"""
Graph-grounded literature references for the generated report.

The genomics interpretation already queries the knowledge graph (bmdx.duckdb)
for real, DOI-anchored papers and names them to the LLM as context, but those
citations evaporated — they never became a structured reference list.  This
module closes that loop end-to-end:

  1. `build_reference_pool_for_genes` turns a responsive-gene set into a
     DETERMINISTIC candidate paper pool (same genes -> same pool), each entry
     resolved to full bibliographic metadata (title / year / venue / doi) and
     tagged with a stable per-stratum `[Pn]` token.
  2. The genomics-narrative LLM is handed that pool as a numbered catalogue and
     asked to cite papers inline as `[Pn]` tokens (see llm_routes).
  3. `assemble_report_references` merges the cited papers from EVERY genomics
     stratum (organ x sex) into ONE report-wide, globally-numbered list, and
     rewrites the per-stratum `[Pn]` tokens to the final report-wide `[n]`
     numbers so the inline citations and the References section agree.

Design notes
------------
* The candidate POOL is a pure graph computation — no LLM, no network beyond the
  local DuckDB — so it is independently testable and deterministic.
* Per-stratum `[Pn]` tokens are LOCAL to a stratum's pool.  The report has ONE
  References section, so the same paper (by `paper_id`) must carry the SAME
  number everywhere.  `assemble_report_references` assigns each paper its global
  number the first time it is cited anywhere, scanning strata in document order
  (organ, then sex) and, within a stratum, in citation order — a deterministic
  projection of the persisted per-stratum pools.
* No authors column exists in the `papers` table, so reference entries carry
  title / venue / year / doi / citation_count only.
"""

from __future__ import annotations

import logging
import re
from typing import Any

# Matches a citation bracket carrying one or more Pn tokens: "[P3]" or the
# combined form "[P1, P3]" some models emit.  The inner _TOKEN_RE then pulls the
# individual tokens so "[P1]" and "[P10]" never collide.
_BRACKET_RE = re.compile(r"\[P\d+(?:\s*,\s*P\d+)*\]")
_TOKEN_RE = re.compile(r"P\d+")
# A hand-typed bare numeric citation like "[12]" or "[3, 5]" — the shape a human
# types when they add a citation directly (as opposed to the pipeline's [Pn]
# tokens).  Used only for the detect-and-warn on human-edited narratives.
_BARE_NUM_RE = re.compile(r"\[\d+(?:\s*[,\-–]\s*\d+)*\]")

logger = logging.getLogger(__name__)

from narrative.citation_check import find_unresolved_tokens  # noqa: E402


def build_reference_pool_for_genes(
    genes: list[str],
    db_path: str = "bmdx.duckdb",
    pool_size: int = 25,
) -> list[dict]:
    """
    Build a deterministic candidate reference pool for a responsive-gene set.

    Papers are collected from `paper_genes` for every gene in the set, ranked so
    that papers tying together MORE of the responsive genes come first (breaking
    ties by citation count, then `paper_id` for a fully stable order), and the
    top `pool_size` are resolved to full metadata from the `papers` table.

    Args:
        genes:     Responsive gene symbols (case-insensitive; the graph stores
                   upper-case HGNC symbols).
        db_path:   Path to bmdx.duckdb (read-only).
        pool_size: How many candidate papers to offer.

    Returns:
        A list of dicts, each ``{token: "Pn", paper_id, title, year, venue, doi,
        citation_count, genes: [sorted symbols]}``, ordered by rank with tokens
        P1..Pn assigned in that order.  Empty when the gene set has no papers.
    """
    from knowledge_base.toxkb import ToxKBQuerier

    with ToxKBQuerier(db_path) as kb:
        return build_reference_pool(genes, kb, pool_size=pool_size)


def build_reference_pool(
    genes: list[str],
    kb: "Any",
    pool_size: int = 25,
) -> list[dict]:
    """Pool builder over an already-open ToxKBQuerier (see
    `build_reference_pool_for_genes` for the semantics)."""
    overlap: dict[str, dict] = {}
    for gene in genes:
        symbol = (gene or "").strip().upper()
        if not symbol:
            continue
        for p in kb.gene_papers(symbol):
            pid = p["paper_id"]
            entry = overlap.setdefault(
                pid,
                {
                    "paper_id": pid,
                    "title": p["title"],
                    "year": p["year"],
                    "citation_count": p["citation_count"] or 0,
                    "genes": set(),
                },
            )
            entry["genes"].add(symbol)

    # Rank: more responsive genes tied together first, then citation count, then
    # paper_id ascending as a deterministic final tiebreaker (so a fixed gene set
    # always yields the identical pool ordering).
    ranked = sorted(
        overlap.values(),
        key=lambda d: (len(d["genes"]), d["citation_count"], _neg_pid(d["paper_id"])),
        reverse=True,
    )[:pool_size]

    meta = kb.papers_metadata([d["paper_id"] for d in ranked])

    pool: list[dict] = []
    for i, d in enumerate(ranked, 1):
        m = meta.get(d["paper_id"], {})
        pool.append(
            {
                "token": f"P{i}",
                "paper_id": d["paper_id"],
                "title": m.get("title") or d["title"],
                "year": m.get("year") or d["year"],
                "venue": m.get("venue") or "",
                "doi": m.get("doi") or "",
                "citation_count": m.get("citation_count") or d["citation_count"],
                "genes": sorted(d["genes"]),
            }
        )
    return pool


def _neg_pid(paper_id: str) -> str:
    """Sort key helper: `sorted(reverse=True)` ranks citation_count DESC but we
    want paper_id ASC as the final tiebreaker.  Inverting each byte flips the
    lexicographic order so the reverse-sort yields ascending paper_ids."""
    return "".join(chr(255 - ord(c)) for c in paper_id)


def format_reference_catalogue(pool: list[dict]) -> str:
    """Render the candidate pool as the numbered `[Pn]` catalogue handed to the
    LLM (the prose is asked to cite these tokens inline)."""
    lines = ["=== CANDIDATE REFERENCES (cite these by their [Pn] token) ==="]
    for p in pool:
        genes = ", ".join(p["genes"][:6])
        lines.append(
            f"[{p['token']}] {p['title']} ({p['year']}). {p['venue']}. "
            f"cited {p['citation_count']}x. [relevant genes: {genes}]"
        )
    return "\n".join(lines)


def _iter_paragraphs(narr: Any) -> list[str]:
    """Coerce a narrative field (str | list | None) to a list of paragraph
    strings, so token extraction/rewriting is uniform across shapes."""
    if narr is None:
        return []
    if isinstance(narr, str):
        return [narr]
    return [p for p in narr if isinstance(p, str)]


def cited_tokens_in_order(*narratives: Any) -> list[str]:
    """The `Pn` tokens appearing across the given narratives, in first-appearance
    order (deduplicated).  Used to reconstruct which pool papers a stratum's
    prose actually cited."""
    seen: list[str] = []
    for narr in narratives:
        for para in _iter_paragraphs(narr):
            for bracket in _BRACKET_RE.findall(para):
                for tok in _TOKEN_RE.findall(bracket):
                    if tok not in seen:
                        seen.append(tok)
    return seen


def _rewrite_paragraph(text: str, token_to_number: dict[str, int]) -> str:
    """Replace every `[Pn]` (or combined `[P1, P2]`) bracket in `text` with the
    report-wide `[n]` numbers.  Tokens with no mapping (e.g. an invented citation
    not in the pool) are dropped, and a bracket left empty is removed."""

    def _sub(match: "re.Match") -> str:
        nums: list[int] = []
        for tok in _TOKEN_RE.findall(match.group(0)):
            n = token_to_number.get(tok)
            if n is not None and n not in nums:
                nums.append(n)
        if not nums:
            return ""
        return "[" + ", ".join(str(n) for n in nums) + "]"

    out = _BRACKET_RE.sub(_sub, text)
    # Collapse any double spaces a dropped citation may have left behind.
    return re.sub(r" {2,}", " ", out).replace(" .", ".").strip()


def assemble_report_references(strata: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Merge per-stratum citations into ONE report-wide, globally-numbered list and
    rewrite each stratum's inline `[Pn]` tokens to the final `[n]` numbers.

    Args:
        strata: Ordered list (document order — the caller sorts by organ then
                sex) of stratum dicts, each carrying:
                  - ``reference_pool``: the stratum's candidate pool (token ->
                    paper metadata), as produced by `build_reference_pool*`;
                  - ``gene_set_narrative`` / ``gene_narrative``: paragraph lists
                    (str or list[str]) that may contain `[Pn]` tokens.

    Returns:
        ``(references, rewritten)`` where:
          - ``references`` is the ordered, de-duplicated, globally-numbered list
            of cited papers: ``[{n, paper_id, title, year, venue, doi,
            citation_count, genes}, ...]``.  A paper is included ONLY if it was
            actually cited somewhere.
          - ``rewritten`` is parallel to ``strata``: each dict carries the same
            organ/sex plus ``gene_set_narrative`` / ``gene_narrative`` with
            tokens rewritten to report-wide numbers.

    Numbering is deterministic: a paper gets its number the first time it is
    cited, scanning strata in the given order and, within a stratum, gene-set
    prose then gene prose in first-appearance order.
    """
    references: list[dict] = []
    paper_to_number: dict[str, int] = {}
    rewritten: list[dict] = []

    for stratum in strata:
        pool = stratum.get("reference_pool") or []
        token_to_paper = {p["token"]: p for p in pool}
        gs = stratum.get("gene_set_narrative")
        gn = stratum.get("gene_narrative")

        # Per-stratum token -> report-wide number, assigning new numbers as
        # unseen papers are first cited (gene-set prose scanned before genes).
        token_to_number: dict[str, int] = {}
        for tok in cited_tokens_in_order(gs, gn):
            paper = token_to_paper.get(tok)
            if not paper:
                continue  # invented / out-of-pool token — dropped on rewrite
            pid = paper["paper_id"]
            if pid not in paper_to_number:
                n = len(references) + 1
                paper_to_number[pid] = n
                references.append(
                    {
                        "n": n,
                        "paper_id": pid,
                        "title": paper.get("title") or "",
                        "year": paper.get("year"),
                        "venue": paper.get("venue") or "",
                        "doi": paper.get("doi") or "",
                        "citation_count": paper.get("citation_count") or 0,
                        "genes": paper.get("genes") or [],
                    }
                )
            token_to_number[tok] = paper_to_number[pid]

        rewritten.append(
            {
                **{k: v for k, v in stratum.items()
                   if k not in ("gene_set_narrative", "gene_narrative")},
                "gene_set_narrative": [
                    _rewrite_paragraph(p, token_to_number) for p in _iter_paragraphs(gs)
                ],
                "gene_narrative": [
                    _rewrite_paragraph(p, token_to_number) for p in _iter_paragraphs(gn)
                ],
            }
        )

    return references, rewritten


def find_unresolved_citations(strata: list[dict]) -> list[dict]:
    """Every `[Pn]` token in a stratum's narratives that is NOT in that stratum's
    reference pool — i.e. a citation the model invented or mis-typed.

    `assemble_report_references` drops such tokens from the rendered prose (a
    raw [P9] must not ship). Before 2026-09-21 that drop was silent: the claim
    survived uncited and nobody was told. This reports it. Same shape as the
    human-edit hazards so one warnings list carries both:
    ``{"kind": "gene_set"|"gene", "organ", "sex", "issue": "unresolved_citation",
       "tokens": ["P9", ...], "sentences": [...]}``. Pure; empty when clean.
    """
    warnings: list[dict] = []
    for s in strata:
        valid = {p.get("token") for p in (s.get("reference_pool") or [])}
        where = f"{s.get('organ', '?')}/{s.get('sex', '?')}"
        for kind, key in (("gene_set", "gene_set_narrative"), ("gene", "gene_narrative")):
            issues = find_unresolved_tokens(
                _iter_paragraphs(s.get(key)), valid, _BRACKET_RE, _TOKEN_RE, where,
            )
            if issues:
                warnings.append({
                    "kind": kind,
                    "organ": s.get("organ", ""),
                    "sex": s.get("sex", ""),
                    "issue": "unresolved_citation",
                    "tokens": sorted({i["token"].strip("[]") for i in issues}),
                    "sentences": [i["sentence"] for i in issues],
                })
    return warnings


def detect_override_citation_hazards(
    overrides: dict,
    pools_by_organ: dict[str, set[str]],
) -> list[dict]:
    """Detect citation hazards in HUMAN-edited genomics narratives (detect-only).

    References are assembled from the interpretation cache, but a human edit lands
    in a SEPARATE store (genomics_narrative_overrides.json) that overlays at render
    and wins — so the override text is never seen by the assembly / [Pn] rewrite.
    Two silent-failure modes result, which this surfaces LOUDLY instead:

      1. an override still carries a [Pn] token that is NOT in that organ's pool
         (an out-of-pool or invented token) — the rewrite would have dropped it,
         so it renders as a raw, unresolved [Pn];
      2. an override carries a hand-typed bare numeric citation like [12] — which
         collides with (or is unrelated to) the auto-generated report numbering.

    This does NOT reconcile or fix anything (that is the deferred robust solution)
    — it only reports.  Returns a list of warning dicts:
    ``{"kind", "organ", "issue", "tokens": [...]}`` — empty when clean (so the
    caller stays byte-identical when there are no human edits).

    Args:
        overrides:       the override store, ``{"gene_set": {organ: [paras]},
                         "gene_bmd": {organ: [paras]}}``.
        pools_by_organ:  ``{organ_lower: {"P1", "P2", ...}}`` — the union of the
                         [Pn] tokens each organ's strata pools legitimately define.
    """
    warnings: list[dict] = []
    for kind in ("gene_set", "gene_bmd"):
        bucket = (overrides or {}).get(kind) or {}
        if not isinstance(bucket, dict):
            continue
        for organ, paras in bucket.items():
            if not paras:
                continue
            organ_l = str(organ).lower()
            valid = pools_by_organ.get(organ_l, set())
            text = " ".join(p for p in paras if isinstance(p, str))

            out_of_pool = sorted({
                tok
                for bracket in _BRACKET_RE.findall(text)
                for tok in _TOKEN_RE.findall(bracket)
                if tok not in valid
            })
            if out_of_pool:
                warnings.append({
                    "kind": kind, "organ": organ_l,
                    "issue": "out_of_pool_token", "tokens": out_of_pool,
                })

            hand_typed = sorted(set(_BARE_NUM_RE.findall(text)))
            if hand_typed:
                warnings.append({
                    "kind": kind, "organ": organ_l,
                    "issue": "hand_typed_citation", "tokens": hand_typed,
                })
    return warnings


def format_reference_entry(entry: dict) -> str:
    """Render one report-wide reference as a numbered citation string, e.g.
    ``"[3] Title. Venue. 2024. https://doi.org/10.x/y"``.  Missing venue/year/doi
    are simply omitted (no authors are available in the graph)."""
    parts = [f"[{entry['n']}]", (entry.get("title") or "").rstrip(".") + "."]
    venue = (entry.get("venue") or "").strip()
    if venue:
        parts.append(venue.rstrip(".") + ".")
    year = entry.get("year")
    if year:
        parts.append(f"{year}.")
    doi = (entry.get("doi") or "").strip()
    if doi:
        parts.append(f"https://doi.org/{doi}")
    return " ".join(parts)


def references_paragraphs(references: list[dict]) -> list[str]:
    """The `data["references"]["paragraphs"]` payload — one formatted citation
    per paragraph, ready for the References narrative node."""
    return [format_reference_entry(e) for e in references]


# ---------------------------------------------------------------------------
# Session-level orchestration — assemble from persisted per-stratum caches
# ---------------------------------------------------------------------------
# The pure functions above are the tested core.  These two read the persisted
# per-(organ, sex) interpretation caches (which carry `reference_pool` +
# `gene_set_narrative` + `gene_narrative`) and turn them into the report-wide
# reference list, deterministically.  Kept HERE so the whole references concern
# lives in one module; the disk read is a thin, lazily-imported shim.  Strata are
# ordered organ (liver, kidney, then alpha) then sex (male, female) so the
# report-wide numbering matches the document order the genomics tables render in.

_ORGAN_RANK = {"liver": 0, "kidney": 1}
_SEX_RANK = {"male": 0, "female": 1}


def collect_reference_strata(session_dir, genomics_cache: dict) -> list[dict]:
    """Load the per-stratum reference pools + narratives for a session.

    Reads the latest `_cache_interpretation_<organ>_<sex>_*.json` for every
    surviving key in `genomics_cache`, returning stratum dicts ordered by
    (organ, sex).  A stratum with no cached `reference_pool` is skipped (nothing
    to cite from).  Pure-ish: the only I/O is reading the JSON caches.
    """
    import json
    from pathlib import Path
    from genomics.genomics_narratives import interpretation_cache_prefix

    session_dir = Path(session_dir)
    if not isinstance(genomics_cache, dict):
        return []

    strata: list[dict] = []
    for key in genomics_cache:
        if "_" not in key:
            continue
        organ_k, sex_k = key.split("_", 1)
        organ_k, sex_k = organ_k.lower(), sex_k.lower()
        prefix = interpretation_cache_prefix(organ_k, sex_k)
        latest, latest_mtime = None, -1.0
        for cf in session_dir.glob(f"{prefix}*.json"):
            try:
                mt = cf.stat().st_mtime
            except OSError:
                continue
            if mt > latest_mtime:
                latest, latest_mtime = cf, mt
        if latest is None:
            continue
        try:
            interp = json.loads(latest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not interp.get("reference_pool"):
            continue
        strata.append({
            "organ": organ_k,
            "sex": sex_k,
            "reference_pool": interp.get("reference_pool") or [],
            "gene_set_narrative": interp.get("gene_set_narrative") or [],
            "gene_narrative": interp.get("gene_narrative") or [],
        })

    strata.sort(key=lambda s: (
        _ORGAN_RANK.get(s["organ"], 99), s["organ"],
        _SEX_RANK.get(s["sex"], 99), s["sex"],
    ))
    return strata


def load_persisted_references(session_dir) -> list[str]:
    """Read the persisted report-wide reference paragraphs for a session.

    Returns ``references.json``'s ``paragraphs`` (the formatted, numbered citation
    strings `_persist_references` wrote at process time) — the ONE consumed
    artifact both render paths read.  Returns [] when the file is absent or
    unreadable (older / apical-only sessions), so callers fall back cleanly.
    """
    import json
    from pathlib import Path

    path = Path(session_dir) / "references.json"
    if not path.exists():
        return []
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    paras = blob.get("paragraphs")
    return paras if isinstance(paras, list) and paras else []


def _load_narrative_overrides(session_dir) -> dict:
    """Read genomics_narrative_overrides.json (the ADR-0005 human-edit store).
    Returns ``{"gene_set": {...}, "gene_bmd": {...}}`` — empty buckets when the
    file is absent/unreadable, so callers need no guards."""
    import json
    from pathlib import Path

    path = Path(session_dir) / "genomics_narrative_overrides.json"
    if not path.exists():
        return {"gene_set": {}, "gene_bmd": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"gene_set": {}, "gene_bmd": {}}
    return {
        "gene_set": raw.get("gene_set", {}) or {},
        "gene_bmd": raw.get("gene_bmd", {}) or {},
    }


def build_session_references(session_dir, genomics_cache: dict, dtxsid: str = "") -> dict:
    """Assemble a session's report-wide references from its persisted caches.

    Returns ``{"references": [...], "paragraphs": [...], "rewritten": {(organ,
    sex): {gene_set_narrative, gene_narrative}}, "warnings": [...]}`` — the
    numbered list, its formatted paragraphs (for ``data["references"]``), the
    per-stratum narratives with ``[Pn]`` tokens rewritten to report-wide ``[n]``
    numbers so the inline citations agree with the References section, and any
    human-edit citation hazards (see `detect_override_citation_hazards`).  Empty
    when no stratum carries a reference pool.
    """
    strata = collect_reference_strata(session_dir, genomics_cache)
    if not strata:
        return {"references": [], "paragraphs": [], "rewritten": {}, "warnings": []}
    references, rewritten_list = assemble_report_references(strata)
    rewritten = {
        (r["organ"], r["sex"]): {
            "gene_set_narrative": r["gene_set_narrative"],
            "gene_narrative": r["gene_narrative"],
        }
        for r in rewritten_list
    }

    # Detect-and-warn for the two-store hazard: human narrative edits live in a
    # SEPARATE override store the assembly never sees, so their citations can't be
    # reconciled here.  Surface them loudly (log + machine-readable flag) rather
    # than let the rewrite silently drop/collide them.  No overrides ⇒ [] ⇒
    # byte-identical to before.
    pools_by_organ: dict[str, set[str]] = {}
    for s in strata:
        pools_by_organ.setdefault(s["organ"], set()).update(
            p["token"] for p in s["reference_pool"]
        )
    # Model-written citations that missed the pool (dropped from the prose by
    # the rewrite above — reported here so the drop is never silent) ...
    warnings = find_unresolved_citations(strata)
    for w in warnings:
        logger.warning(
            "References: %s narrative for %s/%s %s cites %s not in its "
            "reference pool — dropped from the prose, claim left uncited: %s",
            w["kind"], dtxsid or "?", w["organ"], w["sex"], w["tokens"],
            w["sentences"][:1],
        )
    # ... plus human-edit hazards (override store) as before.
    hazards = detect_override_citation_hazards(
        _load_narrative_overrides(session_dir), pools_by_organ,
    )
    for w in hazards:
        logger.warning(
            "References: human-edited %s narrative for %s/%s carries %s not "
            "reconciled with the auto-generated References list: %s",
            w["kind"], dtxsid or "?", w["organ"], w["issue"], w["tokens"],
        )
    warnings = warnings + hazards

    return {
        "references": references,
        "paragraphs": references_paragraphs(references),
        "rewritten": rewritten,
        "warnings": warnings,
    }
