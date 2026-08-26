"""
test_llm_endpoints.py — CA-bundle resolution + explicit-http-client wiring.

Regression net for "Summary generation failed: Connection error.": the NIEHS
LiteLLM proxy's TLS cert is signed by an NIH-internal CA absent from certifi, so
the Anthropic SDK must be handed an http_client that verifies against the
configured bundle.  The SDK's httpx client honors SSL_CERT_FILE but NOT
REQUESTS_CA_BUNDLE, so relying on ambient env is fragile — these tests pin that
the builders pass the bundle EXPLICITLY.

No network: we patch the anthropic client constructors and inspect the kwargs.
"""

import sys
import types

import pytest

import styling_export.llm_endpoints as le


# httpx clients read proxy env vars by default (trust_env=True).  The builder
# tests construct a REAL httpx client to exercise the SSL-context path, so any
# ambient *_PROXY var (e.g. a sandbox-injected SOCKS proxy without socksio)
# would break construction for reasons unrelated to what we're asserting.  Clear
# them so these tests pin the CA-verification wiring hermetically.
@pytest.fixture(autouse=True)
def _no_proxy_env(monkeypatch):
    for var in (
        "ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy",
        "HTTPS_PROXY", "https_proxy", "FTP_PROXY", "ftp_proxy",
    ):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# resolve_ca_bundle precedence
# ---------------------------------------------------------------------------

def test_resolve_ca_bundle_prefers_ssl_cert_file(monkeypatch):
    monkeypatch.setenv("SSL_CERT_FILE", "/ssl.pem")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/req.pem")
    assert le.resolve_ca_bundle() == "/ssl.pem"


def test_resolve_ca_bundle_falls_back_to_requests_bundle(monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/req.pem")
    assert le.resolve_ca_bundle() == "/req.pem"


def test_resolve_ca_bundle_none_when_unset(monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    assert le.resolve_ca_bundle() is None


# ---------------------------------------------------------------------------
# Builders pass an explicit verifying http_client when a bundle is present
# ---------------------------------------------------------------------------

@pytest.fixture
def real_ca_path():
    """A real cafile so ssl.create_default_context(cafile=...) loads cleanly.

    The builder validates the bundle by constructing an SSL context, so the test
    bundle must exist; certifi's bundle is always present in the venv.
    """
    import certifi
    return certifi.where()


@pytest.fixture
def fake_anthropic(monkeypatch):
    """Stub the `anthropic` module so builders construct without network/key.

    httpx stays REAL — we want to exercise the actual http_client construction
    (incl. the SSL context), only the SDK client is faked to capture kwargs.
    """
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
    return calls


def test_sync_builder_attaches_http_client_with_bundle(monkeypatch, fake_anthropic, real_ca_path):
    monkeypatch.setenv("SSL_CERT_FILE", real_ca_path)
    le.build_anthropic_client()
    kwargs = fake_anthropic["sync"]
    assert kwargs["api_key"] == "sk-test"
    assert "http_client" in kwargs, "no explicit CA-verified client passed"


def test_sync_builder_no_http_client_without_bundle(monkeypatch, fake_anthropic):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    le.build_anthropic_client()
    assert "http_client" not in fake_anthropic["sync"]


def test_async_builder_attaches_http_client_with_bundle(monkeypatch, fake_anthropic, real_ca_path):
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", real_ca_path)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    le.build_async_anthropic_client()
    assert "http_client" in fake_anthropic["async"]


def test_generate_routes_through_builder(monkeypatch):
    """AnthropicEndpoint.generate must use build_anthropic_client (the seam that
    carries the CA fix), not construct a bare client."""
    captured = {}

    class _FakeMessages:
        def create(self, **kwargs):
            captured["model"] = kwargs["model"]
            return types.SimpleNamespace(
                content=[types.SimpleNamespace(text="OK")]
            )

    class _FakeClient:
        messages = _FakeMessages()

    monkeypatch.setattr(le, "build_anthropic_client", lambda: _FakeClient())
    ep = le.AnthropicEndpoint(name="t", model="claude-sonnet-4-6", max_tokens=16)
    out = ep.generate("hi", system="be terse")
    assert out == "OK"
    # Model id was remapped to the proxy's dot notation on the way through.
    assert captured["model"] == "claude-sonnet-4.6"


def test_generate_retries_without_temperature_when_rejected(monkeypatch):
    """Models like opus-4.8 reject the temperature param with a 400 saying it is
    deprecated.  generate() must drop temperature and retry once, not surface the
    error."""
    calls = []

    class _Messages:
        def create(self, **kwargs):
            calls.append(kwargs)
            if "temperature" in kwargs:
                raise RuntimeError(
                    "Error code: 400 - `temperature` is deprecated for this model."
                )
            return types.SimpleNamespace(
                content=[types.SimpleNamespace(text="OK")]
            )

    class _Client:
        messages = _Messages()

    monkeypatch.setattr(le, "build_anthropic_client", lambda: _Client())
    ep = le.AnthropicEndpoint(name="t", model="claude-opus-4-8", max_tokens=16)
    out = ep.generate("hi")
    assert out == "OK"
    assert len(calls) == 2, "expected one failed call then a retry"
    assert "temperature" in calls[0] and "temperature" not in calls[1]


def test_generate_does_not_swallow_unrelated_errors(monkeypatch):
    """A 400 that is NOT about temperature must propagate, not trigger a retry."""
    class _Messages:
        def create(self, **kwargs):
            raise RuntimeError("Error code: 400 - invalid model name")

    class _Client:
        messages = _Messages()

    monkeypatch.setattr(le, "build_anthropic_client", lambda: _Client())
    ep = le.AnthropicEndpoint(name="t", model="claude-sonnet-4-6", max_tokens=16)
    with pytest.raises(RuntimeError, match="invalid model name"):
        ep.generate("hi")
