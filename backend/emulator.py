"""Emulator / device control via adb + the Android emulator binary.

Pure-Python, browser-embeddable: the UI mirrors the screen with adb screencap
(see main.py /api/emulator/screenshot) and sends input via `adb shell input`.
Use a google_apis (rootable) AVD so mitmproxy's CA can be installed to /system.
"""
from __future__ import annotations
import asyncio
import os
import shutil
from pathlib import Path

_EMU_PROC = None


def android_home() -> str:
    for e in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if os.environ.get(e):
            return os.environ[e]
    for p in (Path.home() / "Android/Sdk", Path("/opt/android-sdk"), Path("/usr/lib/android-sdk")):
        if p.exists():
            return str(p)
    return ""


def emulator_bin() -> str:
    found = shutil.which("emulator")
    if found:
        return found
    cand = Path(android_home()) / "emulator" / "emulator"
    return str(cand) if cand.exists() else "emulator"


async def _sh(cmd: str, timeout: int = 120):
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        return 124, f"[timeout] {cmd}"
    return proc.returncode, out.decode("utf-8", "replace")


async def devices() -> str:
    return (await _sh("adb devices -l"))[1]


async def list_avds() -> list[str]:
    _, out = await _sh(f'"{emulator_bin()}" -list-avds')
    bad = ("recognized", "not found", "no such", "error", "command", "cannot", "not an")
    return [
        ln.strip() for ln in out.splitlines()
        if ln.strip() and "INFO" not in ln and "/" not in ln
        and not any(b in ln.lower() for b in bad)
    ]


async def start_avd(avd: str, headless: bool = False, proxy: str | None = None, writable: bool = True) -> dict:
    global _EMU_PROC
    args = [f'"{emulator_bin()}"', "-avd", avd, "-no-snapshot-save", "-no-boot-anim"]
    if headless:
        args += ["-no-window", "-no-audio", "-gpu", "swiftshader_indirect"]
    if writable:
        args += ["-writable-system"]
    if proxy:
        args += ["-http-proxy", proxy]
    cmd = " ".join(args)
    _EMU_PROC = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    return {"started": avd, "pid": _EMU_PROC.pid, "cmd": cmd}


async def stop() -> dict:
    await _sh("adb emu kill")
    return {"stopped": True}


async def wait_boot(timeout: int = 120) -> bool:
    for _ in range(timeout):
        _, out = await _sh("adb shell getprop sys.boot_completed")
        if "1" in out:
            return True
        await asyncio.sleep(1)
    return False


async def install_apk(path: str) -> str:
    return (await _sh(f'adb install -r "{path}"', timeout=300))[1]


async def launch_app(package: str) -> str:
    return (await _sh(f"adb shell monkey -p {package} -c android.intent.category.LAUNCHER 1"))[1]


async def input_event(kind: str, **kw) -> str:
    if kind == "tap":
        return (await _sh(f'adb shell input tap {int(kw["x"])} {int(kw["y"])}'))[1]
    if kind == "swipe":
        return (await _sh(
            f'adb shell input swipe {int(kw["x1"])} {int(kw["y1"])} {int(kw["x2"])} {int(kw["y2"])} {int(kw.get("ms", 250))}'
        ))[1]
    if kind == "text":
        return (await _sh(f'adb shell input text "{kw["text"]}"'))[1]
    if kind == "key":
        return (await _sh(f'adb shell input keyevent {kw["key"]}'))[1]
    if kind == "deeplink":
        return (await _sh(f'adb shell am start -a android.intent.action.VIEW -d "{kw["uri"]}"'))[1]
    return f"[unknown input] {kind}"


async def set_proxy(hostport: str) -> str:
    return (await _sh(f"adb shell settings put global http_proxy {hostport}"))[1]


async def clear_proxy() -> str:
    return (await _sh("adb shell settings put global http_proxy :0"))[1]


async def screen_size() -> str:
    return (await _sh("adb shell wm size"))[1]
