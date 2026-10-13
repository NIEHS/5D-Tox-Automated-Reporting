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

The rules are the books' (here); their words are the document definition's
``phrasing:`` block (document_model.phrasing; eras/niehs-2026), each sentence
a template whose fields these rules fill:

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

What a definition prints is its choice: the 2026 era binds these keys and
states their wording (eras/niehs-2026.yaml); the per-tissue results reach a
tissue's section through render_common.node_data (``gene_set_results`` /
``gene_results``).  The appendix and table they cite are the nodes the
definition declares ``cited_as`` (supplemental-data, gene-set-summary-table).
Paragraphs are inline-unit lists (render_common's inline model).
"""

from __future__ import annotations

import math
import re

from document_model.phrasing import Phrasing
from rendering.render_common import make_italic, make_sub
from tables.table_builder_common import format_display_number

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
    precision, the chemical — and the definition's words for them."""

    def __init__(self, data: dict, phrasing: Phrasing):
        from pipeline.study_design import design_or_standard, exposure_verb, species_plural
        self.data = data
        self.p = phrasing
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

    def exposed(self, animals: str) -> str:
        """"rats exposed to 1,4-DCB"."""
        return self.p.say("animals.exposed", animals=animals, exposed=self.verb,
                          chemical=self.chemical)

    def in_group(self, animals: str, sentence: str) -> str:
        """"In female rats, the most sensitive …"."""
        return self.p.say("animals.in_group", animals=animals, sentence=_lower_first(sentence))

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
    def __init__(self, entry: dict, unit: str, phrasing: Phrasing):
        d = _display(entry)
        self.p = phrasing
        self.dec = d.get("decimals", 3)
        self.unit = d.get("unit") or unit
        self.stat = d.get("stat", "median")

    def statistic(self, stat: str | None = None) -> str:
        """"5th percentile" — the ranking statistic as the prose names it."""
        stat = stat or self.stat
        return self.p.word("statistic", stat, default=stat)

    def measure(self, statistic: str = "", plural: bool = False) -> str:
        """"5th percentile BMD", "BMDs"."""
        return f"{statistic} {self.p.noun('bmd', 2 if plural else 1)}".strip()

    def one(self, v) -> str:
        return (format_display_number(v, self.dec) if _num(v) is not None
                else self.p.say("values.not_calculated"))

    def pair(self, row: dict) -> str:
        return self.p.say("values.pair", bmd=self.one(row.get("bmd")),
                          bmdl=self.one(row.get("bmdl")))

    def clause(self, rows: list[dict], statistic: str) -> str:
        """" with 5th percentile BMDs (BMD_Ls) of a (b) and c (d) ppm,
        respectively", or ", both with a 5th percentile BMD (BMD_L) of a (b) ppm"."""
        pairs = [self.pair(r) for r in rows]
        if len(set(pairs)) == 1 and self.p.has_word("all_of", len(pairs)):
            return self.p.say("values.same", all=self.p.word("all_of", len(pairs)),
                              measure=self.measure(statistic), pair=pairs[0], unit=self.unit)
        return self.p.say("values.each", measures=self.measure(statistic, plural=True),
                          pairs=_join(pairs), unit=self.unit)


def _reliable(rows: list[dict], lle: float | None) -> list[dict]:
    out = [r for r in rows or [] if _num(r.get("bmd")) is not None
           and (lle is None or _num(r.get("bmd")) >= lle)]
    return sorted(out, key=lambda r: _num(r.get("bmd")))


def _below(rows: list[dict], lle: float | None) -> list[dict]:
    if lle is None:
        return []
    return [r for r in rows or [] if (b := _num(r.get("bmd"))) is not None and b < lle]


def _term(row: dict, p: Phrasing) -> str:
    return p.say("term", go_term=row.get("go_term", ""), go_id=row.get("go_id", ""))


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
    p, stat = values.p, values.statistic()
    if len(sets) == 1:
        return p.say("gene_sets.one", term=_term(sets[0], p), measure=values.measure(stat),
                     pair=values.pair(sets[0]), unit=values.unit, table=table)
    return p.say("gene_sets.several", terms=_join([_term(s, p) for s in sets]),
                 values=values.clause(sets, stat), table=table)


def _table_cite(entry: dict, p: Phrasing) -> str:
    n = entry.get("table_number")
    return p.say("tables.cite", number=n) if n else ""


def _gene_set_results(entry: dict, report: _Report, unit: str, appendix: str | None) -> None:
    p = report.p
    values = _Values(entry, unit, p)
    table = _table_cite(entry, p)
    results: dict[str, list] = {}
    with_sets: list[str] = []
    for key, _, _ in report.studies:
        sentences = []
        for b in [b for b in _blocks(entry) if (b.get("study") or "") == key]:
            noun = report.group_noun(key, b.get("sex"))
            sets = _reliable(b.get("gene_sets"), report.lle.get(key))
            if not sets:
                sentences.append(p.say("gene_sets.none", animals=report.exposed(noun)))
                continue
            if key not in with_sets:
                with_sets.append(key)
            sentence = _gene_set_sentence(_top_gene_sets(sets, values), values, table)
            if report.several_groups(key):
                sentence = report.in_group(noun, sentence)
            sentences.append(sentence)
        if sentences:
            results[key] = sentences
    if with_sets and appendix:
        results[with_sets[-1]].append(p.say(
            "gene_sets.full_list", organ=(entry.get("organ") or "").strip().lower(),
            animals=report.subjects(with_sets), appendix=appendix))
    entry["results"] = {k: [units(" ".join(v))] for k, v in results.items()}


# ---------------------------------------------------------------------------
# Gene results, per tissue and study
# ---------------------------------------------------------------------------

def _gene(row: dict, names: dict, p: Phrasing) -> str:
    return p.say("gene", symbol=str(row.get("gene") or row.get("gene_symbol") or ""),
                 name=names.get(str(row.get("entrez_id") or "")) or GENE_NAME_PENDING)


def _genes(genes: list[dict], names: dict, p: Phrasing) -> str:
    return _join([_gene(g, names, p) for g in genes])


def _gene_block(genes: list[dict], organ: str, noun: str, lle: float | None,
                values: _Values, names: dict) -> tuple[list[str], bool]:
    """One group's gene results (the books' patterns, module docstring), and
    whether its first sentence names the group's animals itself."""
    p = values.p
    if not genes:
        return [p.say("genes.none", organ=organ, animals=noun)], True
    out: list[str] = []
    below = _below(genes, lle)
    calc = [g for g in genes if g not in below]
    if below:
        dirs = {str(g.get("direction", "")).lower() for g in below}
        exhibiting = (p.say("genes.exhibiting_up" if dirs == {"up"} else "genes.exhibiting_down")
                      if len(dirs) == 1 else "")
        out.append(p.say("genes.below_many" if len(below) > 1 else "genes.below_one",
                         organ=organ, animals=noun, exhibiting=exhibiting,
                         genes=_genes(below, names, p), lle=_lle_text(lle), unit=values.unit))
    few = len(genes) < 10
    if few:
        out.append(p.say("genes.few", count=p.number(len(genes))))
    up = [g for g in calc if str(g.get("direction", "")).lower() == "up"]
    down = [g for g in calc if str(g.get("direction", "")).lower() == "down"]
    body: list[str] = []
    if not below and up and down and len(up) == len(down) and len(genes) == 10:
        body.append(p.say("genes.half", count=len(genes), organ=organ))
        body.append(p.say("genes.half_up", genes=_genes(up, names, p),
                          values=values.clause(up, "")))
        body.append(p.say("genes.half_down", genes=_genes(down, names, p),
                          values=values.clause(down, "")))
    elif not below and calc and not (up and down) and len(calc) > 1:
        body.append(p.say("genes.all_one_way", count=len(calc), organ=organ,
                          direction=p.word("direction", "up" if up else "down")))
        body.append(p.say("genes.all_list", genes=_genes(calc, names, p),
                          values=values.clause(calc, "")))
    else:
        for group, direction in ((up, "up"), (down, "down")):
            if len(group) == 1:
                body.append(p.say("genes.one", gene=_gene(group[0], names, p),
                                  direction=p.word("direction", direction),
                                  pair=values.pair(group[0]), unit=values.unit))
            elif group:
                body.append(p.say(f"genes.most_{direction}", genes=_genes(group, names, p),
                                  values=values.clause(group, "")))
    if few and body:
        body[0] = p.say("genes.few_lead", count=p.number(len(genes)),
                        sentence=_lower_first(body[0]))
    return out + body, bool(below)


def _gene_results(entry: dict, report: _Report, unit: str, names: dict) -> None:
    values = _Values(entry, unit, report.p)
    organ = (entry.get("organ") or "").strip().lower()
    results: dict[str, list] = {}
    for key, _, _ in report.studies:
        sentences = []
        for b in [b for b in _blocks(entry) if (b.get("study") or "") == key]:
            noun = report.group_noun(key, b.get("sex"))
            block, names_animals = _gene_block(b.get("top_genes") or [], organ, noun,
                                               report.lle.get(key), values, names)
            if report.several_groups(key) and block and not names_animals:
                block[0] = report.in_group(noun, block[0])
            sentences += block
        if sentences:
            results[key] = [units(" ".join(sentences))]
    entry["results"] = results


# ---------------------------------------------------------------------------
# The sections' openings and the gene set summary
# ---------------------------------------------------------------------------

def _tables_phrase(entries: list[dict], p: Phrasing) -> tuple[str, str]:
    """("the heart (Table 7), kidney (Table 8), …", "Table 7 to Table 11")."""
    shown = [((e.get("organ") or "").strip().lower(), e.get("table_number")) for e in entries]
    where = p.say("tables.where", tissues=_join(
        [p.say("tables.tissue", organ=o, number=n) if n else o for o, n in shown]))
    numbers = [n for _, n in shown if n]
    if not numbers:
        span = p.say("tables.span_none")
    elif len(numbers) == 1:
        span = p.say("tables.span_one", first=numbers[0])
    elif len(numbers) == 2:
        span = p.say("tables.span_two", first=numbers[0], last=numbers[1])
    else:
        span = p.say("tables.span_many", first=numbers[0], last=numbers[-1])
    return where, span


def _exceptions(entries: list[dict], rows_key: str, report: _Report, noun: str) -> str:
    """" with the exception of one lung gene in mice" — the items below the
    lower limit of extrapolation, by tissue and group; "" when none."""
    p = report.p
    found = []
    for e in entries:
        organ = (e.get("organ") or "").strip().lower()
        for b in _blocks(e):
            key = b.get("study") or ""
            n = len(_below(b.get(rows_key), report.lle.get(key)))
            if n:
                found.append(p.say("limit.exception", count=p.number(n), organ=organ,
                                   noun=p.noun(noun, n),
                                   animals=report.group_noun(key, b.get("sex"))))
    return p.say("limit.exceptions", items=_join(found)) if found else ""


def _lle_sentence(entries, rows_key, report, noun: str, measure: str, unit: str) -> str:
    """" No gene sets had estimated 5th percentile BMD values <0.333 ppm[ with
    the exception of …]." — "" when no study states its doses.  ``noun``: the
    words key of what is counted (gene_set, gene)."""
    lles = [x for x in report.lle.values() if x is not None]
    if not lles:
        return ""
    return report.p.say("limit.below", nouns=report.p.noun(noun, 2), measure=measure,
                        lle=_lle_text(min(lles)), unit=unit,
                        exceptions=_exceptions(entries, rows_key, report, noun))


def _gene_set_intro(sets: list[dict], report: _Report, unit: str, summary_table) -> list:
    p = report.p
    values = _Values(sets[0], unit, p)
    stat = values.statistic()
    tissues = _join([(e.get("organ") or "").strip().lower() for e in sets])
    first = p.say("gene_sets.intro_examined", tissues=tissues, chemical=report.chemical,
                  score=p.word("score", values.stat, default=stat))
    where, span = _tables_phrase(sets, p)
    summary = (p.say("gene_sets.intro_summary", statistic=stat, table=summary_table)
               if summary_table else "")
    below = _lle_sentence(sets, "gene_sets", report, "gene_set", values.measure(stat),
                          values.unit)
    second = p.say("gene_sets.intro_shown", statistic=stat, where=where, summary=summary,
                   below=below, span=span)
    return [units(first), units(second)]


def _gene_intro(genes: list[dict], report: _Report, unit: str) -> list:
    values = _Values(genes[0], unit, report.p)
    where, span = _tables_phrase(genes, report.p)
    # A gene's BMD is the median of its probes' (the gene tables' rule).
    below = _lle_sentence(genes, "top_genes", report, "gene",
                          values.measure(values.statistic("median")), values.unit)
    return [units(report.p.say("genes.intro", where=where, below=below, span=span))]


def _gene_set_summary(sets: list[dict], report: _Report, unit: str, summary_table) -> list:
    p = report.p
    groups: dict[tuple, tuple] = {}
    for e in sets:
        organ = (e.get("organ") or "").strip().lower()
        values = _Values(e, unit, p)
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
    sentences = [p.say("gene_sets.summary_lead", table=summary_table)] if summary_table else []
    organs = {organ for _, (organ, _, _) in found}
    if len(found) == 2 and len(organs) == 1:
        # The same tissue in both groups (NIEHS-12: the liver in rats and mice).
        (k1, l1), (o, r1, v) = found[0]
        (k2, l2), (_, r2, _) = found[1]
        sentences.append(p.say(
            "gene_sets.summary_both", first=report.group_noun(k1, l1),
            second=report.group_noun(k2, l2), exposed=report.verb, chemical=report.chemical,
            organ=o, statistic=v.statistic(), term1=_term(r1, p), term2=_term(r2, p),
            pair1=v.pair(r1), pair2=v.pair(r2), unit=v.unit))
        return [units(" ".join(sentences))]
    for i, ((key, label), (organ, row, values)) in enumerate(found):
        who = report.group_noun(key, label)
        if i == 0:
            who = report.exposed(who)
        sentences.append(p.say(
            "gene_sets.summary_each", animals=who, organ=organ, statistic=values.statistic(),
            term=_term(row, p), pair=values.pair(row), unit=values.unit))
    return [units(" ".join(sentences))]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def cited(tree, name: str, attribute: str):
    """The number or letter of the node the definition declares ``cited_as:
    name`` (document_tree.find_cited); None when it declares none."""
    from document_model.document_tree import find_cited
    node = find_cited(name, tree)
    if node is None:
        return None
    if attribute == "table":
        return node.table_label or node.table_number
    return node.appendix_letter


def attach_genomics_results(data: dict, tree, phrasing: Phrasing) -> None:
    """Write the books' gene set and gene results into ``data`` (module
    docstring) from its numbered genomic tables, worded by the definition's
    ``phrasing``; ``tree`` is the report's numbered document tree (the
    appendix and summary table its nodes declare cited).  Nothing when the
    definition declares no phrasing (it binds none of these keys)."""
    entries = data.get("genomics_sections") or []
    sets = [e for e in entries if e.get("type") == "gene_set"]
    genes = [e for e in entries if e.get("type") == "gene"]
    if not phrasing or not (sets or genes):
        return
    report = _Report(data, phrasing)
    unit = data.get("dose_unit") or "mg/kg"
    appendix = cited(tree, "supplemental-data", "appendix")
    summary_table = cited(tree, "gene-set-summary-table", "table")
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
