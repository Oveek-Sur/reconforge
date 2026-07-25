"""Provider factory."""
from __future__ import annotations


def get_provider(cfg: dict):
    name = cfg["active_provider"]
    pconf = cfg["providers"][name]
    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(pconf)
    if name in ("azure_openai", "openai", "openrouter", "gemini"):
        from .openai_provider import OpenAIProvider
        return OpenAIProvider(name, pconf)
    if name == "vertex":
        raise NotImplementedError("Vertex is a phase-2 stub — use 'gemini' or 'anthropic'.")
    raise ValueError(f"unknown provider: {name}")
