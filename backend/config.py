"""Persistent config: LLM providers, API keys, settings. Stored as JSON."""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CONFIG_PATH = DATA_DIR / "config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "active_provider": "azure_openai",
    "providers": {
        "azure_openai": {
            "endpoint": "",          # https://<res>.openai.azure.com
            "api_key": "",
            "deployment": "gpt-5",   # your Azure deployment name
            "api_version": "2024-08-01-preview",
        },
        "anthropic": {"api_key": "", "model": "claude-opus-4-8"},
        "openrouter": {"api_key": "", "model": "anthropic/claude-opus-4"},
        "openai": {"api_key": "", "model": "gpt-5", "base_url": "https://api.openai.com/v1"},
        "gemini": {"api_key": "", "model": "gemini-2.5-pro"},
        "vertex": {"project": "", "location": "us-central1", "model": "gemini-2.5-pro"},
    },
    "settings": {
        "allow_shell": True,
        "allow_sudo": False,          # opt-in; relies on NOPASSWD sudoers
        "workspace_dir": str(DATA_DIR / "workspaces"),
        "max_agent_steps": 40,
        "system_prompt": (
            "You are ReconForge, an autonomous mobile-app security assistant running on the "
            "user's Kali Linux VM for AUTHORIZED bug-bounty/pentest work. You have tools to run "
            "shell commands (sudo is authorized), read/list/grep the decompiled APK, make HTTP "
            "requests, drive adb, and self-provision the environment. "
            "Work like a methodical bug hunter: recon the app structure, form hypotheses, verify "
            "them with tools, and report findings with file:line evidence and honest severity. "
            "SELF-PROVISION: if a tool (emulator, adb, mitmproxy, jadx) is missing, install it "
            "yourself — call setup_environment, read its SUMMARY, and if a step failed, diagnose "
            "(missing apt packages, SDK licenses, PATH, /dev/kvm) and FIX it autonomously, then "
            "retry; never ask the user to run a command you can run yourself. "
            "Never attack out-of-scope targets. Prefer non-destructive checks. Explain what you run."
        ),
    },
}


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.exists():
        try:
            user = json.loads(CONFIG_PATH.read_text("utf-8"))
            return _deep_merge(DEFAULT_CONFIG, user)
        except Exception:
            pass
    return json.loads(json.dumps(DEFAULT_CONFIG))


def save(cfg: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), "utf-8")


def redacted(cfg: dict[str, Any]) -> dict[str, Any]:
    """Copy with API keys masked, for sending to the UI."""
    c = json.loads(json.dumps(cfg))
    for p in c.get("providers", {}).values():
        for key in ("api_key",):
            if p.get(key):
                p[key] = p[key][:4] + "…" + p[key][-2:] if len(p[key]) > 6 else "•••"
    return c


def workspace_dir() -> Path:
    d = Path(load()["settings"]["workspace_dir"])
    d.mkdir(parents=True, exist_ok=True)
    return d
