"""
knowledge_base/query_agent.py — an assistant that proposes edits to a crawl
query's text.

A person asks in plain words ("add seeds on PFAS hepatotoxicity", "narrow the
heart crawl to cardiomyopathy", "what does the floor do?"); the agent answers
with a revised text, a short explanation and the diff against the text it was
given.  It saves nothing and runs nothing: the person reads the proposal and
saves it (knowledge_base.crawl_queries.save) or not.

The agent knows only the query's format (crawl_queries.FORMAT_DOC) and the
text it is given — nothing of a session, its data or the knowledge bases.  A
query is sent to Semantic Scholar when it runs, so the prompt tells the agent
never to add a study's results to it.  The call goes through the approved
gateway (styling_export.llm_endpoints): a query names no study data, but the
person's request might.

A proposal that does not parse as a query (crawl_queries.parse) is sent back
once with the problem; if the second one fails too it is returned with
``valid: false`` and the problem, for the person to see — never saved.

``endpoint`` is injectable (anything with ``generate(prompt, system=...)``)
so tests drive the agent with a stub.
"""

from __future__ import annotations

import os
import re

from knowledge_base import crawl_queries

DEFAULT_MODEL = os.environ.get("ANTHROPIC_QUERY_AGENT_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = 16000

SYSTEM = """You help a person edit a crawl query: a YAML document that tells a \
literature crawler what to search (seed papers, searches), how to judge a paper, \
what to extract from each paper, what to count, what to crawl next and what to \
annotate. The query is the person's; you propose, they decide.

The format:

{format}

Rules:
- Change only what the request asks for. Keep every other line, comment and \
key order exactly as given.
- Keep the YAML valid and in the format above. Keep `format: 1`.
- Do not invent DOIs. Add a seed only when the person gives its DOI; otherwise \
add a search (`searches: [{{query, limit}}]`) that finds such papers.
- Never put a study's own results (its responsive genes, its doses, its \
findings) into the query: the query's searches are sent to a public service.
- If the request is a question, answer it in the explanation and return the \
text unchanged.

Reply in exactly this form, nothing before or after:

<explanation>
What you changed and why, in a few plain sentences.
</explanation>
<query>
the whole revised query text
</query>"""

_EXPLANATION = re.compile(r"<explanation>\s*(.*?)\s*</explanation>", re.S)
_QUERY = re.compile(r"<query>\n?(.*?)</query>", re.S)


def _endpoint():
    from styling_export.llm_endpoints import AnthropicEndpoint
    return AnthropicEndpoint(name="crawl-query-agent", model=DEFAULT_MODEL,
                             max_tokens=MAX_TOKENS, temperature=0.2)


def _prompt(text: str, request: str, earlier: list[dict]) -> str:
    parts = []
    if earlier:
        parts.append("Earlier in this conversation:")
        for turn in earlier:
            parts.append(f"- The person asked: {turn.get('request', '')}\n"
                         f"  You answered: {turn.get('explanation', '')}")
        parts.append("")
    parts += ["The current query text:", "<current>", text, "</current>", "",
              f"The person asks: {request}"]
    return "\n".join(parts)


def _read_reply(reply: str) -> tuple[str, str | None]:
    explanation = _EXPLANATION.search(reply or "")
    query = _QUERY.search(reply or "")
    return (explanation.group(1).strip() if explanation else "",
            query.group(1) if query else None)


def _problem(text: str | None) -> str | None:
    if text is None:
        return "the reply held no <query> block"
    try:
        crawl_queries.parse(text)
    except crawl_queries.QueryError as e:
        return str(e)
    return None


def propose(text: str, request: str, *, earlier: list[dict] | None = None,
            endpoint=None) -> dict:
    """A proposed revision of ``text`` for ``request``.  Returns
    ``{text, explanation, diff, changed, valid, problem}``; saves nothing."""
    if not (request or "").strip():
        raise ValueError("say what to change")
    endpoint = endpoint or _endpoint()
    system = SYSTEM.format(format=crawl_queries.FORMAT_DOC)
    prompt = _prompt(text, request.strip(), earlier or [])
    explanation, revised = _read_reply(endpoint.generate(prompt, system=system))
    problem = _problem(revised)
    if problem:
        # A different request (the proxy caches identical ones), with the problem.
        retry = (f"{prompt}\n\nYour previous reply could not be used: {problem}. Reply "
                 "again in the stated form, with the whole query text valid.")
        explanation, revised = _read_reply(endpoint.generate(retry, system=system))
        problem = _problem(revised)
    revised = revised if revised is not None else text
    if not revised.endswith("\n"):
        revised += "\n"
    return {"text": revised, "explanation": explanation,
            "diff": crawl_queries.diff(text, revised), "changed": revised != text,
            "valid": problem is None, "problem": problem}
