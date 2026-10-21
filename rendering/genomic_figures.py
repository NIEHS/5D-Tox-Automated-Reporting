"""
rendering/genomic_figures.py — the gene set figures of each genomic analysis:
its semantic map and its gene-overlap clusters (a proposed section of the
report, eras/niehs-proposed).

The images are the Process step's charts (genomics.genomics_viz, the session's
``_cache_charts_*.json``: one UMAP semantic map and one cluster scatter per
tissue × sex).  A definition places them as `figure` nodes repeated per
genomic analysis (``repeat: genomic_analyses``), each bound to a data key this
module fills ``by_analysis`` (render_common.scoped_value):

  gene_set_map_figures      {"by_analysis": {key: {png_b64, svg, filename, notes}}}
  gene_set_cluster_figures  the same, for the cluster scatters
  gene_set_map_intro        {"paragraphs": [...]} — what the maps show
  gene_set_cluster_intro    {"paragraphs": [...]} — what the cluster charts show

and the appendix that explains them (eras/niehs-proposed):

  gene_set_map_method       how the semantic map and its clusters were derived
  gene_set_cluster_method   how the gene set clusters were made
  gene_set_figures_relation how the two clusterings relate
  gene_set_cluster_membership  {"by_analysis": {key: matrix}} — each active
                               gene set by its gene set cluster
  gene_set_semantic_membership the same, by semantic cluster

``svg`` is the chart as SVG, each marker titled with its gene set (the hover
text): an HTML surface shows it inline so a reader can point at a marker.

The rules are here: which figures the prose cites (the numbered figure nodes
bound to each key), the map's size (assets/data/umap_reference.json: its
terms and its semantic clusters), the statistic the gene sets' BMDs are (the
one the charts were drawn with), how many gene sets each figure shows.  The
words are the definition's ``phrasing.genomic_figures`` (document_model.
phrasing).  Captions are the figure nodes' own (the definition's).

The inline charts of the gene set tables (genomics_charts.attach_genomics_
charts, the ``charts:`` allowlist) are another placement of the same images;
this module neither reads nor changes that allowlist.
"""

from __future__ import annotations

import json
from pathlib import Path

from document_model.phrasing import Phrasing

MAP_KEY = "gene_set_map_figures"
CLUSTER_KEY = "gene_set_cluster_figures"
MAP_INTRO = "gene_set_map_intro"
CLUSTER_INTRO = "gene_set_cluster_intro"
MAP_METHOD = "gene_set_map_method"
CLUSTER_METHOD = "gene_set_cluster_method"
RELATION = "gene_set_figures_relation"
CLUSTER_MEMBERS = "gene_set_cluster_membership"
SEMANTIC_MEMBERS = "gene_set_semantic_membership"
# What the prose that presents the figures cites the appendix as.
CITED_APPENDIX = "genomic-figures-appendix"

_KINDS = {"umap": (MAP_KEY, "map"), "cluster": (CLUSTER_KEY, "clusters")}
_REFERENCE = Path(__file__).resolve().parent.parent / "assets" / "data" / "umap_reference.json"
STAT_UNRECORDED = "[Placeholder: the charts do not record the BMD statistic they plot]"


def _reference_size() -> tuple[int, int, int] | None:
    """(terms, semantic clusters, terms in no cluster) of the semantic map;
    None when unreadable."""
    try:
        points = json.loads(_REFERENCE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    clusters = [p.get("cluster") for p in points if isinstance(p, dict)]
    return (len(points), len({c for c in clusters if c is not None and c >= 0}),
            sum(1 for c in clusters if c is None or c < 0))


def _figure_labels(tree, key: str, figures: dict) -> list[str]:
    """The labels of the numbered figures bound to ``key`` that have an image,
    in document order."""
    from document_model.document_tree import walk_tree
    out: list[str] = []

    def visit(node) -> None:
        if (node.node_type == "figure" and node.data_key == key
                and node.figure_number is not None
                and (node.scope_analysis or "") in figures):
            out.append(str(node.figure_label or node.figure_number))

    walk_tree(tree or [], visit)
    return out


def _span(labels: list[str], p: Phrasing) -> str:
    if len(labels) == 1:
        return p.say("genomic_figures.span_one", first=labels[0])
    if len(labels) == 2:
        return p.say("genomic_figures.span_two", first=labels[0], last=labels[1])
    return p.say("genomic_figures.span_many", first=labels[0], last=labels[-1])


def _number(n: int) -> str:
    return f"{n:,}"


def attach_genomic_figures(data: dict, tree, phrasing: Phrasing, charts_cache) -> None:
    """Fill the four data keys (module docstring) from the session's chart
    cache, worded by ``phrasing``; ``tree`` is the report's numbered document
    tree.  Nothing when the definition places no figure bound to them, or
    there are no charts."""
    from document_model.document_tree import analysis_key, walk_tree
    bound: set[str] = set()
    walk_tree(tree or [], lambda n: bound.add(n.data_key)
              if n.node_type == "figure" and n.data_key else None)
    if not (bound & {MAP_KEY, CLUSTER_KEY}) or not isinstance(charts_cache, list):
        return
    from genomics.genomics_charts import decode_png
    figures: dict[str, dict] = {MAP_KEY: {}, CLUSTER_KEY: {}}
    stats: set = set()
    for chart in charts_cache:
        if not isinstance(chart, dict):
            continue
        key = analysis_key(chart.get("organ"), chart.get("sex"))
        counts = chart.get("counts") or {}
        stat = chart.get("bmd_stat")
        for kind, (data_key, wording) in _KINDS.items():
            png = chart.get(f"{kind}_png")
            if not png or decode_png(png) is None:
                continue
            payload = {"png_b64": png, "filename": f"gene-set-{wording}-{key}.png"}
            if chart.get(f"{kind}_svg"):
                payload["svg"] = chart[f"{kind}_svg"]
            if counts:
                payload["notes"] = [_note(wording, counts, stat, phrasing)]
            figures[data_key][key] = payload
            stats.add(stat)
    unit = data.get("dose_unit") or "mg/kg"
    statistic = (phrasing.word("statistic", next(iter(stats)))
                 if len(stats) == 1 and None not in stats else STAT_UNRECORDED)
    terms, clusters, unclustered = _reference_size() or (None, None, None)
    terms = _number(terms) if terms else "[Placeholder: the map's terms]"
    clusters = clusters if clusters else "[Placeholder: the map's clusters]"
    from rendering.genomics_results import cited
    appendix = cited(tree, CITED_APPENDIX, "appendix")
    spans = {}
    for data_key, intro_key, wording in ((MAP_KEY, MAP_INTRO, "map"),
                                         (CLUSTER_KEY, CLUSTER_INTRO, "clusters")):
        if data_key not in bound or not figures[data_key]:
            continue
        data[data_key] = {"by_analysis": figures[data_key]}
        labels = _figure_labels(tree, data_key, figures[data_key])
        if not labels:
            continue
        spans[wording] = cited_span = _span(labels, phrasing)
        if wording == "map":
            text = phrasing.say("genomic_figures.map.intro", figures=cited_span,
                                terms=terms, clusters=clusters)
        else:
            text = phrasing.say("genomic_figures.clusters.intro", figures=cited_span,
                                statistic=statistic, unit=unit)
        if appendix:
            text += phrasing.say("genomic_figures.appendix_cite", appendix=appendix)
        data[intro_key] = {"paragraphs": [text]}
    # The appendix: the derivations, how they relate, and the memberships.
    if not appendix:
        return
    figs = {"map_figures": spans.get("map", ""), "cluster_figures": spans.get("clusters", "")}
    data[MAP_METHOD] = {"paragraphs": _paragraphs(
        phrasing, "genomic_figures.method.map", terms=terms, clusters=clusters,
        unclustered=_number(unclustered or 0), **figs)}
    data[CLUSTER_METHOD] = {"paragraphs": _paragraphs(
        phrasing, "genomic_figures.method.clusters", statistic=statistic, unit=unit, **figs)}
    data[RELATION] = {"paragraphs": _paragraphs(
        phrasing, "genomic_figures.method.relation", **figs)}
    decimals = next(((e.get("display") or {}).get("decimals", 1)
                     for e in data.get("genomics_sections") or []
                     if e.get("type") == "gene_set"), 1)
    by_overlap, by_semantic = {}, {}
    for chart in charts_cache:
        if not isinstance(chart, dict) or not chart.get("members"):
            continue
        key = analysis_key(chart.get("organ"), chart.get("sex"))
        by_overlap[key], by_semantic[key] = _membership(
            chart["members"], phrasing, statistic, unit, decimals)
    if by_overlap:
        data[CLUSTER_MEMBERS] = {"by_analysis": by_overlap}
        data[SEMANTIC_MEMBERS] = {"by_analysis": by_semantic}


def _paragraphs(p: Phrasing, key: str, **fields) -> list[str]:
    """A declared list of paragraph templates, filled."""
    from document_model.phrasing import missing
    templates = p.items(key)
    return [t.format_map(fields) for t in templates] if templates else [missing(key)]


def _membership(members: list[dict], p: Phrasing, statistic: str, unit: str,
                decimals: int) -> tuple[dict, dict]:
    """An analysis' two membership tables: every active gene set with both of
    its clusters, grouped by its gene set cluster (in the figure's order,
    lowest BMD first) and by its semantic cluster (in the map's numbering)."""
    from tables.table_builder_common import format_display_number

    def bmd_key(m):
        return (m.get("bmd") is None, m.get("bmd") or 0.0, m.get("go_term") or "")

    def semantic(m):
        if m.get("semantic") is None:
            return p.say("genomic_figures.membership.off_map")
        return str(m["semantic"]) if m["semantic"] >= 0 else p.say("genomic_figures.membership.none")

    def overlap(m):
        return str(m["overlap"]) if m.get("overlap", -1) >= 0 else p.say("genomic_figures.membership.none")

    def row(first, second, m):
        return [first, second, m.get("go_id") or "", m.get("go_term") or "",
                format_display_number(m.get("bmd"), decimals)]

    fields = {"statistic": statistic, "unit": unit}
    lowest = {}
    for m in members:
        if m.get("bmd") is not None:
            c = m.get("overlap", -1)
            lowest[c] = min(lowest.get(c, m["bmd"]), m["bmd"])
    order = sorted({m.get("overlap", -1) for m in members},
                   key=lambda c: (c < 0, lowest.get(c, float("inf")), c))
    rows_o = [row(overlap(m), semantic(m), m)
              for c in order for m in sorted((m for m in members if m.get("overlap", -1) == c),
                                             key=bmd_key)]

    def sem_rank(m):
        s = m.get("semantic")
        return (s is None, s is not None and s < 0, s if s is not None else 0)
    rows_s = [row(semantic(m), overlap(m), m)
              for m in sorted(members, key=lambda m: (sem_rank(m), bmd_key(m)))]
    foot = [{"text": p.say("genomic_figures.membership.footnote")}]
    heads_o = [h.format(**fields) for h in p.items("genomic_figures.membership.by_cluster_headers")]
    heads_s = [h.format(**fields) for h in p.items("genomic_figures.membership.by_semantic_headers")]
    # Hundreds of rows: a table that breaks across pages, the term wrapping.
    layout = {"footnotes": foot, "breakable": True, "col_widths": _MEMBERSHIP_WIDTHS}
    return ({"headers": heads_o, "rows": rows_o, **layout},
            {"headers": heads_s, "rows": rows_s, **layout})


# Fractions of the text width: two cluster columns, the GO ID, the term, the
# BMD (with the columns' padding, the full width).
_MEMBERSHIP_WIDTHS = [0.10, 0.11, 0.13, 0.40, 0.13]


def _note(wording: str, counts: dict, stat, p: Phrasing) -> str:
    """The figure's note: how many of the analysis' gene sets it shows."""
    n = int(counts.get("gene_sets") or 0)
    if wording == "map":
        on = int(counts.get("on_map") or 0)
        if on >= n:
            return p.say("genomic_figures.map.note_all", gene_sets=_number(n))
        return p.say("genomic_figures.map.note", on_map=_number(on), gene_sets=_number(n),
                     off_map=_number(n - on))
    statistic = p.word("statistic", stat) if stat else STAT_UNRECORDED
    return p.say("genomic_figures.clusters.note",
                 gene_sets=_number(int(counts.get("with_bmd") or 0)),
                 clusters=_number(int(counts.get("overlap_clusters") or 0)),
                 statistic=statistic)
