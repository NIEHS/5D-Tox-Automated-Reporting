"""
rendering/genomics_results.py — the gene set and gene results as the books
write them (NIEHS-12, 13 Results; NIEHS-10's are the same sentences).

Each sentence is built from the tables the report prints — the top gene sets
and top genes of each tissue, the most potent gene set per tissue — so the
prose states exactly what the tables do, programmatically, no model:

  gene_set_intro   the Gene Set Benchmark Dose Analysis' opening: what was
                   examined, where the tables are, the gene sets below the
                   lower limit of extrapolation, the caution.
  entry["results"] per tissue and study: "The most sensitive GO biological
                   processes for which a BMD value could be reliably
                   calculated were … (GO:…) and … with 5th percentile BMDs
                   (BMD_Ls) of … ppm, respectively (Table 7)."; the gene
                   analysis' "The most sensitive upregulated genes with a
                   calculated BMD were Spp1 (secreted phosphoprotein 1) …".
  gene_set_summary "A summary of the most potent gene set per tissue is
                   provided in Table 12.  In rats exposed to 1,4-DCB, the
                   liver had the gene set with the lowest BMD 5th percentile
                   value, corresponding to …".
  gene_intro       the Gene Benchmark Dose Analysis' opening.

The rules are the books':

  - A gene set or gene is "reliably calculated" when its BMD is at least the
    lower limit of extrapolation (the lowest non-zero dose / 3, "<0.333 ppm");
    one below it is stated apart ("… with an estimated median BMD <0.333 ppm").
  - The gene sets named are the two most potent, and any tied with the
    second (NIEHS-12 rat lung: three, "all three with …").
  - The genes named are the table's top genes, upregulated then downregulated
    ("One gene, Sult1c3 …, was downregulated …"; "All 10 of the most sensitive
    heart genes were downregulated."; "Half of the top 10 …"; "Only eight
    genes met the criteria.").
  - A gene is printed with its full name (genomics.gene_names), its symbol in
    italics; the BMDL's L a subscript.
  - The "full list … can be found in Appendix G" sentence closes a tissue's
    gene set results, naming the animals with gene sets there.

What a definition prints is its choice: the 2026 era binds these keys
(eras/niehs-2026.yaml); the per-tissue results reach a tissue's section
through render_common.node_data (``gene_set_results`` / ``gene_results``).
Paragraphs are inline-unit lists (render_common's inline model).
"""

from __future__ import annotations

import math
import re

from rendering.render_common import make_italic, make_sub
from tables.table_builder_common import format_display_number

# The ranking statistic as the prose names it.
_STAT = {"fifth_pct": "5th percentile", "median": "median"}
# The aggregate score of gene set potency the analysis used (the intro).
_SCORE = {"fifth_pct": "5th percentile of transcript BMDs", "median": "median transcript BMD"}
_WORDS = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")
_ALL = {2: "both", 3: "all three", 4: "all four", 5: "all five"}
_MARKUP = re.compile(r"\*([^*]+)\*|BMD_L")
GENE_NAME_PENDING = "[Placeholder: gene name]"


def units(text: str) -> list:
    """A sentence's inline units: ``*x*`` in italics, ``BMD_L``'s L a subscript."""
    out: list = []
    pos = 0
    for m in _MARKUP.finditer(text):
        if m.start() > pos:
            out.append(text[pos:m.start()])
        if m.group(1) is not None:
            out.append(make_italic(m.group(1)))
        else:
            out += ["BMD", make_sub("L")]
        pos = m.end()
    if pos < len(text):
        out.append(text[pos:])
    return out


def _join(items: list[str]) -> str:
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + ", and " + items[-1]


def _word(n: int) -> str:
    return _WORDS[n] if 0 <= n < len(_WORDS) else str(n)


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def _lower_first(s: str) -> str:
    return s[:1].lower() + s[1:]


# ---------------------------------------------------------------------------
# The report's studies and groups
# ---------------------------------------------------------------------------

class _Report:
    """What the sentences name: each study's animals and dose, the unit, the
    precision, the chemical."""

    def __init__(self, data: dict):
        from pipeline.study_design import design_or_standard, exposure_verb, species_plural
        self.data = data
        studies = data.get("studies") or []
        design = data.get("study_design") or {}
        self.verb = exposure_verb(design)
        self.chemical = data.get("abbreviation") or _chemical_in_prose(data.get("chemical_name"))
        if studies:
            self.studies = [(s["key"], s["title"].lower(), s.get("data") or {}) for s in studies]
        else:
            self.studies = [("", species_plural(design_or_standard(design)), data)]
        self.lle = {key: _lle(sdata) for key, _, sdata in self.studies}
        self.noun = {key: noun for key, noun, _ in self.studies}
        # The groups each study's genomic tables hold (its sexes, or the one study).
        self.labels: dict[str, list[str]] = {key: [] for key, _, _ in self.studies}
        for entry in data.get("genomics_sections") or []:
            for b in _blocks(entry):
                key = b.get("study") or ""
                if key in self.labels and b.get("sex") not in self.labels[key]:
                    self.labels[key].append(b.get("sex"))

    def group_noun(self, key: str, label) -> str:
        """"rats", "female rats", "mice" — a table group's animals."""
        if key:
            return str(label or self.noun[key]).lower()
        if len(self.labels.get(key) or []) > 1:
            return f"{str(label or '').lower()} {self.noun[key]}".strip()
        return self.noun[key]

    def several_groups(self, key: str) -> bool:
        return len(self.labels.get(key) or []) > 1

    def subjects(self, keys: list[str]) -> str:
        """"female rats and mice" — the animals of these studies (captions')."""
        from pipeline.study_design import caption_subject
        if not self.data.get("studies"):
            return caption_subject(self.data.get("study_design") or {}).lower()
        from rendering.report_compose import composed_design
        designs = [(sdata.get("study_design") or {}) for key, _, sdata in self.studies
                   if key in keys]
        return caption_subject(composed_design(designs)).lower()


def _chemical_in_prose(name) -> str:
    """A chemical's name mid-sentence: "triclosan", "1,4-dichlorobenzene",
    "bisphenol AF" — each word capitalized only as a title capitalizes it
    (its one capital its first letter) lowered; "PFHxSAm", "AF" as written."""
    def word(w: str) -> str:
        caps = [i for i, c in enumerate(w) if c.isupper()]
        first = next((i for i, c in enumerate(w) if c.isalpha()), None)
        return w[:first] + w[first].lower() + w[first + 1:] if caps == [first] else w
    return " ".join(word(w) for w in str(name or "the test article").split())


def _lle(sdata: dict) -> float | None:
    """The lower limit of extrapolation: the study's lowest non-zero dose / 3."""
    for sec in sdata.get("apical_sections") or []:
        for rows in (sec.get("table_data") or {}).values():
            for row in rows or []:
                doses = [d for d in (_num(x) for x in row.get("doses") or []) if d and d > 0]
                if doses:
                    return min(doses) / 3
    return None


def _blocks(entry: dict) -> list[dict]:
    sexes = entry.get("sexes")
    if isinstance(sexes, list):
        return sexes
    return [{k: v for k, v in entry.items() if k in ("sex", "gene_sets", "top_genes")}]


def _display(entry: dict) -> dict:
    return entry.get("display") if isinstance(entry.get("display"), dict) else {}


def _lle_text(lle: float) -> str:
    return f"{lle:.3f}"


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------

class _Values:
    def __init__(self, entry: dict, unit: str):
        d = _display(entry)
        self.dec = d.get("decimals", 3)
        self.unit = d.get("unit") or unit
        self.stat = d.get("stat", "median")

    def one(self, v) -> str:
        return format_display_number(v, self.dec) if _num(v) is not None else "NC"

    def pair(self, row: dict) -> str:
        return f"{self.one(row.get('bmd'))} ({self.one(row.get('bmdl'))})"

    def clause(self, rows: list[dict], what: str) -> str:
        """" with 5th percentile BMDs (BMD_Ls) of a (b) and c (d) ppm,
        respectively", or ", both with a 5th percentile BMD (BMD_L) of a (b) ppm"."""
        pairs = [self.pair(r) for r in rows]
        lead = f"{what} " if what else ""
        if len(set(pairs)) == 1 and len(pairs) in _ALL:
            return f", {_ALL[len(pairs)]} with a {lead}BMD (BMD_L) of {pairs[0]} {self.unit}"
        return f" with {lead}BMDs (BMD_Ls) of {_join(pairs)} {self.unit}, respectively"


def _reliable(rows: list[dict], lle: float | None) -> list[dict]:
    out = [r for r in rows or [] if _num(r.get("bmd")) is not None
           and (lle is None or _num(r.get("bmd")) >= lle)]
    return sorted(out, key=lambda r: _num(r.get("bmd")))


def _below(rows: list[dict], lle: float | None) -> list[dict]:
    if lle is None:
        return []
    return [r for r in rows or [] if (b := _num(r.get("bmd"))) is not None and b < lle]


# ---------------------------------------------------------------------------
# Gene set results, per tissue and study
# ---------------------------------------------------------------------------

def _top_gene_sets(sets: list[dict], values: _Values) -> list[dict]:
    """The two most potent, and any tied with the second (the same BMD and
    BMDL as printed)."""
    if len(sets) <= 2:
        return sets
    second = values.pair(sets[1])
    return sets[:2] + [s for s in sets[2:] if values.pair(s) == second]


def _gene_set_sentence(sets: list[dict], values: _Values, table: str) -> str:
    stat = _STAT.get(values.stat, values.stat)
    terms = [f"{s.get('go_term', '')} ({s.get('go_id', '')})" for s in sets]
    if len(sets) == 1:
        return (f"The most sensitive GO biological process for which a BMD value could be "
                f"reliably calculated was {terms[0]} with a {stat} BMD (BMD_L) of "
                f"{values.pair(sets[0])} {values.unit}{table}.")
    return (f"The most sensitive GO biological processes for which a BMD value could be "
            f"reliably calculated were {_join(terms)}{values.clause(sets, stat)}{table}.")


def _gene_set_results(entry: dict, report: _Report, unit: str, appendix: str | None) -> None:
    values = _Values(entry, unit)
    table = f" (Table {entry['table_number']})" if entry.get("table_number") else ""
    results: dict[str, list] = {}
    with_sets: list[str] = []
    for key, _, _ in report.studies:
        sentences = []
        for b in [b for b in _blocks(entry) if (b.get("study") or "") == key]:
            noun = report.group_noun(key, b.get("sex"))
            sets = _reliable(b.get("gene_sets"), report.lle.get(key))
            if not sets:
                sentences.append(f"In {noun} {report.verb} {report.chemical}, there were no "
                                 f"active GO terms (i.e., no gene expression response at the "
                                 f"gene set level).")
                continue
            if key not in with_sets:
                with_sets.append(key)
            sentence = _gene_set_sentence(_top_gene_sets(sets, values), values, table)
            if report.several_groups(key):
                sentence = f"In {noun}, {_lower_first(sentence)}"
            sentences.append(sentence)
        if sentences:
            results[key] = sentences
    if with_sets and appendix:
        organ = (entry.get("organ") or "").strip().lower()
        results[with_sets[-1]].append(
            f"The full list of affected gene sets in the {organ} of "
            f"{report.subjects(with_sets)} can be found in Appendix {appendix}.")
    entry["results"] = {k: [units(" ".join(v))] for k, v in results.items()}


# ---------------------------------------------------------------------------
# Gene results, per tissue and study
# ---------------------------------------------------------------------------

def _gene(row: dict, names: dict) -> str:
    symbol = str(row.get("gene") or row.get("gene_symbol") or "")
    name = names.get(str(row.get("entrez_id") or ""))
    return f"*{symbol}* ({name or GENE_NAME_PENDING})"


def _gene_list_sentence(genes: list[dict], lead: str, values: _Values, names: dict) -> str:
    listed = _join([_gene(g, names) for g in genes])
    return f"{lead} {listed}{values.clause(genes, '')}."


def _one_gene(gene: dict, direction: str, values: _Values, names: dict) -> str:
    return (f"One gene, {_gene(gene, names)}, was {direction}regulated with a BMD (BMD_L) of "
            f"{values.pair(gene)} {values.unit}.")


def _gene_block(genes: list[dict], organ: str, noun: str, lle: float | None,
                values: _Values, names: dict) -> list[str]:
    """One group's gene results (the books' patterns, module docstring)."""
    if not genes:
        return [f"No {organ} genes in {noun} met the criteria."]
    out: list[str] = []
    below = _below(genes, lle)
    calc = [g for g in genes if g not in below]
    if below:
        dirs = {str(g.get("direction", "")).lower() for g in below}
        plural = len(below) > 1
        exhibit = (f", exhibiting {'an increase' if dirs == {'up'} else 'a decrease'} in "
                   f"expression," if len(dirs) == 1 else "")
        out.append(f"The most sensitive {organ} gene{'s' if plural else ''} in {noun}{exhibit} "
                   f"{'were' if plural else 'was'} {_join([_gene(g, names) for g in below])} "
                   f"with {'estimated median BMDs' if plural else 'an estimated median BMD'} "
                   f"<{_lle_text(lle)} {values.unit}.")
    few = len(genes) < 10
    if few:
        out.append(f"Only {_word(len(genes))} genes met the criteria.")
    up = [g for g in calc if str(g.get("direction", "")).lower() == "up"]
    down = [g for g in calc if str(g.get("direction", "")).lower() == "down"]
    body: list[str] = []
    if not below and up and down and len(up) == len(down) and len(genes) == 10:
        body.append(f"Half of the top 10 most sensitive {organ} genes were upregulated and the "
                    f"other half were downregulated.")
        body.append(_gene_list_sentence(up, "The upregulated genes with a calculated BMD were",
                                        values, names))
        body.append(_gene_list_sentence(down, "The downregulated genes with a calculated BMD "
                                        "were", values, names))
    elif not below and calc and not (up and down) and len(calc) > 1:
        direction = "up" if up else "down"
        body.append(f"All {len(calc)} of the most sensitive {organ} genes were "
                    f"{direction}regulated.")
        body.append(_gene_list_sentence(calc, "These genes were", values, names))
    else:
        for group, direction, lead in (
                (up, "up", "The most sensitive upregulated genes with a calculated BMD were"),
                (down, "down", "The most sensitive genes exhibiting a decrease in expression "
                               "were")):
            if len(group) == 1:
                body.append(_one_gene(group[0], direction, values, names))
            elif group:
                body.append(_gene_list_sentence(group, lead, values, names))
    if few and body:
        body[0] = f"Of these {_word(len(genes))} genes, {_lower_first(body[0])}"
    return out + body


def _gene_results(entry: dict, report: _Report, unit: str, names: dict) -> None:
    values = _Values(entry, unit)
    organ = (entry.get("organ") or "").strip().lower()
    results: dict[str, list] = {}
    for key, _, _ in report.studies:
        sentences = []
        for b in [b for b in _blocks(entry) if (b.get("study") or "") == key]:
            noun = report.group_noun(key, b.get("sex"))
            block = _gene_block(b.get("top_genes") or [], organ, noun, report.lle.get(key),
                                values, names)
            if report.several_groups(key) and block and not block[0].startswith(
                    "The most sensitive " + organ):
                block[0] = f"In {noun}, {_lower_first(block[0])}"
            sentences += block
        if sentences:
            results[key] = [units(" ".join(sentences))]
    entry["results"] = results


# ---------------------------------------------------------------------------
# The sections' openings and the gene set summary
# ---------------------------------------------------------------------------

def _tables_phrase(entries: list[dict]) -> tuple[str, str]:
    """("the heart (Table 7), kidney (Table 8), …", "Table 7 to Table 11")."""
    shown = [((e.get("organ") or "").strip().lower(), e.get("table_number")) for e in entries]
    where = "the " + _join([f"{o} (Table {n})" if n else o for o, n in shown])
    numbers = [n for _, n in shown if n]
    if not numbers:
        span = "these tables"
    elif len(numbers) == 1:
        span = f"Table {numbers[0]}"
    elif len(numbers) == 2:
        span = f"Table {numbers[0]} and Table {numbers[1]}"
    else:
        span = f"Table {numbers[0]} to Table {numbers[-1]}"
    return where, span


def _exceptions(entries: list[dict], rows_key: str, report: _Report, noun: str) -> str:
    """" with the exception of one lung gene in mice" — the items below the
    lower limit of extrapolation, by tissue and group; "" when none."""
    found = []
    for e in entries:
        organ = (e.get("organ") or "").strip().lower()
        for b in _blocks(e):
            key = b.get("study") or ""
            n = len(_below(b.get(rows_key), report.lle.get(key)))
            if n:
                found.append(f"{_word(n)} {organ} {noun}{'s' if n > 1 else ''} in "
                             f"{report.group_noun(key, b.get('sex'))}")
    return f" with the exception of {_join(found)}" if found else ""


def _lle_sentence(entries, rows_key, report, noun: str, what: str, unit: str) -> str:
    """" No gene sets had estimated 5th percentile BMD values <0.333 ppm[ with
    the exception of …]." — "" when no study states its doses."""
    lles = [x for x in report.lle.values() if x is not None]
    if not lles:
        return ""
    return (f" No {noun}s had estimated {what} values <{_lle_text(min(lles))} {unit}"
            f"{_exceptions(entries, rows_key, report, noun)}.")


def _gene_set_intro(sets: list[dict], report: _Report, unit: str, summary_table) -> list:
    values = _Values(sets[0], unit)
    stat = _STAT.get(values.stat, values.stat)
    tissues = _join([(e.get("organ") or "").strip().lower() for e in sets])
    first = (f"Chemical-induced alterations in {tissues} gene transcript expression were "
             f"examined to determine those gene sets most sensitive to {report.chemical} "
             f"exposure. To that end, BMD analysis of transcripts and gene sets (Gene Ontology "
             f"[GO] biological process) was conducted to determine the potency of the chemical "
             f"to elicit gene expression changes in the {tissues}. This analysis used "
             f"transcript-level BMD data to assess an aggregate score of gene set potency "
             f"({_SCORE.get(values.stat, stat)}) and enrichment.")
    where, span = _tables_phrase(sets)
    summary = (f", with a summary of the top gene set per tissue based on lowest BMD {stat} "
               f"provided in Table {summary_table}" if summary_table else "")
    below = _lle_sentence(sets, "gene_sets", report, "gene set", f"{stat} BMD", values.unit)
    second = (f"The “active” gene sets with the lowest {stat} BMD values are shown in "
              f"{where}{summary}.{below} The gene sets shown in {span} should be interpreted "
              f"with caution from the standpoint of the underlying biological mechanism and any "
              f"relationship to toxicity or toxic agents referenced in the GO term definitions. "
              f"The data primarily should be considered as a metric of potency for "
              f"chemical-induced transcriptional changes (i.e., a concerted biological change) "
              f"that could serve as a surrogate of estimated biological potency and, by "
              f"extension, toxicological potency when more definitive toxicological data are "
              f"unavailable.")
    return [units(first), units(second)]


def _gene_intro(genes: list[dict], report: _Report, unit: str) -> list:
    values = _Values(genes[0], unit)
    where, span = _tables_phrase(genes)
    below = _lle_sentence(genes, "top_genes", report, "gene", "median BMD", values.unit)
    return [units(
        f"The top 10 genes ranked by BMD potency are shown in {where}.{below} As with the GO "
        f"analysis, the biological or toxicological significance of the changes in gene "
        f"expression shown in {span} should be interpreted with caution. The data primarily "
        f"should be considered as a metric of potency for chemical-induced transcriptional "
        f"changes that could serve as a conservative surrogate of estimated biological "
        f"potency, and by extension toxicological potency, when more definitive "
        f"toxicological data are unavailable.")]


def _gene_set_summary(sets: list[dict], report: _Report, unit: str, summary_table) -> list:
    groups: dict[tuple, tuple] = {}
    for e in sets:
        organ = (e.get("organ") or "").strip().lower()
        values = _Values(e, unit)
        for b in _blocks(e):
            key = b.get("study") or ""
            top = _reliable(b.get("gene_sets"), report.lle.get(key))
            if top and ((key, b.get("sex")) not in groups
                        or _num(top[0]["bmd"]) < _num(groups[(key, b.get("sex"))][1]["bmd"])):
                groups[(key, b.get("sex"))] = (organ, top[0], values)
    if not groups:
        return []
    order = {key: i for i, (key, _, _) in enumerate(report.studies)}
    found = sorted(groups.items(), key=lambda kv: order.get(kv[0][0], 0))
    sentences = [f"A summary of the most potent gene set per tissue is provided in Table "
                 f"{summary_table}."] if summary_table else []
    organs = {organ for _, (organ, _, _) in found}
    if len(found) == 2 and len(organs) == 1:
        # The same tissue in both groups (NIEHS-12: the liver in rats and mice).
        (k1, l1), (o, r1, v) = found[0]
        (k2, l2), (_, r2, _) = found[1]
        stat = _STAT.get(v.stat, v.stat)
        sentences.append(
            f"In both {report.group_noun(k1, l1)} and {report.group_noun(k2, l2)} "
            f"{report.verb} {report.chemical}, the {o} had the gene set with the lowest BMD "
            f"{stat} value, corresponding to {r1.get('go_term', '')} ({r1.get('go_id', '')}) "
            f"and {r2.get('go_term', '')} ({r2.get('go_id', '')}), respectively. The BMDs "
            f"(BMD_Ls) were {v.pair(r1)} and {v.pair(r2)} {v.unit}, respectively.")
        return [units(" ".join(sentences))]
    for i, ((key, label), (organ, row, values)) in enumerate(found):
        who = report.group_noun(key, label)
        if i == 0:
            who = f"{who} {report.verb} {report.chemical}"
        stat = _STAT.get(values.stat, values.stat)
        sentences.append(
            f"In {who}, the {organ} had the gene set with the lowest BMD {stat} value, "
            f"corresponding to {row.get('go_term', '')} ({row.get('go_id', '')}) with a BMD "
            f"(BMD_L) of {values.pair(row)} {values.unit}.")
    return [units(" ".join(sentences))]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

SUPPLEMENTAL_APPENDIX = "appendix-f"            # the Supplemental Data appendix's node
SUMMARY_TABLE = "table-most-potent-gene-sets"   # the most potent gene set per tissue


def attach_genomics_results(data: dict, tree) -> None:
    """Write the books' gene set and gene results into ``data`` (module
    docstring) from its numbered genomic tables; ``tree`` is the report's
    numbered document tree (the appendix and summary table it cites)."""
    from document_model.document_tree import find_node
    entries = data.get("genomics_sections") or []
    sets = [e for e in entries if e.get("type") == "gene_set"]
    genes = [e for e in entries if e.get("type") == "gene"]
    if not (sets or genes):
        return
    report = _Report(data)
    unit = data.get("dose_unit") or "mg/kg"
    appendix_node = find_node(SUPPLEMENTAL_APPENDIX, tree) if tree else None
    appendix = getattr(appendix_node, "appendix_letter", None)
    table_node = find_node(SUMMARY_TABLE, tree) if tree else None
    summary_table = getattr(table_node, "table_label", None) or getattr(
        table_node, "table_number", None)
    from genomics.gene_names import gene_names
    names = gene_names(g.get("entrez_id") for e in genes for b in _blocks(e)
                       for g in b.get("top_genes") or [])
    for e in sets:
        _gene_set_results(e, report, unit, appendix)
    for e in genes:
        _gene_results(e, report, unit, names)
    if sets:
        data["gene_set_intro"] = {"paragraphs": _gene_set_intro(sets, report, unit, summary_table)}
        data["gene_set_summary"] = {"paragraphs": _gene_set_summary(sets, report, unit,
                                                                    summary_table)}
    if genes:
        data["gene_intro"] = {"paragraphs": _gene_intro(genes, report, unit)}
