"""Anthropic (Claude) provider."""
from __future__ import annotations
import asyncio

from .base import BaseProvider, Turn


class AnthropicProvider(BaseProvider):
    def __init__(self, pconf: dict):
        self.pconf = pconf
        self._client = None

    def _client_(self):
        if self._client is None:
            from anthropic import Anthropic
            self._client = Anthropic(api_key=self.pconf["api_key"])
        return self._client

    @staticmethod
    def _convert(messages: list, tools: list):
        amsgs = []
        for m in messages:
            role = m["role"]
            if role == "user":
                amsgs.append({"role": "user", "content": m["content"]})
            elif role == "assistant":
                content = []
                if m.get("content"):
                    content.append({"type": "text", "text": m["content"]})
                for tc in m.get("tool_calls", []):
                    content.append({"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["args"]})
                amsgs.append({"role": "assistant", "content": content or "…"})
            elif role == "tool":
                amsgs.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
                ]})
        atools = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools]
        return amsgs, atools

    async def complete(self, system, messages, tools) -> Turn:
        client = self._client_()
        model = self.pconf.get("model", "claude-opus-4-8")
        amsgs, atools = self._convert(messages, tools)

        def call():
            return client.messages.create(
                model=model, system=system, messages=amsgs, tools=atools, max_tokens=4096,
            )

        resp = await asyncio.to_thread(call)
        text, tcs = "", []
        for block in resp.content:
            if block.type == "text":
                text += block.text
            elif block.type == "tool_use":
                tcs.append({"id": block.id, "name": block.name, "args": block.input})
        return Turn(text=text, tool_calls=tcs)
