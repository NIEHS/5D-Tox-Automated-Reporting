"""
LLM endpoint adapters and credential/model-name resolution.

Holds the Anthropic (Claude) endpoint, the egress guard that keeps study data
off publicly hosted models (approved_base_url / assert_local_ollama), and the
single-chokepoint resolvers for the API key and the proxy model-name remap.  Extracted from interpret.py so
the endpoint/auth concern is independently testable and importable without
pulling in the DB, analysis, or narrative layers.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Egress guard — study data may only reach models inside the NIEHS wall
# ---------------------------------------------------------------------------

# Hosts an LLM request may be sent to.  Prompts carry study data (BMD values,
# endpoint results, gene lists), so the ONLY approved destination is the walled
# NIEHS toxpipe LiteLLM gateway.  Deliberately a code constant, not an env var:
# widening it must be a reviewed commit, never a shell setting.  There is no
# opt-out — off the NIEHS network, LLM features simply don't run.
APPROVED_LLM_HOSTS = frozenset({"litellm.toxpipe.niehs.nih.gov"})

# Loopback names a local Ollama daemon may be reached on (incl. SSH tunnels).
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

# Ollama "cloud" models (tags like ``gpt-oss:120b-cloud``) are proxied by the
# local daemon to ollama.com — a publicly hosted model behind a localhost URL.
_OLLAMA_CLOUD_TAG = re.compile(r"[:-]cloud$")


class LLMEgressBlocked(RuntimeError):
    """Raised instead of sending a prompt to an unapproved (public) endpoint."""


def approved_base_url() -> str:
    """Return ANTHROPIC_BASE_URL after checking it names an approved host.

    Fails CLOSED.  Unset/empty is the dangerous case: the Anthropic SDK then
    silently falls back to the public api.anthropic.com (this happened on an
    off-network run, 2026-09-21).  Every client builder calls this and passes
    the result as ``base_url`` explicitly, so the checked value and the one the
    SDK uses can't diverge.
    """
    base = (os.environ.get("ANTHROPIC_BASE_URL") or "").strip()
    if not base:
        raise LLMEgressBlocked(
            "ANTHROPIC_BASE_URL is not set, so the Anthropic SDK would send this "
            "prompt to the public api.anthropic.com. Study data may only go to the "
            f"walled NIEHS gateway ({', '.join(sorted(APPROVED_LLM_HOSTS))}); set "
            "ANTHROPIC_BASE_URL to it (requires the NIEHS network/VPN)."
        )
    parsed = urlparse(base)
    if parsed.scheme != "https" or parsed.hostname not in APPROVED_LLM_HOSTS:
        raise LLMEgressBlocked(
            f"ANTHROPIC_BASE_URL={base!r} is not an approved LLM endpoint. Study "
            f"data may only go to: {', '.join(sorted(APPROVED_LLM_HOSTS))} (https)."
        )
    return base


def assert_local_ollama(url: str, model: str) -> None:
    """Refuse an Ollama call unless it stays on this machine.

    Ollama endpoints are local daemons (or SSH tunnels to them), so the URL must
    be loopback — and the model must not be an Ollama cloud model, which the
    local daemon forwards to ollama.com.
    """
    host = urlparse(url).hostname
    if host not in _LOOPBACK_HOSTS:
        raise LLMEgressBlocked(
            f"Ollama endpoint {url!r} is not a local (loopback) address."
        )
    if _OLLAMA_CLOUD_TAG.search(model or ""):
        raise LLMEgressBlocked(
            f"Ollama model {model!r} is a cloud model (runs on ollama.com)."
        )


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


def resolve_ca_bundle() -> "str | None":
    """Resolve the CA bundle path for verifying the LiteLLM proxy's TLS cert.

    The NIEHS proxy presents a cert signed by an NIH-internal CA absent from the
    public certifi trust store, so an explicit bundle is required.  Returns
    ``SSL_CERT_FILE`` if set, else ``REQUESTS_CA_BUNDLE``, else None.

    The single chokepoint for CA resolution — mirrors the precedence the
    /api/models route uses (llm_routes.py) so the two can't drift.  NOTE both
    must be checked: the Anthropic SDK's httpx client honors ``SSL_CERT_FILE``
    but NOT ``REQUESTS_CA_BUNDLE`` (only ``requests`` reads the latter), so an
    env that sets only ``REQUESTS_CA_BUNDLE`` would break SDK calls if we relied
    on ambient env instead of passing the bundle explicitly.
    """
    return os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")


def _ssl_context_for_bundle(bundle: str):
    """Build an SSL context trusting the given CA bundle.

    Passed to httpx as ``verify=<context>`` — the supported form in httpx 0.28+
    (``verify=<str path>`` is deprecated).  Isolated so both builders share it.
    """
    import ssl
    return ssl.create_default_context(cafile=bundle)


def build_anthropic_client(timeout: "float | None" = None):
    """Construct a sync anthropic.Anthropic with explicit key + CA verification.

    The base URL is passed explicitly from approved_base_url(), which raises
    LLMEgressBlocked rather than let the SDK fall back to the public API.
    When a CA bundle resolves, an httpx.Client verifying against it is passed as
    the SDK's http_client so TLS to the proxy verifies against the NIH CA (the
    SDK's default certifi store lacks it → APIConnectionError "Connection
    error.").  When none resolves, the default client is used.
    """
    import anthropic
    kwargs = {"api_key": resolve_anthropic_api_key(), "base_url": approved_base_url()}
    if timeout is not None:
        kwargs["timeout"] = timeout
    bundle = resolve_ca_bundle()
    if bundle:
        import httpx
        kwargs["http_client"] = httpx.Client(verify=_ssl_context_for_bundle(bundle))
    return anthropic.Anthropic(**kwargs)


def build_async_anthropic_client():
    """Async counterpart of build_anthropic_client (AsyncAnthropic + AsyncClient)."""
    import anthropic
    kwargs = {"api_key": resolve_anthropic_api_key(), "base_url": approved_base_url()}
    bundle = resolve_ca_bundle()
    if bundle:
        import httpx
        kwargs["http_client"] = httpx.AsyncClient(verify=_ssl_context_for_bundle(bundle))
    return anthropic.AsyncAnthropic(**kwargs)


def using_proxy() -> bool:
    """True when the SDK is pointed at a gateway (ANTHROPIC_BASE_URL set and
    non-empty) rather than api.anthropic.com. The NIEHS LiteLLM proxy is the
    only such gateway we know; its model-name convention differs from
    Anthropic's, which is what `resolve_model_name` compensates for."""
    return bool((os.environ.get("ANTHROPIC_BASE_URL") or "").strip())


def resolve_model_name(model: str) -> str:
    """Map a canonical model id to the name the configured endpoint expects.

    The NIEHS LiteLLM proxy uses dot version notation (``claude-sonnet-4.6``)
    while the app passes hyphenated canonical ids (``claude-sonnet-4-6``);
    sending the hyphenated form gets a 400 "Invalid model name" from the proxy.
    Anthropic's own API is the opposite: it accepts ONLY the hyphenated id and
    answers the dotted one with 404 "model: claude-sonnet-4.6 was not found"
    (seen 2026-09-21 running off-network against api.anthropic.com). So the
    automatic remap applies only when a proxy base URL is configured
    (`using_proxy`). An explicit ANTHROPIC_MODEL_MAP env (``src=dst,src2=dst2``)
    is honoured in either mode — it is a deliberate operator override.

    This is the single chokepoint for the remap — every Anthropic call site must
    route its model through here (directly or via AnthropicEndpoint) so the
    endpoint never sees an id in the wrong convention.
    """
    import re
    map_str = os.environ.get("ANTHROPIC_MODEL_MAP", "")
    if map_str:
        for entry in map_str.split(","):
            if "=" in entry:
                src, dst = entry.strip().split("=", 1)
                if model == src.strip():
                    return dst.strip()
    if not using_proxy():
        return model
    # Proxy auto-remap: claude-{tier}-{major}-{minor} → claude-{tier}-{major}.{minor}
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
                 temperature: float | None = None, no_cache: bool = False) -> str:
        """`no_cache` asks the LiteLLM proxy for a fresh completion: it caches
        responses, so an identical request otherwise returns the same text —
        which defeats running one prompt several times to see how it varies."""
        temp = temperature if temperature is not None else self.temperature
        client = build_anthropic_client()
        messages = [{"role": "user", "content": prompt}]
        kwargs = {
            "model": self._resolve_model(),
            "max_tokens": self.max_tokens,
            "messages": messages,
            "temperature": temp,
        }
        if system:
            kwargs["system"] = system
        if no_cache and using_proxy():
            kwargs["extra_body"] = {"cache": {"no-cache": True}}
        try:
            response = client.messages.create(**kwargs)
        except Exception as e:
            # Newer models (e.g. opus-4.8) reject the temperature param outright
            # ("`temperature` is deprecated for this model.").  Rather than carry
            # a per-model allow/deny list that rots as models change, react to
            # what the proxy tells us: drop temperature and retry once.
            if "temperature" not in str(e).lower():
                raise
            kwargs.pop("temperature", None)
            response = client.messages.create(**kwargs)
        return response.content[0].text if response.content else ""

    def is_available(self) -> bool:
        return bool(resolve_anthropic_api_key())
