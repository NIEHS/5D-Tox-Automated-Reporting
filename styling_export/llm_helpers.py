"""
llm_helpers.py — Shared LLM generation utilities for Claude API calls.

Provides a synchronous JSON-generating wrapper around AnthropicEndpoint and
an async version that offloads the blocking call to a thread-pool executor.
Used wherever the app needs to call Claude and parse the result as JSON.

Also includes a markdown-fence stripper, since Claude sometimes wraps JSON
output in ```json ... ``` blocks even when instructed not to.
"""

import asyncio
import json
import logging
import re
from typing import Any

# AnthropicEndpoint wraps the Claude API — provides a simple
# `generate(prompt, system=...)` interface that returns raw text.
from narrative.interpret import AnthropicEndpoint

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Markdown fence stripping
# ---------------------------------------------------------------------------

def strip_markdown_fences(text: str) -> str:
    """
    Remove markdown code fences (```json ... ```) from LLM responses.

    Claude sometimes wraps JSON output in markdown code blocks even when
    instructed to return raw JSON.  This strips those fences so the
    response can be parsed as JSON.

    Args:
        text: Raw LLM response text, possibly wrapped in code fences.

    Returns:
        The text with leading ```json and trailing ``` removed, if present.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned


# ---------------------------------------------------------------------------
# Synchronous LLM → JSON helper
# ---------------------------------------------------------------------------

def llm_generate_json(
    name: str,
    prompt: str,
    system: str,
    *,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 8192,
    temperature: float = 0.2,
) -> Any:
    """
    Synchronous helper: call Claude → strip markdown fences → parse JSON.

    Centralizes the repeated pattern of creating an AnthropicEndpoint,
    generating text, stripping markdown code fences, and JSON-parsing the
    result.  Can be called directly in sync code (e.g. inside a thread-pool
    worker) or wrapped in run_in_executor for async endpoints.

    Args:
        name:        Logical name for the endpoint (appears in logs / billing).
        prompt:      The user-turn prompt to send.
        system:      The system prompt.
        model:       Claude model ID (default: claude-sonnet-4-6).
        max_tokens:  Max tokens for the response.
        temperature: Sampling temperature.

    Returns:
        Parsed JSON (dict or list) from the LLM response.

    A reply that isn't valid JSON gets ONE retry: the same request with the
    parse error appended.  The request must differ — the LiteLLM proxy caches
    responses, so an identical retry returns the same malformed text (NIEHS-13's
    heart genomics narrative failed this way on every re-run).

    Raises:
        ValueError:  If the LLM returns an empty response.
        json.JSONDecodeError: If the retry isn't valid JSON either.
    """
    endpoint = AnthropicEndpoint(
        name=name,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    response = endpoint.generate(prompt, system=system)
    if not response:
        raise ValueError(f"LLM '{name}' returned empty response")
    try:
        return json.loads(strip_markdown_fences(response))
    except json.JSONDecodeError as e:
        logger.warning("LLM '%s' returned invalid JSON (%s) — retrying once", name, e)
        retry = (f"{prompt}\n\nYour previous reply was not valid JSON ({e}). Reply again "
                 "with ONLY the JSON object — escape every double quote inside strings.")
        response = endpoint.generate(retry, system=system)
        if not response:
            raise ValueError(f"LLM '{name}' returned empty response") from e
        return json.loads(strip_markdown_fences(response))


# ---------------------------------------------------------------------------
# Async wrapper
# ---------------------------------------------------------------------------

async def llm_generate_json_async(
    name: str,
    prompt: str,
    system: str,
    **kwargs,
) -> Any:
    """
    Async wrapper around llm_generate_json — runs the blocking LLM call
    in a thread-pool executor so it doesn't block the event loop.

    Accepts the same keyword arguments as llm_generate_json (model,
    max_tokens, temperature).

    Returns:
        Parsed JSON (dict or list) from the LLM response.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: llm_generate_json(name, prompt, system, **kwargs),
    )
