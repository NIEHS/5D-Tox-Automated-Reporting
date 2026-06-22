"""
LLM endpoint adapters and credential/model-name resolution.

Holds the Anthropic (Claude) endpoint plus the two single-chokepoint resolvers
for the API key and the proxy model-name remap.  Extracted from interpret.py so
the endpoint/auth concern is independently testable and importable without
pulling in the DB, analysis, or narrative layers.
"""

import os
from dataclasses import dataclass
from pathlib import Path


def resolve_anthropic_api_key() -> "str | None":
    """
    Resolve the Anthropic API key: the ANTHROPIC_API_KEY env var if set, else
    the contents of ~/.anthropic/api_key, else None.

    Env wins (so a Cloud Run / deployment-injected key still takes precedence);
    the file is a convenience fallback for local use.  The single chokepoint
    every Anthropic client construction passes its api_key through, so the key
    source can't drift between call sites.  Returns None when neither is present
    (the SDK then raises its own clear "no api key" error).
    """
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    path = Path.home() / ".anthropic" / "api_key"
    if path.exists():
        return path.read_text().strip() or None
    return None


def resolve_model_name(model: str) -> str:
    """Map a canonical model id to the proxy's expected name.

    The LiteLLM proxy uses dot version notation (``claude-sonnet-4.6``) while
    the app passes hyphenated canonical ids (``claude-sonnet-4-6``); sending the
    hyphenated form gets a 400 "Invalid model name" from the proxy.  An explicit
    ANTHROPIC_MODEL_MAP env (``src=dst,src2=dst2``) overrides the auto-remap.

    This is the single chokepoint for the remap — every Anthropic call site must
    route its model through here (directly or via AnthropicEndpoint) so the
    proxy never sees an un-remapped id.
    """
    import re
    map_str = os.environ.get("ANTHROPIC_MODEL_MAP", "")
    if map_str:
        for entry in map_str.split(","):
            if "=" in entry:
                src, dst = entry.strip().split("=", 1)
                if model == src.strip():
                    return dst.strip()
    # Auto-remap: claude-{tier}-{major}-{minor} → claude-{tier}-{major}.{minor}
    m = re.match(r"^(claude-\w+)-(\d+)-(\d+)$", model)
    if m:
        return f"{m.group(1)}-{m.group(2)}.{m.group(3)}"
    return model


@dataclass
class AnthropicEndpoint:
    name: str
    model: str          # e.g. "claude-sonnet-4-6"
    max_tokens: int = 4096
    temperature: float = 0.3

    def _resolve_model(self) -> str:
        """Map canonical model IDs to proxy-friendly names via ANTHROPIC_MODEL_MAP env."""
        return resolve_model_name(self.model)

    def generate(self, prompt: str, system: str = "",
                 temperature: float | None = None) -> str:
        import anthropic
        temp = temperature if temperature is not None else self.temperature
        client = anthropic.Anthropic(api_key=resolve_anthropic_api_key())
        messages = [{"role": "user", "content": prompt}]
        kwargs = {
            "model": self._resolve_model(),
            "max_tokens": self.max_tokens,
            "messages": messages,
            "temperature": temp,
        }
        if system:
            kwargs["system"] = system
        response = client.messages.create(**kwargs)
        return response.content[0].text if response.content else ""

    def is_available(self) -> bool:
        return bool(resolve_anthropic_api_key())
