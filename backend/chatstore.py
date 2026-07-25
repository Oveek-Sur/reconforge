"""Persist chat history so conversations survive reload/restart (AionUi-style)."""
from __future__ import annotations
import json

from config import DATA_DIR

HISTORY = DATA_DIR / "chat_history.json"
MAX_MSGS = 200


def load() -> list:
    try:
        return json.loads(HISTORY.read_text("utf-8"))
    except Exception:
        return []


def save(messages: list) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        HISTORY.write_text(json.dumps(messages[-MAX_MSGS:]), "utf-8")
    except Exception:
        pass


def clear() -> None:
    try:
        HISTORY.unlink()
    except Exception:
        pass


def display(history: list) -> list:
    """Neutral agent history -> renderable [{role:'user'|'ai', text}] (skip tool internals)."""
    out = []
    for m in history:
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            out.append({"role": "user", "text": m["content"]})
        elif m.get("role") == "assistant" and m.get("content"):
            out.append({"role": "ai", "text": m["content"]})
    return out
