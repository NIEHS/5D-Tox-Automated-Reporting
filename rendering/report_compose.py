"""
report_compose.py — a report over several studies (ADR-0029 §9).

NIEHS-12 and 13 report two studies of one chemical in one book: a rat study
and a mouse study, each with its own animals, dose levels and genomic project.
Each study is its own session, run through the pipeline unchanged; the report
session lists them in ``studies.json`` — ``{"rat": "<id>_rat", "mouse":
"<id>_mouse"}``, species → member session, in the book's order — and keeps
what is the report's own: front matter, Background, deposit, views, overrides.

compose_studies merges the members' data into the report's at the one data
entry point (latex_export.load_session_data):

  - ``data["studies"]``: each study's key, title ("Rats"), session and its
    study data (STUDY_KEYS).  A section the document repeats per study
    (``repeat: study_species``) renders from its study's data
    (render_common.node_data).
  - The combined tables: each study's rows become a group under the study's
    label — "Rats" / "Mice" when every study is of one sex (as the 2026 books
    print them), else "Female Rats" … .  Studies given different dose levels
    share the union of the levels; a level a study did not test shows NA.
  - The study design lists the studies (pipeline.study_design reads "Rats and
    Mice"); the title, captions and abstract follow from it.

A report session without ``studies.json`` is a single study: nothing changes.
"""

from __future__ import annotations

import copy
import json
import re

from pipeline.deposit import SPECIES_TITLES

STUDIES_FILE = "studies.json"

# The study data a member contributes.  A node scoped to one study renders
# with these taken from that study (render_common.node_data); everything else
# (front matter, Background, deposit, overrides …) is the report's.
STUDY_KEYS = (
    "apical_sections", "genomics_sections", "bmd_summary", "unified_narratives",
    "methods", "sample_counts", "study_design", "dose_unit", "internal_dose",
    "summary", "collected_platforms", "appendix_animals", "appendix_animals_matrix",
    "appendix_pca_figure", "appendix_bmd_config_matrix", "appendix_bmd_acceptance_matrix",
    "gene_set_narrative", "gene_narrative",
)

_SEXES = ("Male", "Female")
_CITATION = re.compile(r"\[(\d+(?:\s*[,–-]\s*\d+)*)\]")


def member_sessions(dtxsid: str) -> list[tuple[str, str]]:
    """[(study key, member session id)] from the report session's studies.json,
    in its order; [] for a single-study session."""
    from pipeline.session_store import SESSIONS_DIR
    path = SESSIONS_DIR / dtxsid / STUDIES_FILE
    if not path.exists():
        return []
    stated = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(stated, dict) or not all(isinstance(v, str) for v in stated.values()):
        raise ValueError(f"{path}: expected {{study key: member session id}}")
    return list(stated.items())


def compose_studies(data: dict, dtxsid: str, chemical_name: str, casrn: str,
                    view: str | None = None) -> bool:
    """Merge the report session's member studies into ``data`` (in place).
    False, with ``data`` untouched, when the session lists no studies."""
    members = member_sessions(dtxsid)
    if not members:
        return False
    from rendering.latex_export import load_session_data

    studies = []
    for key, member in members:
        mdata = load_session_data(member, chemical_name, casrn, view)
        sdata = {k: mdata[k] for k in STUDY_KEYS if k in mdata}
        # The study's strain designation (its front matter) goes with its design.
        if isinstance(sdata.get("study_design"), dict) and mdata.get("strain"):
            sdata["study_design"] = dict(sdata["study_design"], designation=mdata["strain"])
        studies.append({"key": key, "title": SPECIES_TITLES.get(key, key.title()),
                        "dtxsid": member, "data": sdata,
                        "abstract": mdata.get("abstract"),
                        "references": (mdata.get("references") or {}).get("paragraphs") or []})
    _renumber_references(data, studies)
    one_sex = all(len(_study_sexes(s["data"])) <= 1 for s in studies)
    for s in studies:
        s["labels"] = {sex: (s["title"] if one_sex else f"{sex} {s['title']}")
                       for sex in _SEXES}
        s["label"] = s["title"]
    data["studies"] = [{k: s[k] for k in ("key", "title", "dtxsid", "data")} for s in studies]

    first = studies[0]["data"]
    # The title and running header name the studies' animals; each combined
    # table's caption names those of the studies it has rows for (below).
    from rendering.report_data import apply_design
    apply_design(data, composed_design([s["data"].get("study_design") or {} for s in studies]))
    data["dose_unit"] = first.get("dose_unit") or data.get("dose_unit")
    # The prose shared by the studies (Chemistry, Transcriptomics …) is the
    # first study's; a section about one study is repeated and scoped to it.
    for key in ("methods", "internal_dose", "appendix_bmd_config_matrix",
                "appendix_bmd_acceptance_matrix"):
        if key in first:
            data[key] = copy.deepcopy(first[key])
    data["apical_sections"] = _merge_apical(studies)
    data["genomics_sections"] = _merge_genomics(studies)
    data["bmd_summary"] = _merge_bmd_summary(studies, data.get("bmd_summary") or {})
    counts = _merge_sample_counts(studies)
    if counts:
        data["sample_counts"] = counts
    if not (data.get("summary") or {}).get("paragraphs"):
        data["summary"] = {"paragraphs": [p for s in studies
                                          for p in (s["data"].get("summary") or {}).get("paragraphs") or []]}
    _merge_abstract(data, studies)
    return True


# ---------------------------------------------------------------------------
# The studies' design
# ---------------------------------------------------------------------------

def composed_design(designs: list[dict]) -> dict:
    """One study's design as is; several studies' as the facts they share
    (route, vehicle, duration) with the studies listed under ``studies`` —
    pipeline.study_design then names their animals together ("Rats and Mice")."""
    if len(designs) == 1:
        return designs[0]
    out = {"species": None, "strain": None, "studies": designs, "fallback": [],
           "conflicts": sorted({c for d in designs for c in d.get("conflicts") or []})}
    for field in ("route", "vehicle", "duration_days"):
        values = {d.get(field) for d in designs}
        out[field] = values.pop() if len(values) == 1 else None
        if len({d.get(field) for d in designs}) > 1:
            out["conflicts"].append(field)
    return out


def _study_sexes(sdata: dict) -> set[str]:
    """The sexes a study's data has rows for."""
    found = set()
    for sec in sdata.get("apical_sections") or []:
        found |= {k for k, rows in (sec.get("table_data") or {}).items() if rows}
    for entry in sdata.get("genomics_sections") or []:
        found |= {str(b.get("sex", "")).title() for b in entry.get("sexes") or []}
    found |= {str(e.get("sex", "")).title()
              for e in (sdata.get("bmd_summary") or {}).get("endpoints") or []}
    return found & set(_SEXES)


def _label(study: dict, sex) -> str:
    return study["labels"].get(str(sex or "").strip().title(), study["title"])


# ---------------------------------------------------------------------------
# Combined tables
# ---------------------------------------------------------------------------

def _merge_apical(studies: list[dict]) -> list[dict]:
    """One section per platform; each study's rows a group under its label."""
    from rendering.render_common import table_groups
    from tables.table_builder_common import finalize_footnotes, refresh_caption_compound

    order: list[str] = []
    by_platform: dict[str, list[tuple[dict, dict]]] = {}
    for s in studies:
        for sec in s["data"].get("apical_sections") or []:
            p = sec.get("platform") or sec.get("title") or ""
            if p not in by_platform:
                order.append(p)
                by_platform[p] = []
            by_platform[p].append((s, sec))
    merged = []
    for p in order:
        parts = by_platform[p]
        out = copy.deepcopy(parts[0][1])
        table_data: dict[str, list] = {}
        footnotes: list[dict] = []
        for s, sec in parts:
            remap = _merge_footnotes(footnotes, sec.get("footnotes") or [], s["key"])
            for sex, rows in table_groups(sec.get("table_data") or {}):
                table_data.setdefault(_label(s, sex), []).extend(
                    _remap_markers(copy.deepcopy(rows), remap))
        out["table_data"] = table_data
        out["footnotes"] = finalize_footnotes(footnotes, table_data)
        out["narrative"] = []
        if out.get("caption"):
            design = composed_design([s["data"].get("study_design") or {} for s, _ in parts])
            out["caption"] = refresh_caption_compound(out["caption"], "", design)
        merged.append(out)
    return merged


def _merge_footnotes(into: list[dict], footnotes: list[dict], suffix: str) -> dict:
    """Append a study's footnotes not already stated; a footnote id another
    study states with other text is renamed.  Returns {old id: new id}."""
    by_id = {fn.get("id"): fn for fn in into if fn.get("id")}
    stated = {(fn.get("kind"), fn.get("text")) for fn in into}
    remap = {}
    for fn in footnotes:
        fn = copy.deepcopy(fn)
        fid = fn.get("id")
        if fid and fid in by_id:
            if by_id[fid].get("text") == fn.get("text"):
                continue
            fn["id"] = remap[fid] = f"{fid}--{suffix}"
        elif not fid and (fn.get("kind"), fn.get("text")) in stated:
            continue
        fn.pop("letter", None)
        into.append(fn)
        stated.add((fn.get("kind"), fn.get("text")))
        if fn.get("id"):
            by_id[fn["id"]] = fn
    return remap


def _remap_markers(rows: list[dict], remap: dict) -> list[dict]:
    if remap:
        for row in rows:
            refs = row.get("marker_refs")
            if isinstance(refs, dict):
                row["marker_refs"] = {k: remap.get(v, v) for k, v in refs.items()}
    return rows


def _merge_genomics(studies: list[dict]) -> list[dict]:
    """One table per (type, tissue); each study's rows a group under its label.
    The tissue's prose is per study (a scoped section), not the table's."""
    order: list[tuple] = []
    by_key: dict[tuple, dict] = {}
    for s in studies:
        for entry in s["data"].get("genomics_sections") or []:
            key = (entry.get("type"), entry.get("organ"))
            blocks = entry.get("sexes")
            if not isinstance(blocks, list):
                blocks = [{k: v for k, v in entry.items()
                           if k in ("sex", "gene_sets", "top_genes", "narrative")}]
            blocks = [{**{k: copy.deepcopy(v) for k, v in b.items() if k != "narrative"},
                       "sex": _label(s, b.get("sex"))} for b in blocks]
            if key not in by_key:
                out = copy.deepcopy(entry)
                out["sexes"], out["narrative"] = [], []
                for k in ("go_descriptions", "gene_descriptions", "charts"):
                    if k in out:
                        out[k] = []
                order.append(key)
                by_key[key] = out
            out = by_key[key]
            out["sexes"].extend(blocks)
            # A chart is one study's: labelled with it, so its id is unique.
            for chart in entry.get("charts") or []:
                out.setdefault("charts", []).append(
                    dict(copy.deepcopy(chart), sex=_label(s, chart.get("sex"))))
            for k in ("go_descriptions", "gene_descriptions"):
                seen = {json.dumps(d, sort_keys=True) for d in out.get(k) or []}
                for d in entry.get(k) or []:
                    if json.dumps(d, sort_keys=True) not in seen:
                        out.setdefault(k, []).append(copy.deepcopy(d))
    return [by_key[k] for k in order]


def _merge_bmd_summary(studies: list[dict], report: dict) -> dict:
    """The studies' endpoints, study by study (each already sorted by BMD or
    LOEL within its sexes), under the studies' labels."""
    endpoints, paragraphs = [], []
    for s in studies:
        summary = s["data"].get("bmd_summary") or {}
        for ep in summary.get("endpoints") or []:
            endpoints.append(dict(ep, sex=_label(s, ep.get("sex"))))
    out = dict(report)
    out["endpoints"] = endpoints
    out["paragraphs"] = report.get("paragraphs") or paragraphs
    return out


_DOSE_HEAD = re.compile(r"^\s*([\d.,]+)")


def _merge_sample_counts(studies: list[dict]) -> dict | None:
    """Table 1 over the studies: the union of their dose columns (NA where a
    study did not test the level), each study's rows under its label."""
    tables = [(s, s["data"].get("sample_counts")) for s in studies]
    tables = [(s, t) for s, t in tables if t and t.get("headers")]
    if not tables:
        return None

    def level(head):
        m = _DOSE_HEAD.match(str(head))
        return float(m.group(1).replace(",", "")) if m else None

    heads: dict[float, str] = {}
    for _, t in tables:
        for h in t["headers"][1:]:
            if level(h) is not None:
                heads.setdefault(level(h), h)
    columns = sorted(heads)
    out = copy.deepcopy(tables[0][1])
    out["headers"] = [tables[0][1]["headers"][0]] + [heads[c] for c in columns]
    out["rows"] = []
    for s, t in tables:
        own = [level(h) for h in t["headers"][1:]]
        for row in t["rows"]:
            if row and str(row[0]).startswith("**"):
                sex = str(row[0]).strip("* ")
                out["rows"].append([f"**{_label(s, sex)}**"] + [""] * len(columns))
                continue
            cells = dict(zip(own, row[1:]))
            out["rows"].append([row[0]] + [cells.get(c, "NA") for c in columns])
        for fn in t.get("footnotes") or []:
            if fn not in out["footnotes"]:
                out["footnotes"].append(fn)
    return out


# ---------------------------------------------------------------------------
# Prose the studies share
# ---------------------------------------------------------------------------

def _merge_abstract(data: dict, studies: list[dict]) -> None:
    """The abstract's Methods, Results and Summary state each study in turn;
    its Background is the report's."""
    sections = list((data.get("abstract") or {}).get("sections") or [])
    for label in ("Methods", "Results", "Summary"):
        texts = [sec.get("text") for s in studies
                 for sec in (s.get("abstract") or {}).get("sections") or []
                 if sec.get("label", "").lower() == label.lower() and (sec.get("text") or "").strip()]
        if not texts:
            continue
        text = " ".join(texts)
        for sec in sections:
            if sec.get("label", "").lower() == label.lower():
                sec["text"] = text
                break
        else:
            sections.append({"label": label, "text": text})
    data["abstract"] = {"sections": sections}


def _renumber_references(data: dict, studies: list[dict]) -> None:
    """One References list: the report's Background references, then each
    study's genomic references, numbered on from them — the citations in a
    study's genomic prose renumbered to match."""
    report = list((data.get("references") or {}).get("paragraphs") or [])
    offset = len(report)
    for s in studies:
        refs = s["references"]
        if not refs:
            continue
        shift = offset

        def renumber(text, shift=shift):
            return _CITATION.sub(lambda m: "[" + re.sub(
                r"\d+", lambda n: str(int(n.group()) + shift), m.group(1)) + "]", text)

        report.extend(renumber(p) for p in refs)
        _rewrite_narratives(s["data"].get("genomics_sections"), renumber)
        offset += len(refs)
    if report:
        data["references"] = {"paragraphs": report}


def _rewrite_narratives(node, fn) -> None:
    """Apply ``fn`` to every prose string under a ``*narrative*`` key."""
    if isinstance(node, list):
        for item in node:
            _rewrite_narratives(item, fn)
    elif isinstance(node, dict):
        for k, v in node.items():
            if "narrative" in k:
                node[k] = _rewrite_text(v, fn)
            else:
                _rewrite_narratives(v, fn)


def _rewrite_text(value, fn):
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, list):
        return [_rewrite_text(v, fn) for v in value]
    if isinstance(value, dict):
        return {k: _rewrite_text(v, fn) for k, v in value.items()}
    return value
