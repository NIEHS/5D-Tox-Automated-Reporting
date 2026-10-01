"""
test_llm_egress_guard.py — study data must never reach a publicly hosted model.

Prompts carry study data (BMD values, endpoint results, gene lists), so every
LLM request must go to the walled NIEHS toxpipe gateway or a local Ollama
daemon.  These tests pin that the guard in styling_export/llm_endpoints fails
CLOSED — in particular when ANTHROPIC_BASE_URL is unset, where the Anthropic SDK
would otherwise silently fall back to the public api.anthropic.com — and that no
first-party module constructs an LLM client around the guarded builders.

No network: the anthropic module is stubbed and the scan is static (AST).
"""

import ast
import sys
import types
from pathlib import Path

import pytest

import styling_export.llm_endpoints as le

TOXPIPE = "https://litellm.toxpipe.niehs.nih.gov"
REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def fake_anthropic(monkeypatch):
    """Stub `anthropic` so the builders run without network/key; capture kwargs."""
    calls = {}

    class _Client:
        def __init__(self, **kwargs):
            calls["sync"] = kwargs

    class _AsyncClient:
        def __init__(self, **kwargs):
            calls["async"] = kwargs

    mod = types.ModuleType("anthropic")
    mod.Anthropic = _Client
    mod.AsyncAnthropic = _AsyncClient
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    monkeypatch.setattr(le, "resolve_anthropic_api_key", lambda: "sk-test")
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    return calls


# ---------------------------------------------------------------------------
# approved_base_url
# ---------------------------------------------------------------------------

def test_approved_gateway_passes(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", TOXPIPE)
    assert le.approved_base_url() == TOXPIPE


@pytest.mark.parametrize("value", [None, "", "   "])
def test_unset_base_url_is_blocked(monkeypatch, value):
    """Unset/empty == the SDK's public-API fallback — the case that leaked."""
    if value is None:
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    else:
        monkeypatch.setenv("ANTHROPIC_BASE_URL", value)
    with pytest.raises(le.LLMEgressBlocked, match="api.anthropic.com"):
        le.approved_base_url()


@pytest.mark.parametrize("url", [
    "https://api.anthropic.com",
    "https://api.openai.com/v1",
    "http://litellm.toxpipe.niehs.nih.gov",                 # not https
    "https://litellm.toxpipe.niehs.nih.gov.attacker.example",  # lookalike suffix
    "https://localhost:4000",                               # a local proxy can forward anywhere
])
def test_unapproved_base_url_is_blocked(monkeypatch, url):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", url)
    with pytest.raises(le.LLMEgressBlocked):
        le.approved_base_url()


# ---------------------------------------------------------------------------
# Builders: guard runs first, and the checked URL is passed explicitly
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("builder,key", [
    ("build_anthropic_client", "sync"),
    ("build_async_anthropic_client", "async"),
])
def test_builder_refuses_without_gateway(monkeypatch, fake_anthropic, builder, key):
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    with pytest.raises(le.LLMEgressBlocked):
        getattr(le, builder)()
    assert key not in fake_anthropic, "client was constructed despite the block"


@pytest.mark.parametrize("builder,key", [
    ("build_anthropic_client", "sync"),
    ("build_async_anthropic_client", "async"),
])
def test_builder_pins_base_url_explicitly(monkeypatch, fake_anthropic, builder, key):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", TOXPIPE)
    getattr(le, builder)()
    assert fake_anthropic[key]["base_url"] == TOXPIPE


def test_generate_is_blocked_end_to_end(monkeypatch, fake_anthropic):
    """AnthropicEndpoint.generate (behind llm_helpers and every narrative call)
    raises before any client exists when the gateway isn't configured."""
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    ep = le.AnthropicEndpoint(name="t", model="claude-sonnet-4-6", max_tokens=16)
    with pytest.raises(le.LLMEgressBlocked):
        ep.generate("study data would be here")
    assert "sync" not in fake_anthropic


# ---------------------------------------------------------------------------
# Ollama: loopback only, no cloud models
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url", ["http://localhost:11434", "http://127.0.0.1:11435"])
def test_local_ollama_passes(url):
    le.assert_local_ollama(url, "qwen2.5:14b")


def test_remote_ollama_is_blocked():
    with pytest.raises(le.LLMEgressBlocked, match="loopback"):
        le.assert_local_ollama("http://ollama.example.com:11434", "qwen2.5:14b")


@pytest.mark.parametrize("model", ["gpt-oss:120b-cloud", "deepseek-v3.1:cloud"])
def test_ollama_cloud_model_is_blocked(model):
    with pytest.raises(le.LLMEgressBlocked, match="cloud"):
        le.assert_local_ollama("http://localhost:11434", model)


def test_ollama_endpoint_generate_is_guarded():
    from knowledge_base.extract import OllamaEndpoint
    ep = OllamaEndpoint(name="x", url="http://ollama.example.com", model="qwen2.5:14b")
    with pytest.raises(le.LLMEgressBlocked):
        ep.generate("study data would be here")


# ---------------------------------------------------------------------------
# Structural: nobody builds an LLM client around the guard
# ---------------------------------------------------------------------------

_CLIENT_CTORS = {"Anthropic", "AsyncAnthropic", "OpenAI", "AsyncOpenAI",
                 "AnthropicBedrock", "AnthropicVertex", "AzureOpenAI", "AsyncAzureOpenAI"}
_ALLOWED = {Path("styling_export/llm_endpoints.py")}
_SKIP_DIRS = {"tests", "node_modules", "__pycache__"}


def _first_party_py_files():
    for path in REPO_ROOT.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT)
        if any(part.startswith(".") or part in _SKIP_DIRS for part in rel.parts[:-1]):
            continue
        yield rel


def test_no_llm_client_constructed_outside_llm_endpoints():
    offenders = []
    for rel in _first_party_py_files():
        if rel in _ALLOWED:
            continue
        try:
            tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
            if name in _CLIENT_CTORS:
                offenders.append(f"{rel}:{node.lineno} {name}(...)")
    assert not offenders, (
        "LLM clients must be built via styling_export.llm_endpoints "
        "(build_anthropic_client / build_async_anthropic_client) so the egress "
        "guard applies:\n  " + "\n  ".join(offenders)
    )
