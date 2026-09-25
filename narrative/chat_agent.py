"""
narrative/chat_agent.py — the tool-using interpretation loop behind the
session chatbot (ADR-0022).

One `run_turn` call answers one user message: it sends the conversation plus
the tool catalogue to the model, executes whatever tools the model asks for
(through narrative/chat_tools), feeds the results back, and repeats until the
model stops asking. The loop is bounded (MAX_TOOL_ROUNDS) so a confused model
cannot spin forever, and every step is reported through `emit` so the HTTP
layer can stream progress to the browser.

Grounding is enforced AFTER the answer, not just requested in the prompt:
  * every `[Sn]` the answer cites must be a token a tool actually returned
    this thread (SourceRegistry); anything else is recorded as an unresolved
    citation through narrative/citation_check — the same layer that guards
    the report narratives — and shown to the author;
  * cited tokens are resolved to full references appended to the answer's
    metadata, so the UI can show what the answer rests on.

This module is HTTP-free and takes an optional pre-built client so tests can
drive it with a fake that returns scripted tool calls.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Awaitable, Callable
from typing import Any

from narrative.chat_tools import ChatToolbox
from narrative.citation_check import find_unresolved_tokens, summarize_issues
from styling_export.llm_endpoints import build_async_anthropic_client, resolve_model_name

logger = logging.getLogger(__name__)

# Model: same default as the other narratives; overridable per deployment.
DEFAULT_CHAT_MODEL = os.environ.get("ANTHROPIC_CHAT_MODEL", "claude-sonnet-4-6")
MAX_TOOL_ROUNDS = 8
MAX_TOKENS = 2048
# How much of a tool result to echo to the UI (the model gets the full text).
PREVIEW_CHARS = 400

# Citation tokens the chat uses: [S3] or combined [S1, S4].
S_BRACKET_RE = re.compile(r"\[S\d+(?:\s*,\s*S\d+)*\]")
S_TOKEN_RE = re.compile(r"S\d+")

SYSTEM_PROMPT = """\
You are a toxicologist's analysis assistant for ONE NTP 5-day genomic dose-response \
study in Sprague-Dawley rats, on the test article {chemical}. You help interpret \
the study's data and the report generated from it.

You have tools. Use them; do not answer from memory:
- Every number you state (BMD, BMDL, LOEL, NOEL, fold change, gene/gene-set rank, \
dose, n) MUST come from a run_sql result or a report section you read this turn. \
Call list_tables before your first SQL.
- Every literature or mechanism claim MUST be supported by a knowledge-graph tool \
result, cited inline with the paper's [Sn] token exactly as returned (e.g. "... \
consistent with PPAR-alpha activation [S2]"). Cite ONLY tokens returned by tools \
in this conversation. Never invent a citation, a paper, or a token.
- When the data do not support a conclusion, say so plainly and say what would.
- Be concise and quantitative. Use the report's terminology (apical endpoint, BMD, \
BMDL, responsive, gene set). Distinguish adaptive from adverse responses when you \
interpret genomics.
- You are an EXPLORATORY assistant: your answers are not report text. Do not \
propose edits to the report; if asked, explain what the data show instead.
"""

EmitFn = Callable[[str, dict], Awaitable[None] | None]


async def _emit(emit: EmitFn | None, event: str, data: dict) -> None:
    if emit is None:
        return
    res = emit(event, data)
    if asyncio.iscoroutine(res):
        await res


def _block_to_dict(block: Any) -> dict:
    """Serialise an SDK content block (text / tool_use) to the plain dict shape
    the messages API accepts back — so assistant turns round-trip verbatim."""
    btype = getattr(block, "type", None)
    if btype == "text":
        return {"type": "text", "text": getattr(block, "text", "") or ""}
    if btype == "tool_use":
        return {
            "type": "tool_use",
            "id": getattr(block, "id", ""),
            "name": getattr(block, "name", ""),
            "input": getattr(block, "input", {}) or {},
        }
    return {"type": "text", "text": str(block)}


def history_to_messages(history: list[dict]) -> list[dict]:
    """Prior turns as plain user/assistant text messages. Tool traces are NOT
    replayed (they are display metadata); the answers already contain what
    the model concluded from them."""
    out = []
    for m in history:
        role = m.get("role")
        text = (m.get("content") or "").strip()
        if role in ("user", "assistant") and text:
            out.append({"role": role, "content": text})
    return out


async def run_turn(
    *,
    history: list[dict],
    user_message: str,
    toolbox: ChatToolbox,
    chemical_name: str = "the test article",
    model: str | None = None,
    client: Any = None,
    emit: EmitFn | None = None,
) -> dict:
    """Answer one user message with tool use.

    Args:
        history:       prior turns ``[{"role", "content"}, ...]``.
        user_message:  the new question.
        toolbox:       the session's ChatToolbox (executes tools, owns the
                       SourceRegistry).
        chemical_name: for the system prompt.
        model:         canonical model id (proxy remap applied here).
        client:        an AsyncAnthropic-compatible client; built via the
                       shared chokepoint (CA bundle, key) when omitted.
        emit:          ``emit(event, data)`` callback for progress streaming:
                       events are "thinking", "tool_call", "tool_result",
                       "answer".

    Returns ``{"answer", "references", "unresolved_citations", "tool_trace",
    "model_used", "rounds"}``.
    """
    chosen = model or DEFAULT_CHAT_MODEL
    client = client or build_async_anthropic_client()
    messages = history_to_messages(history) + [{"role": "user", "content": user_message}]
    system = SYSTEM_PROMPT.format(chemical=chemical_name)

    final_text: list[str] = []
    rounds = 0
    while True:
        rounds += 1
        await _emit(emit, "thinking", {"round": rounds})
        # No temperature: newer models reject the parameter and the answers
        # should be deterministic-ish anyway (data-grounded).
        response = await client.messages.create(
            model=resolve_model_name(chosen),
            system=system,
            messages=messages,
            tools=toolbox.specs(),
            max_tokens=MAX_TOKENS,
        )
        blocks = [_block_to_dict(b) for b in (response.content or [])]
        text_parts = [b["text"] for b in blocks if b["type"] == "text" and b["text"].strip()]
        tool_uses = [b for b in blocks if b["type"] == "tool_use"]

        if getattr(response, "stop_reason", None) != "tool_use" or not tool_uses:
            final_text = text_parts
            break
        if rounds > MAX_TOOL_ROUNDS:
            final_text = text_parts or [
                "I could not finish within the tool-call budget for one answer. "
                "Please narrow the question."
            ]
            break

        # Execute every requested tool, feed results back as tool_result blocks.
        messages.append({"role": "assistant", "content": blocks})
        results = []
        for tu in tool_uses:
            await _emit(emit, "tool_call", {"tool": tu["name"], "input": tu["input"]})
            out = toolbox.execute(tu["name"], tu["input"])
            await _emit(emit, "tool_result", {
                "tool": tu["name"],
                "preview": out[:PREVIEW_CHARS],
                "chars": len(out),
            })
            results.append({"type": "tool_result", "tool_use_id": tu["id"], "content": out})
        messages.append({"role": "user", "content": results})

    answer = "\n\n".join(final_text).strip()

    # Citation verification — the same discipline as the report narratives.
    valid = toolbox.registry.tokens()
    issues = find_unresolved_tokens([answer], valid, S_BRACKET_RE, S_TOKEN_RE, "chat")
    cited: list[str] = []
    for bracket in S_BRACKET_RE.findall(answer):
        for tok in S_TOKEN_RE.findall(bracket):
            if tok in valid and tok not in cited:
                cited.append(tok)
    references = []
    for tok in cited:
        src = toolbox.registry.lookup(tok) or {}
        references.append({
            "token": tok,
            "title": src.get("title", ""),
            "year": src.get("year"),
            "venue": src.get("venue", ""),
            "doi": src.get("doi", ""),
        })
    if issues:
        logger.warning("Chat answer citations: %s", summarize_issues(issues))

    result = {
        "answer": answer,
        "references": references,
        "unresolved_citations": issues,
        "tool_trace": list(toolbox.trace),
        "model_used": chosen,
        "rounds": rounds,
    }
    await _emit(emit, "answer", result)
    return result
