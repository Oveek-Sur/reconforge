"""OpenAI-compatible provider — covers Azure-OpenAI, OpenAI, OpenRouter, and
Gemini (via its OpenAI-compatible endpoint). Runs the sync SDK in a thread."""
from __future__ import annotations
import asyncio
import json

from .base import BaseProvider, Turn

_BASE_URLS = {
    "openrouter": "https://openrouter.ai/api/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
}


class OpenAIProvider(BaseProvider):
    def __init__(self, kind: str, pconf: dict):
        self.kind = kind
        self.pconf = pconf
        self._client = None
        self._model = None

    def _client_model(self):
        if self._client is not None:
            return self._client, self._model
        if self.kind == "azure_openai":
            ep = (self.pconf.get("endpoint") or "").rstrip("/")
            # New Azure AI Foundry v1 API (…/openai/v1) is OpenAI-compatible → plain OpenAI client.
            if "services.ai.azure.com" in ep or ep.endswith("/openai/v1"):
                from openai import OpenAI
                base = ep if ep.endswith("/openai/v1") else ep + "/openai/v1"
                self._client = OpenAI(api_key=self.pconf["api_key"], base_url=base)
                self._model = self.pconf.get("deployment") or self.pconf.get("model")
            else:  # classic Azure OpenAI (…​.openai.azure.com)
                from openai import AzureOpenAI
                self._client = AzureOpenAI(
                    azure_endpoint=ep,
                    api_key=self.pconf["api_key"],
                    api_version=self.pconf.get("api_version", "2024-08-01-preview"),
                )
                self._model = self.pconf["deployment"]
        else:
            from openai import OpenAI
            base = _BASE_URLS.get(self.kind, self.pconf.get("base_url"))
            self._client = OpenAI(api_key=self.pconf["api_key"], base_url=base)
            self._model = self.pconf["model"]
        return self._client, self._model

    @staticmethod
    def _convert(system: str, messages: list, tools: list):
        out = [{"role": "system", "content": system}]
        for m in messages:
            role = m["role"]
            if role == "user":
                out.append({"role": "user", "content": m["content"]})
            elif role == "assistant":
                a = {"role": "assistant", "content": m.get("content") or None}
                if m.get("tool_calls"):
                    a["tool_calls"] = [
                        {"id": tc["id"], "type": "function",
                         "function": {"name": tc["name"], "arguments": json.dumps(tc["args"])}}
                        for tc in m["tool_calls"]
                    ]
                out.append(a)
            elif role == "tool":
                out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
        otools = [{"type": "function", "function": t} for t in tools]
        return out, otools

    async def complete(self, system, messages, tools) -> Turn:
        client, model = self._client_model()
        omsgs, otools = self._convert(system, messages, tools)

        def call():
            return client.chat.completions.create(
                model=model, messages=omsgs, tools=otools, tool_choice="auto",
            )

        resp = await asyncio.to_thread(call)
        msg = resp.choices[0].message
        tcs = []
        for tc in (msg.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            tcs.append({"id": tc.id, "name": tc.function.name, "args": args})
        return Turn(text=msg.content or "", tool_calls=tcs)
