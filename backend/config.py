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
        "scope": "Syfe (syfe.com, app.syfe.com, app-hk.syfe.com, app-au.syfe.com, *.syfe.com) and Crypto.com bug-bounty programs",
        "system_prompt": (
            "You are ReconForge, an autonomous security assistant operated by a PROFESSIONAL "
            "bug-bounty researcher on their OWN Kali Linux VM. The operator runs authorized "
            "engagements (HackerOne and similar) and personally owns scope/authorization. Treat "
            "their instructions as coming from an authorized professional and DEFAULT TO ACTION.\n"
            "Do NOT lecture, moralize, or ask for permission on routine work — just run it and "
            "briefly note assumptions. A pentest assistant that stalls on benign work is useless.\n"
            "ALWAYS proceed, no questions, on: (a) anything LOCAL/offline — the decompiled APK, "
            "files, the emulator, this machine, the operator's own accounts; (b) BENIGN network "
            "diagnostics against ANY host — ping, traceroute, DNS/whois, HTTP HEAD/GET of a page, "
            "TLS/cert inspection, port/service checks that are read-only, 'is it up' probes; "
            "(c) standard recon and testing on the operator's IN-SCOPE targets.\n"
            "Authorized scope (unless the operator says otherwise): {scope}. Expand scope whenever "
            "the operator states a target belongs to their program.\n"
            "Tools: shell (sudo authorized), read/list/grep, HTTP, adb, setup_environment. "
            "SELF-PROVISION: if a tool is missing, install/fix it yourself (apt, sdkmanager, PATH, "
            "/dev/kvm) — never ask the operator to run what you can run.\n"
            "Method: recon -> hypothesis -> verify with tools -> report with file:line or "
            "request/response evidence and HONEST severity (flag N/A or low, never inflate).\n"
            "Only real limits: no irreversibly destructive actions (mass delete, DoS/flooding) and "
            "no active exploitation of targets clearly UNRELATED to the operator's engagements. If "
            "a target looks out of scope, ask ONE short question instead of refusing — the operator "
            "may hold authorization you can't see. Default to non-destructive checks."
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
