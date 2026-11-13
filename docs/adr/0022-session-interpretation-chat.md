# 0022 — Session interpretation chat: a tool-using, knowledge-graph-grounded assistant

**Status:** Accepted 2026-09-21 (scoping decisions by the sole developer; implemented
in the same change).

## Context

The report's genomics narrative is credible because it is *graph-augmented*: the
generator queries the toxicogenomics knowledge base (`bmdx.duckdb`) for real
papers and pathways, hands them to the model as a numbered catalogue, and the
model may only cite from it. That pattern (the "RLM") has so far been a one-shot
producer of fixed report sections. A toxicologist reviewing a study wants to *ask*
about it — "which endpoints drive the apical BMD ordering?", "is the liver gene-set
response adaptive?" — and get answers grounded the same way, without leaving the
app or re-running generation.

Three scoping decisions were made up front:

1. **It lives inside rlm-bmdx, per session.** A `Chat` step in the wizard UI plus
   `/api/chat/{dtxsid}/...` routes. It reuses the session's query substrate
   (ADR-0016), the report-data loader, the knowledge-base querier and the LLM
   chokepoint rather than duplicating any of them.
2. **Grounding is by tool use, not context stuffing.** The model receives a small
   tool catalogue and decides, per question, what to query. That lets it drill
   into any table or gene without a pre-selected bundle, and it makes every
   answer's provenance explicit (the tool trace).
3. **Exploratory only.** Transcripts are persisted per session for reference but
   are never report content. This is consistent with ADR-0018: the app generates,
   previews and approves; it is not an editor. A "send to narrative" action can be
   added later on top of the existing generate/review/approve flow.

## Decision

Add four small pieces, each in the package that owns its concern:

| piece | package | responsibility |
|---|---|---|
| `chat_tools.py` | `narrative/` | the tools: read-only SQL over `session.duckdb`; read the generated report sections; knowledge-graph gene evidence / papers-for-genes / pathway genes. A `SourceRegistry` issues a stable `[Sn]` token for every paper a tool returns. |
| `chat_agent.py` | `narrative/` | the bounded tool-use loop (Anthropic messages API through `styling_export.llm_endpoints`), progress emission, and **post-answer citation verification** through `narrative/citation_check` — the same layer that guards the report narratives. |
| `chat_store.py` | `pipeline/` | transcripts at `sessions/<DTXSID>/chat/<thread>.json`, atomic writes, thread-id validation. |
| `chat_routes.py` | `web_routes/` | thin HTTP transport; the message route streams SSE progress then `complete`. |

**Grounding is enforced, not requested.** The system prompt tells the model to use
tools and to cite only `[Sn]` tokens, but the guarantees come from code: SQL runs
read-only and single-statement through `query.session_query`; tokens exist only for
papers a tool actually returned in the thread; after the answer, every `[Sn]` is
checked against the registry and anything else is returned as an *unresolved
citation* and shown to the author as a warning. Numbers are traceable through the
tool trace.

**Safety envelope.** Session ids pass `validate_dtxsid`; thread ids match
`^[A-Za-z0-9_-]{1,64}$`; messages are capped at 4000 characters; a turn may make at
most eight tool rounds; tool output is capped at 200 rows / 12 000 characters.

## Consequences

- The chat is the first *interactive* consumer of the graph-augmented pattern. The
  citation-verification helper it shares with the narratives is now the single
  definition of "grounded" in the codebase.
- No new render surface, no new section type, no change to the document tree or to
  section readiness — the feature is orthogonal to report generation.
- The known gap in `query.session_query` (no effective statement timeout on this
  DuckDB version) is inherited; the row cap bounds output but not runtime.
- Live tool use through the NIEHS LiteLLM proxy has not been exercised at the time
  of writing (tests drive the loop with a scripted fake client). If the proxy strips
  `tools`, the loop degrades to a plain answer with no citations and the UI shows no
  tool calls — visible, not silent.

## Deferred

- "Send to narrative": promote an answer into a section draft under the ADR-0015
  label/guard rules.
- Streaming the answer text token-by-token (today: progress events, then the whole
  answer).
- A per-session lock so two concurrent questions cannot interleave writes to one
  thread file.
