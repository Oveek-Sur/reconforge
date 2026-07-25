"""Provider abstraction. A provider converts a neutral message history + tool
defs into its own API format, does one completion, and returns a Turn."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Turn:
    text: str = ""
    tool_calls: list = field(default_factory=list)  # [{"id","name","args": dict}]


class BaseProvider:
    async def complete(self, system: str, messages: list, tools: list) -> Turn:  # noqa: D401
        raise NotImplementedError
