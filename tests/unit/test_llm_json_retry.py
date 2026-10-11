"""llm_generate_json retries once, with a changed request, on invalid JSON.

The LiteLLM proxy caches responses, so re-sending the identical request
returns the same malformed text — NIEHS-13's heart genomics narrative failed
on every re-run.  The retry appends the parse error, so the request differs.
"""

import json

import pytest

import styling_export.llm_helpers as lh


class _Endpoint:
    def __init__(self, replies):
        self.replies, self.prompts = list(replies), []

    def __call__(self, **kwargs):
        return self

    def generate(self, prompt, system=None, no_cache=False):
        self.prompts.append(prompt)
        return self.replies.pop(0)


def test_invalid_json_is_retried_with_a_different_request(monkeypatch):
    ep = _Endpoint(['{"a": "say "hi""}', '{"a": "say \\"hi\\""}'])
    monkeypatch.setattr(lh, "AnthropicEndpoint", ep)
    assert lh.llm_generate_json("t", "PROMPT", "SYS") == {"a": 'say "hi"'}
    assert len(ep.prompts) == 2 and ep.prompts[1] != ep.prompts[0]
    assert ep.prompts[1].startswith("PROMPT") and "not valid JSON" in ep.prompts[1]


def test_valid_json_is_one_call(monkeypatch):
    ep = _Endpoint(['```json\n{"a": 1}\n```'])
    monkeypatch.setattr(lh, "AnthropicEndpoint", ep)
    assert lh.llm_generate_json("t", "P", "S") == {"a": 1} and len(ep.prompts) == 1


def test_a_second_invalid_reply_raises(monkeypatch):
    monkeypatch.setattr(lh, "AnthropicEndpoint", _Endpoint(["{bad", "{still bad"]))
    with pytest.raises(json.JSONDecodeError):
        lh.llm_generate_json("t", "P", "S")
