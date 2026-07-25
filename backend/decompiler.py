"""jadx decompiler runner that streams progress %.

jadx prints lines like `INFO  - progress: 13391 of 19500 (68%)` to stdout/stderr.
We parse those and invoke an async callback so the UI can show a live progress bar.
Works on Kali (jadx binary) and Windows (jadx.bat) alike.
"""
from __future__ import annotations
import asyncio
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Awaitable, Callable, Optional

PROGRESS_RE = re.compile(r"progress:\s*(\d+)\s+of\s+(\d+)\s+\((\d+)%\)")

ProgressCB = Callable[[int, str], Awaitable[None]]
LogCB = Optional[Callable[[str], Awaitable[None]]]


def find_jadx() -> str:
    """Locate a jadx executable: $JADX, PATH, or common install locations."""
    env = os.environ.get("JADX")
    if env and Path(env).exists():
        return env
    for cand in ("jadx", "jadx.bat"):
        found = shutil.which(cand)
        if found:
            return found
    for p in (
        "/usr/bin/jadx",
        "/opt/jadx/bin/jadx",
        "/usr/local/bin/jadx",
        "D:/backup/kong-3.0.0/apk-analysis/tools/jadx/bin/jadx.bat",
    ):
        if Path(p).exists():
            return p
    return "jadx"  # last resort; will error clearly if missing


def _build_cmd(jadx: str, apk_path: str, out_dir: str) -> list[str]:
    threads = str(max(1, (os.cpu_count() or 4) - 1))
    base = [jadx, "-j", threads, "-d", out_dir, apk_path]
    # On Windows a .bat must run through cmd.exe
    if jadx.lower().endswith(".bat") and sys.platform == "win32":
        return ["cmd", "/c", *base]
    return base


async def run_jadx(
    apk_path: str,
    out_dir: str,
    on_progress: ProgressCB,
    on_log: LogCB = None,
) -> int:
    """Run jadx, streaming progress. Returns the process exit code."""
    jadx = find_jadx()
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    cmd = _build_cmd(jadx, apk_path, out_dir)

    # jadx needs a big heap for large apps; harmless if ignored.
    env = {**os.environ, "JAVA_TOOL_OPTIONS": os.environ.get("JAVA_TOOL_OPTIONS", "-Xmx6g")}

    await on_progress(0, f"launching jadx: {Path(apk_path).name}")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )
    last = -1
    assert proc.stdout is not None
    async for raw in proc.stdout:
        line = raw.decode("utf-8", "replace").rstrip()
        if not line:
            continue
        m = PROGRESS_RE.search(line)
        if m:
            pct = int(m.group(3))
            if pct != last:
                last = pct
                await on_progress(pct, f"{m.group(1)}/{m.group(2)} classes")
        elif on_log:
            await on_log(line)
    rc = await proc.wait()
    await on_progress(100 if rc == 0 else last, "decompiled" if rc == 0 else f"jadx exit {rc}")
    return rc


def sources_dir(out_dir: str) -> Path:
    """jadx writes Java under <out>/sources and resources under <out>/resources."""
    return Path(out_dir) / "sources"
