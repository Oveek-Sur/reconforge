"""Agent tools — the Kali capabilities the assistant can call autonomously.

Each tool is provider-agnostic: a name, JSON-schema parameters, and an async fn
returning a string. providers/* translate TOOL_DEFS into their own tool format.
"""
from __future__ import annotations
import asyncio
import shutil
from pathlib import Path

import httpx

MAX_OUT = 12000


def _clip(s: str) -> str:
    return s if len(s) <= MAX_OUT else s[:MAX_OUT] + f"\n…[truncated {len(s) - MAX_OUT} chars]"


async def run_shell(command: str, timeout: int = 120, sudo: bool = False, *, cfg=None) -> str:
    settings = (cfg or {}).get("settings", {})
    if not settings.get("allow_shell", True):
        return "[blocked] shell execution disabled in settings"
    if sudo:
        if not settings.get("allow_sudo", False):
            return "[blocked] sudo not allowed — enable allow_sudo (needs NOPASSWD sudoers)"
        command = "sudo -n " + command
    try:
        proc = await asyncio.create_subprocess_shell(
            command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return _clip(f"$ {command}\n{out.decode('utf-8', 'replace')}\n[exit {proc.returncode}]")
    except asyncio.TimeoutError:
        return f"[timeout] '{command}' exceeded {timeout}s"
    except Exception as e:  # noqa: BLE001
        return f"[error] {e}"


async def read_file(path: str, offset: int = 0, limit: int = 400, **_) -> str:
    p = Path(path)
    if not p.exists():
        return f"[not found] {path}"
    try:
        lines = p.read_text("utf-8", "replace").splitlines()
    except Exception as e:  # noqa: BLE001
        return f"[error] {e}"
    chunk = lines[offset: offset + limit]
    body = "\n".join(f"{offset + i + 1}\t{ln}" for i, ln in enumerate(chunk))
    return _clip(body or "[empty range]")


async def list_dir(path: str, **_) -> str:
    p = Path(path)
    if not p.exists():
        return f"[not found] {path}"
    if p.is_file():
        return f"[file] {path} ({p.stat().st_size} bytes)"
    entries = []
    for c in sorted(p.iterdir())[:500]:
        entries.append(("📁 " if c.is_dir() else "📄 ") + c.name)
    return _clip("\n".join(entries) or "[empty dir]")


async def grep(pattern: str, path: str, glob: str = "", **_) -> str:
    rg = shutil.which("rg")
    if rg:
        cmd = [rg, "-n", "--no-heading", "-S", pattern, path]
        if glob:
            cmd[1:1] = ["-g", glob]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
            return _clip(out.decode("utf-8", "replace") or "[no matches]")
        except asyncio.TimeoutError:
            return "[timeout] grep took too long — narrow the path"
    # python fallback
    import re as _re
    rx = _re.compile(pattern)
    hits = []
    base = Path(path)
    files = [base] if base.is_file() else list(base.rglob(glob or "*"))[:2000]
    for f in files:
        if not f.is_file():
            continue
        try:
            for i, ln in enumerate(f.read_text("utf-8", "replace").splitlines(), 1):
                if rx.search(ln):
                    hits.append(f"{f}:{i}:{ln.strip()[:200]}")
                    if len(hits) >= 200:
                        return _clip("\n".join(hits))
        except Exception:
            continue
    return _clip("\n".join(hits) or "[no matches]")


async def http_request(method: str, url: str, headers: dict | None = None, body: str | None = None, **_) -> str:
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, verify=True) as c:
            r = await c.request(method.upper(), url, headers=headers or {}, content=body)
        head = "\n".join(f"{k}: {v}" for k, v in r.headers.items())
        return _clip(f"HTTP {r.status_code}\n{head}\n\n{r.text[:4000]}")
    except Exception as e:  # noqa: BLE001
        return f"[error] {e}"


async def adb(args: str, *, cfg=None) -> str:
    return await run_shell(f"adb {args}", timeout=90, cfg=cfg)


async def setup_environment(**_) -> str:
    """Run the self-setup bootstrap (Android SDK + emulator + system image + mitmproxy)."""
    script = Path(__file__).resolve().parent.parent / "scripts" / "bootstrap.sh"
    if not script.exists():
        return f"[error] bootstrap.sh not found at {script}"
    try:
        proc = await asyncio.create_subprocess_shell(
            f'bash "{script}"', stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=3000)
    except asyncio.TimeoutError:
        return "[timeout] setup exceeded 50 min — re-run; sdkmanager may still be downloading"
    except Exception as e:  # noqa: BLE001
        return f"[error] {e}"
    text = out.decode("utf-8", "replace")
    # keep the TAIL — the SUMMARY block is at the end
    return text if len(text) <= MAX_OUT else "…[head truncated]\n" + text[-MAX_OUT:]


# ── tool schema (JSON-schema params) ───────────────────────────────────────────
TOOL_DEFS = [
    {
        "name": "run_shell",
        "description": "Run a shell command on the Kali box. Use for any Kali tool (nmap, apktool, mitmdump, etc.). Set sudo=true only when required.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer", "default": 120},
                "sudo": {"type": "boolean", "default": False},
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a slice of a text file (returns numbered lines).",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "offset": {"type": "integer", "default": 0},
                "limit": {"type": "integer", "default": 400},
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_dir",
        "description": "List a directory (files and folders).",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    },
    {
        "name": "grep",
        "description": "Search file contents with ripgrep (regex). Scope with a path and optional glob.",
        "parameters": {
            "type": "object",
            "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}, "glob": {"type": "string"}},
            "required": ["pattern", "path"],
        },
    },
    {
        "name": "http_request",
        "description": "Send an HTTP request (recon/verify an endpoint). Non-destructive by default.",
        "parameters": {
            "type": "object",
            "properties": {
                "method": {"type": "string", "default": "GET"},
                "url": {"type": "string"},
                "headers": {"type": "object"},
                "body": {"type": "string"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "adb",
        "description": "Run an adb subcommand against the connected device/emulator (e.g. 'shell am start ...').",
        "parameters": {"type": "object", "properties": {"args": {"type": "string"}}, "required": ["args"]},
    },
    {
        "name": "setup_environment",
        "description": "Self-install the Android testing environment (SDK, emulator, google_apis x86_64 API-34 image, AVD, mitmproxy) by running the bootstrap script. Read the SUMMARY; if anything is MISSING, diagnose with shell tools and fix it, then call again.",
        "parameters": {"type": "object", "properties": {}},
    },
]

_FUNCS = {
    "run_shell": run_shell, "read_file": read_file, "list_dir": list_dir,
    "grep": grep, "http_request": http_request, "adb": adb,
    "setup_environment": setup_environment,
}


async def execute_tool(name: str, args: dict, cfg: dict) -> str:
    fn = _FUNCS.get(name)
    if not fn:
        return f"[error] unknown tool {name}"
    try:
        if name in ("run_shell", "adb"):
            return await fn(cfg=cfg, **args)
        return await fn(**args)
    except TypeError as e:
        return f"[error] bad args for {name}: {e}"
