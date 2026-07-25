"""Frida SSL-unpinning + decrypted-traffic capture for the embedded emulator.

Turns the emulator into a full MITM box even when the target app pins certs or
only trusts system CAs: pushes a matching frida-server, attaches a universal
SSL-unpin script (so the app trusts mitmproxy's CA), routes its HTTPS through
mitmproxy, and records decrypted request/response flows to flows.jsonl.

Battle-tested against Syfe (com.syfe) on an API-34 google_apis x86_64 AVD:
frida 17 removed the legacy `Java` global, so we pin frida 16.7.19 (client
binding + device server) which the classic Java.perform() unpin script needs.
spawn-gating throws DeadSystemException on API-34, so we launch the app normally
and attach by PID (the per-handshake TrustManagerImpl hook works on attach).

All long-running children are started DEVNULL-detached (never awaited) so the
FastAPI event loop is never blocked and no pipe is held open.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
VENV_PY = ROOT / ".venv" / "bin" / "python3"

FRIDA_VERSION = "16.7.19"  # has the legacy `Java` global the unpin script needs

UNPIN_JS = SCRIPTS / "frida-ssl-unpin.js"
ATTACH_PY = SCRIPTS / "frida_attach.py"
FLOWLOG_PY = SCRIPTS / "mitm_flowlog.py"
ANALYZE_PY = SCRIPTS / "analyze_flows.py"

FLOWS = "/tmp/rf_flows.jsonl"
MITM_LOG = "/tmp/rf_mitm.log"
FRIDA_LOG = "/tmp/rf_frida.log"
FR_PIDFILE = "/tmp/rf_frida.pid"
MITM_PIDFILE = "/tmp/rf_mitm.pid"


def _py() -> str:
    return str(VENV_PY) if VENV_PY.exists() else "python3"


async def _sh(cmd: str, timeout: int = 120) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        return 124, f"[timeout] {cmd}"
    return proc.returncode, out.decode("utf-8", "replace")


async def _detach(cmd: str) -> int:
    """Start a long-running process fully detached; return its pid, never await."""
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        stdin=asyncio.subprocess.DEVNULL,
    )
    return proc.pid


async def device_abi() -> str:
    _, out = await _sh("adb shell getprop ro.product.cpu.abi")
    return out.strip() or "x86_64"


async def versions() -> dict:
    _, binv = await _sh(f'"{_py()}" -c "import frida;print(frida.__version__)"')
    _, srv = await _sh("adb shell 'pgrep -x frida-server >/dev/null && echo up || echo down'")
    return {"client": binv.strip(), "server_state": srv.strip(), "pinned": FRIDA_VERSION}


async def ensure_server() -> dict:
    """Pin the frida client binding, download the matching frida-server for the
    device ABI, push it, and (re)start it as root. Idempotent."""
    steps = []
    # 1. pin client binding
    _, o = await _sh(f'"{_py()}" -m pip install -q "frida=={FRIDA_VERSION}" 2>&1 | tail -2', timeout=180)
    steps.append(f"pip: {o.strip()[:120]}")
    # 2. download server for ABI
    abi = await device_abi()
    url = (f"https://github.com/frida/frida/releases/download/{FRIDA_VERSION}/"
           f"frida-server-{FRIDA_VERSION}-android-{abi}.xz")
    _, o = await _sh(
        f"curl -sL -o /tmp/rf_fs.xz {url} && unxz -f /tmp/rf_fs.xz && ls -l /tmp/rf_fs | awk '{{print $5}}'",
        timeout=180,
    )
    steps.append(f"download({abi}): {o.strip()[:80]}")
    # 3. push + run as root
    await _sh("adb root", timeout=30)
    await _sh("adb wait-for-device", timeout=30)
    await _sh('adb shell "pkill -x frida-server 2>/dev/null"')
    _, o = await _sh("adb push /tmp/rf_fs /data/local/tmp/frida-server 2>&1 | tail -1")
    steps.append(f"push: {o.strip()[:80]}")
    await _sh("adb shell chmod 755 /data/local/tmp/frida-server")
    await _detach('adb shell "setsid /data/local/tmp/frida-server >/dev/null 2>&1 &"')
    await asyncio.sleep(3)
    _, state = await _sh("adb shell 'pgrep -x frida-server >/dev/null && echo up || echo down'")
    return {"abi": abi, "server": state.strip(), "steps": steps}


async def _pidof(package: str) -> str:
    _, out = await _sh(f"adb shell pidof {package}")
    return out.strip()


async def _mitmdump_bin() -> str:
    import shutil
    return shutil.which("mitmdump") or str(ROOT / ".venv" / "bin" / "mitmdump")


async def capture_start(package: str, proxy_port: int = 8080, drive: bool = True) -> dict:
    """Full pipeline: mitmdump+flowlog, launch app, attach unpin, set proxy,
    then drive foreground/deeplinks so fresh (decrypted) traffic is recorded."""
    # 0. clean old
    for f in (FLOWS, MITM_LOG, FRIDA_LOG):
        await _sh(f"rm -f {f}")
    for pf in (MITM_PIDFILE, FR_PIDFILE):
        await _sh(f'[ -f {pf} ] && kill "$(cat {pf})" 2>/dev/null; true')
    await _sh("pkill -x mitmdump 2>/dev/null; true")
    # 1. mitmdump + flowlog addon
    mitm = await _mitmdump_bin()
    mitm_pid = await _detach(
        f'"{mitm}" --listen-host 0.0.0.0 -p {proxy_port} --ssl-insecure '
        f'-s "{FLOWLOG_PY}" --set flowlog={FLOWS} >{MITM_LOG} 2>&1'
    )
    await _sh(f"echo {mitm_pid} > {MITM_PIDFILE}")
    await asyncio.sleep(3)
    # 2. frida-server up
    await _sh("adb root", timeout=20)
    await _sh("adb wait-for-device", timeout=20)
    await _detach('adb shell "pgrep -x frida-server >/dev/null || setsid /data/local/tmp/frida-server >/dev/null 2>&1 &"')
    # 3. launch app WITHOUT proxy first (reliable), wait for pid
    await _sh("adb shell settings put global http_proxy :0")
    await _sh(f"adb shell am force-stop {package}")
    await asyncio.sleep(1)
    await _sh(f"adb shell monkey -p {package} -c android.intent.category.LAUNCHER 1")
    pid = ""
    for _ in range(25):
        pid = await _pidof(package)
        if pid:
            break
        await asyncio.sleep(1)
    if not pid:
        return {"error": f"{package} did not start", "mitm_pid": mitm_pid}
    # 4. attach unpin hooks by pid
    fr_pid = await _detach(
        f'"{_py()}" "{ATTACH_PY}" {pid} "{UNPIN_JS}" 1800 >{FRIDA_LOG} 2>&1'
    )
    await _sh(f"echo {fr_pid} > {FR_PIDFILE}")
    await asyncio.sleep(7)
    # 5. proxy on -> subsequent TLS is decryptable
    await _sh(f"adb shell settings put global http_proxy 10.0.2.2:{proxy_port}")
    # 6. drive fresh traffic (process + hooks preserved)
    if drive:
        await _sh("adb shell input keyevent KEYCODE_HOME")
        await asyncio.sleep(2)
        await _sh(f"adb shell am start -n {package}/.MainActivity")
        await asyncio.sleep(3)
    return {"package": package, "app_pid": pid, "mitm_pid": mitm_pid, "frida_pid": fr_pid,
            "flows": FLOWS, "proxy": f"10.0.2.2:{proxy_port}"}


async def capture_status() -> dict:
    _, mitm = await _sh("pgrep -xc mitmdump")
    _, listen = await _sh("ss -ltn 2>/dev/null | grep -c ':8080'")
    _, frlog = await _sh(f"tail -6 {FRIDA_LOG} 2>/dev/null")
    _, nflows = await _sh(f"wc -l < {FLOWS} 2>/dev/null")
    _, hosts = await _sh(
        f"grep -o '\"host\": \"[^\"]*\"' {FLOWS} 2>/dev/null | sort | uniq -c | sort -rn | head -20"
    )
    return {
        "mitmdump": mitm.strip(), "listen8080": listen.strip(),
        "frida_log": frlog.strip(), "flow_count": nflows.strip(), "hosts": hosts.strip(),
    }


async def analyze() -> str:
    _, out = await _sh(f'"{_py()}" "{ANALYZE_PY}" {FLOWS}', timeout=60)
    return out


async def flows(host_filter: str = "") -> list[dict]:
    _, raw = await _sh(f"cat {FLOWS} 2>/dev/null")
    rows = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if host_filter and host_filter not in r.get("host", ""):
            continue
        rows.append(r)
    return rows


async def capture_stop() -> dict:
    for pf in (MITM_PIDFILE, FR_PIDFILE):
        await _sh(f'[ -f {pf} ] && kill "$(cat {pf})" 2>/dev/null; true')
    await _sh("pkill -x mitmdump 2>/dev/null; true")
    await _sh("adb shell settings put global http_proxy :0")
    return {"stopped": True}
