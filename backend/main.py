"""ReconForge backend — FastAPI app: serves the UI, runs jadx with live progress,
exposes the file tree + static structure, and drives the agentic chat + emulator."""
from __future__ import annotations
import asyncio
import hmac
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import Body, FastAPI, Header, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

import analyzer
import chatstore
import config as cfgmod
import decompiler
import emulator
import frida as fridamod
from agent import Agent, quick_comment, test_agentic

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend" / "index.html"

app = FastAPI(title="ReconForge")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

JOBS: dict[str, dict] = {}


@app.get("/")
async def index():
    return FileResponse(FRONTEND)


# ── config ─────────────────────────────────────────────────────────────────────
@app.get("/api/config")
async def get_config():
    return cfgmod.redacted(cfgmod.load())


@app.post("/api/config")
async def set_config(patch: dict = Body(...)):
    cur = cfgmod.load()

    def merge(a: dict, b: dict):
        for k, v in b.items():
            if isinstance(v, dict) and isinstance(a.get(k), dict):
                merge(a[k], v)
            else:
                # never overwrite a real key with a masked ('…') value from the UI
                if k == "api_key" and isinstance(v, str) and "…" in v:
                    continue
                a[k] = v

    merge(cur, patch)
    cfgmod.save(cur)
    return cfgmod.redacted(cur)


@app.post("/api/test-agentic")
async def api_test_agentic():
    return await test_agentic(cfgmod.load())


# ── filesystem browse / tree / file ─────────────────────────────────────────────
@app.get("/api/browse")
async def browse(path: str = Query("")):
    p = Path(path) if path else Path.home()
    if not p.exists():
        return JSONResponse({"error": "not found"}, 404)
    items = []
    if p.is_dir():
        for c in sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
            try:
                items.append({"name": c.name, "path": str(c), "dir": c.is_dir()})
            except Exception:
                pass
    return {"path": str(p), "parent": str(p.parent), "items": items}


@app.get("/api/tree")
async def tree(path: str = Query(...)):
    p = Path(path)
    if not p.exists():
        return JSONResponse({"error": "not found"}, 404)
    items = []
    for c in sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
        items.append({"name": c.name, "path": str(c), "dir": c.is_dir()})
    return {"path": str(p), "items": items}


@app.get("/api/file")
async def get_file(path: str = Query(...)):
    p = Path(path)
    if not p.exists() or not p.is_file():
        return JSONResponse({"error": "not found"}, 404)
    try:
        data = p.read_text("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, 500)
    return {"path": str(p), "content": data[:200_000]}


# ── analyze (jadx + static structure) over WebSocket ────────────────────────────
@app.websocket("/ws/analyze")
async def ws_analyze(ws: WebSocket):
    await ws.accept()
    try:
        req = json.loads(await ws.receive_text())
        apk = req["apk_path"]
        if not Path(apk).exists():
            await ws.send_json({"type": "error", "error": f"APK not found: {apk}"})
            return
        stem = Path(apk).stem
        out_dir = cfgmod.workspace_dir() / stem / "jadx"

        async def on_prog(pct: int, msg: str):
            await ws.send_json({"type": "progress", "pct": pct, "msg": msg})

        async def on_log(line: str):
            await ws.send_json({"type": "log", "line": line})

        await ws.send_json({"type": "stage", "stage": "decompiling"})
        rc = await decompiler.run_jadx(apk, str(out_dir), on_prog, on_log)
        await ws.send_json({"type": "stage", "stage": "analyzing"})
        structure = analyzer.analyze_apk(apk, str(out_dir))
        JOBS[stem] = {"out_dir": str(out_dir), "structure": structure}
        await ws.send_json({
            "type": "done", "rc": rc,
            "sources": str(out_dir / "sources"),
            "structure": structure,
        })
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        try:
            await ws.send_json({"type": "error", "error": str(e)})
        except Exception:
            pass


# ── agentic chat over WebSocket ─────────────────────────────────────────────────
@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket):
    await ws.accept()
    history: list = chatstore.load()
    await ws.send_json({"type": "history", "messages": chatstore.display(history)})
    try:
        while True:
            req = json.loads(await ws.receive_text())
            if req.get("reset"):
                history = []
                chatstore.clear()
                continue
            msg = req.get("message", "")
            cfg = cfgmod.load()
            try:
                agent = Agent(cfg)
            except Exception as e:  # provider not configured
                await ws.send_json({"type": "error", "error": f"provider: {e}"})
                continue

            async def emit(t: str, p: dict):
                await ws.send_json({"type": t, **p})

            history = await agent.run(msg, history, emit)
            chatstore.save(history)
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        try:
            await ws.send_json({"type": "error", "error": str(e)})
        except Exception:
            pass


# ── emulator screenshot (phase-2 preview) ───────────────────────────────────────
@app.get("/api/emulator/screenshot")
async def emu_shot():
    try:
        proc = await asyncio.create_subprocess_shell(
            "adb exec-out screencap -p",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=20)
        if not out:
            return JSONResponse({"error": err.decode("utf-8", "replace") or "no device"}, 502)
        return Response(content=out, media_type="image/png")
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, 502)


# ── emulator control ────────────────────────────────────────────────────────────
@app.get("/api/emulator/devices")
async def emu_devices():
    return {"out": await emulator.devices()}


@app.get("/api/emulator/avds")
async def emu_avds():
    return {"avds": await emulator.list_avds()}


@app.post("/api/emulator/start")
async def emu_start(body: dict = Body(...)):
    return await emulator.start_avd(body["avd"], body.get("headless", False), body.get("proxy"))


@app.post("/api/emulator/stop")
async def emu_stop():
    return await emulator.stop()


@app.post("/api/emulator/install")
async def emu_install(body: dict = Body(...)):
    return {"out": await emulator.install_apk(body["apk_path"])}


@app.post("/api/emulator/launch")
async def emu_launch(body: dict = Body(...)):
    return {"out": await emulator.launch_app(body["package"])}


@app.post("/api/emulator/input")
async def emu_input(body: dict = Body(...)):
    kind = body.pop("kind")
    return {"out": await emulator.input_event(kind, **body)}


# ── Frida SSL-unpin + decrypted capture (defeats pinning / system-CA-only apps) ──
@app.get("/api/frida/versions")
async def frida_versions():
    return await fridamod.versions()


@app.post("/api/frida/ensure-server")
async def frida_ensure():
    return await fridamod.ensure_server()


@app.post("/api/frida/capture-start")
async def frida_capture_start(body: dict = Body(...)):
    return await fridamod.capture_start(
        body["package"], int(body.get("port", 8080)), body.get("drive", True)
    )


@app.get("/api/frida/capture-status")
async def frida_capture_status():
    return await fridamod.capture_status()


@app.post("/api/frida/capture-stop")
async def frida_capture_stop():
    return await fridamod.capture_stop()


@app.get("/api/frida/flows")
async def frida_flows(host: str = Query(default="")):
    return {"flows": await fridamod.flows(host)}


@app.get("/api/frida/analyze")
async def frida_analyze():
    return {"report": await fridamod.analyze()}


# ── network intercept (mitmproxy sidecar → UI) ──────────────────────────────────
INTERCEPT_WS: set = set()
MITM: dict = {"proc": None}


@app.websocket("/ws/intercept")
async def ws_intercept(ws: WebSocket):
    await ws.accept()
    INTERCEPT_WS.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        INTERCEPT_WS.discard(ws)


@app.post("/api/intercept/push")
async def intercept_push(flow: dict = Body(...)):
    dead = []
    for ws in list(INTERCEPT_WS):
        try:
            await ws.send_json({"type": "flow", **flow})
        except Exception:
            dead.append(ws)
    for ws in dead:
        INTERCEPT_WS.discard(ws)
    return {"ok": True, "subs": len(INTERCEPT_WS)}


@app.post("/api/intercept/start")
async def intercept_start(body: dict = Body(default={})):
    if not shutil.which("mitmdump"):
        return {"running": False, "error": "mitmdump not installed — run 🛠 Auto-setup or: sudo apt install -y mitmproxy"}
    port = int(body.get("port", 8080))
    # Clean our previous proc + any stale mitmdump holding the port. This fixes the
    # silent 'running but never bound' when an old instance from an earlier Start lingers.
    if MITM.get("proc") and MITM["proc"].returncode is None:
        try:
            MITM["proc"].terminate()
        except Exception:
            pass
    try:
        killer = await asyncio.create_subprocess_shell("pkill -x mitmdump 2>/dev/null")
        await killer.wait()
    except Exception:
        pass
    await asyncio.sleep(0.6)
    addon = str(Path(__file__).resolve().parent / "mitm_addon.py")
    logf = str(cfgmod.DATA_DIR / "mitm.log")
    MITM["proc"] = await asyncio.create_subprocess_shell(
        f'mitmdump -p {port} -s "{addon}" > "{logf}" 2>&1',
    )
    await asyncio.sleep(1.8)  # let it bind (or fail)
    if MITM["proc"].returncode is not None:
        tail = ""
        try:
            tail = Path(logf).read_text("utf-8", "replace")[-400:]
        except Exception:
            pass
        return {"running": False, "error": f"mitmdump exited (code {MITM['proc'].returncode}). Port {port} in use? {tail}"}
    if body.get("set_device_proxy", True):
        # 10.0.2.2 is the host loopback as seen from inside an AVD
        await emulator.set_proxy(f"10.0.2.2:{port}")
    return {"running": True, "port": port, "pid": MITM["proc"].pid}


@app.post("/api/intercept/stop")
async def intercept_stop():
    p = MITM["proc"]
    if p and p.returncode is None:
        p.terminate()
    await emulator.clear_proxy()
    MITM["proc"] = None
    return {"running": False}


# ── AI comment on an intercepted flow + chat history persistence ────────────────
@app.post("/api/intercept/analyze")
async def intercept_analyze(flow: dict = Body(...)):
    summary = (
        f"{flow.get('method')} {flow.get('url')} -> {flow.get('status')}\n"
        f"req_headers: {json.dumps(flow.get('req_headers', {}))[:800]}\n"
        f"req_body: {(flow.get('req_body') or '')[:800]}\n"
        f"res_body: {(flow.get('res_body') or '')[:800]}"
    )
    return {"comment": await quick_comment(cfgmod.load(), summary)}


@app.get("/api/history")
async def get_history():
    return {"messages": chatstore.display(chatstore.load())}


@app.post("/api/history/clear")
async def clear_history():
    chatstore.clear()
    return {"ok": True}


# ── live setup console (streams bootstrap.sh line-by-line) ───────────────────────
@app.websocket("/ws/setup")
async def ws_setup(ws: WebSocket):
    await ws.accept()
    script = ROOT / "scripts" / "bootstrap.sh"
    await ws.send_json({"type": "line", "line": f"$ bash {script}"})
    try:
        proc = await asyncio.create_subprocess_shell(
            f'bash "{script}"', stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        assert proc.stdout is not None
        async for raw in proc.stdout:
            await ws.send_json({"type": "line", "line": raw.decode("utf-8", "replace").rstrip()})
        rc = await proc.wait()
        await ws.send_json({"type": "done", "rc": rc})
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        try:
            await ws.send_json({"type": "line", "line": f"[error] {e}"})
        except Exception:
            pass


# ── remote command exec (token-gated) + environment self-test ───────────────────
@app.post("/api/exec")
async def remote_exec(body: dict = Body(...), x_rf_token: str = Header(default="")):
    tok = cfgmod.load()["settings"].get("remote_token", "")
    if not tok:
        return JSONResponse({"error": "remote exec disabled — set a remote_token in Settings"}, 403)
    if not hmac.compare_digest(str(x_rf_token), str(tok)):
        return JSONResponse({"error": "bad token"}, 403)
    command = body.get("command", "")
    if body.get("sudo"):
        command = "sudo -n " + command
    timeout = int(body.get("timeout", 120))
    try:
        proc = await asyncio.create_subprocess_shell(
            command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {"rc": proc.returncode, "out": out.decode("utf-8", "replace")[:200000]}
    except asyncio.TimeoutError:
        return {"rc": 124, "out": f"[timeout after {timeout}s]"}
    except Exception as e:  # noqa: BLE001
        return {"rc": -1, "out": f"[error] {e}"}


@app.get("/api/selftest")
async def selftest():
    emu = bool(shutil.which("emulator")) or (Path(emulator.android_home()) / "emulator" / "emulator").exists()
    return {
        "mitmdump": bool(shutil.which("mitmdump")),
        "adb": bool(shutil.which("adb")),
        "emulator": emu,
        "jadx": bool(decompiler.find_jadx()),
        "ripgrep": bool(shutil.which("rg")),
        "kvm": Path("/dev/kvm").exists(),
        "intercept_running": bool(MITM.get("proc") and MITM["proc"].returncode is None),
        "avds": await emulator.list_avds(),
    }


# ── self-update from GitHub (git pull) ──────────────────────────────────────────
@app.post("/api/self-update")
async def self_update():
    proc = await asyncio.create_subprocess_shell(
        "git pull --ff-only origin main", cwd=str(ROOT),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
    except asyncio.TimeoutError:
        return {"out": "git pull timed out", "rc": 124}
    return {"out": out.decode("utf-8", "replace"), "rc": proc.returncode}


if __name__ == "__main__":
    import os
    import uvicorn
    host = os.environ.get("RECONFORGE_HOST", "127.0.0.1")
    reload = os.environ.get("RECONFORGE_RELOAD") == "1"
    print(f"ReconForge -> http://{host}:8777" + (" [hot-reload]" if reload else ""))
    if reload:
        uvicorn.run("main:app", host=host, port=8777, reload=True)
    else:
        uvicorn.run(app, host=host, port=8777)
