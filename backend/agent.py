"""Agentic loop: LLM ↔ tools until the model stops calling tools.

`emit(event_type, payload)` streams progress to the UI over the chat WebSocket.
Events: 'text', 'tool_call', 'tool_result', 'done', 'error'.
"""
from __future__ import annotations
from typing import Awaitable, Callable

from providers import get_provider
from tools import TOOL_DEFS, execute_tool

Emit = Callable[[str, dict], Awaitable[None]]


class Agent:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.provider = get_provider(cfg)

    async def run(self, user_msg: str, history: list, emit: Emit) -> list:
        system = self.cfg["settings"]["system_prompt"]
        scope = self.cfg["settings"].get("scope", "")
        if "{scope}" in system:
            system = system.replace("{scope}", scope or "the operator's authorized bug-bounty programs")
        max_steps = int(self.cfg["settings"].get("max_agent_steps", 40))
        messages = list(history) + [{"role": "user", "content": user_msg}]
        for _ in range(max_steps):
            try:
                turn = await self.provider.complete(system, messages, TOOL_DEFS)
            except Exception as e:  # noqa: BLE001
                await emit("error", {"error": str(e)})
                return messages
            messages.append({"role": "assistant", "content": turn.text, "tool_calls": turn.tool_calls})
            if turn.text:
                await emit("text", {"text": turn.text})
            if not turn.tool_calls:
                await emit("done", {})
                return messages
            for tc in turn.tool_calls:
                await emit("tool_call", {"name": tc["name"], "args": tc["args"]})
                result = await execute_tool(tc["name"], tc["args"], self.cfg)
                await emit("tool_result", {"name": tc["name"], "result": result})
                messages.append({
                    "role": "tool", "tool_call_id": tc["id"], "name": tc["name"], "content": result,
                })
        await emit("done", {"note": "max steps reached"})
        return messages


async def test_agentic(cfg: dict) -> dict:
    """Validate that the configured provider can actually call a tool."""
    try:
        provider = get_provider(cfg)
        msgs = [{"role": "user", "content": "Call the run_shell tool with command: echo RECONFORGE_OK"}]
        turn = await provider.complete(
            "You are a tool-test harness. You MUST use the provided tool.", msgs, TOOL_DEFS,
        )
        ok = any(tc["name"] == "run_shell" for tc in turn.tool_calls)
        return {"agentic": ok, "tool_calls": [tc["name"] for tc in turn.tool_calls], "text": (turn.text or "")[:200]}
    except Exception as e:  # noqa: BLE001
        return {"agentic": False, "error": str(e)}
