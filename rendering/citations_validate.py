"""
rendering/citations_validate.py — the citation check: an act on a report as it
is presented, with a record (ADR-0038).

``validate(dtxsid)`` reads the report the way a reader gets it (the tree of
the view, the text as printed) and answers:

  * does every citation in the printed text name a recorded source?
  * is every listed source cited, each listed once?  (By construction for a
    report whose citations are tracked: rendering.citations derives the list
    from the printed citations.  Checked as printed for a report whose text
    and list arrive numbered: a published book kept as a session.)
  * is each cited source's entry complete?
  * is its DOI registered; does its address answer?  (narrative.source_lookup)
  * did a person type a citation as a bare number, which no record ties to a
    source?
  * which recorded sources does nothing printed cite, and is that because the
    text that cites them is not part of this report, or because no text does?
  * which citations did a writer make that named none of the sources offered
    to it?

Findings are ``error`` (the report is not to be published with it),
``warning`` (a check that could not be made, or a thing to look at) or
``note``.  The check passes when it has no error.

The record (``citations_check.json`` in the report's session) says when, by
whom, on which state of the report (``content_fingerprint``), what was found,
and what the check does not judge.  Whether a record still holds is derived,
never stored: ``status`` compares the fingerprint with the report as it
stands, so any change after the check shows it out of date.  The publish gate
(workflow.engine.publish_readiness) waits for a check that holds and passed.
"""

from __future__ import annotations

import hashlib
import html as _html
import json
import re
from pathlib import Path

from narrative.sources import (
    RUN_RE, TOKEN_RE, format_entry, is_unknown, missing_fields, normalize_doi,
)

RECORD_FILE = "citations_check.json"

ERROR, WARNING, NOTE = "error", "warning", "note"

NOT_CHECKED, OUT_OF_DATE, FAILED, PASSED = "not_checked", "out_of_date", "failed", "passed"

# Said with every record: what a passed check does not mean.
NOT_JUDGED = (
    "Whether a source supports the sentence that cites it. That is a question of meaning.",
    "Whether a sentence that cites nothing should cite a source.",
    "Whether a registered DOI belongs to the work its entry describes.",
    "A Word file edited outside the application: the check reads the report as the "
    "application presents it.",
)

_MARKER = "ZZREFERENCELISTZZ"
_SHOWN = 5                      # sentences, numbers or names shown per finding
_SENTENCES_KEPT = 40            # sentences kept per source in the record
# A citation typed as a number: "[3]", "[1, 4]", "[2-4]" standing free in the
# text — not part of a chemical name ("dibenzo[b,e][1,4]dioxin").
_TYPED = re.compile(r"(?<![\w\]\[])\[(\d{1,3}(?:\s*[,\-–]\s*\d{1,3})*)\](?![\w\[])")
_LEADING = re.compile(r"^\s*(?:\[(\d+)\]|(\d+)[.)])\s*")
_DOI_IN_TEXT = re.compile(r"10\.\d{4,9}/[^\s\"<>]+")
_URL_IN_TEXT = re.compile(r"https?://[^\s\"<>]+")
_PENDING = "Citation pending"


def _finding(severity: str, code: str, message: str, **more) -> dict:
    return {"severity": severity, "code": code, "message": message,
            **{k: v for k, v in more.items() if v not in (None, [], "")}}


_BLOCK_END = re.compile(r"</(?:p|h[1-6]|li|td|th|tr|div|caption|figcaption|section|title)>|<br\s*/?>",
                        re.IGNORECASE)


def _plain(markup: str) -> str:
    """The text of a rendered report, one line per block (paragraph, heading,
    cell), so a sentence never runs on into the heading before it."""
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", markup, flags=re.DOTALL | re.IGNORECASE)
    text = _BLOCK_END.sub("\x00", text)
    text = _html.unescape(re.sub(r"<[^>]+>", " ", text))
    lines = (" ".join(line.split()) for line in text.split("\x00"))
    return "\n".join(line for line in lines if line)


def _around(text: str, start: int, end: int, reach: int = 240) -> str:
    """The sentence around a place in the text (cut at the block's ends and
    at sentence ends, and at ``reach`` characters either side)."""
    a, b = max(0, start - reach), min(len(text), end + reach)
    before, after = text[a:start], text[end:b]
    before = before[before.rfind("\n") + 1:]
    cut = max(before.rfind(". "), before.rfind("? "))
    if cut >= 0:
        before = before[cut + 2:]
    stops = [i for i in (after.find("\n"), after.find(". ") + 1 if ". " in after else -1) if i >= 0]
    if stops:
        after = after[:min(stops)]
    return (before + text[start:end] + after).strip()


def _sentence(text: str) -> str:
    """A sentence as shown in a finding: its citation tokens out."""
    return re.sub(r"\s+([.,;:])", r"\1", " ".join(TOKEN_RE.sub("", text).split()))


def _numbers(inner: str) -> list[int]:
    from narrative.sources import _numbers as numbers
    return numbers(inner)


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else many or one + 's'}"


# ---------------------------------------------------------------------------
# The examination
# ---------------------------------------------------------------------------

def examine(data: dict, tree=None, *, doi_state=None, url_state=None,
            known_doi_state=None) -> dict:
    """What the check finds in a report's data, presented with ``tree``.

    ``doi_state(doi)`` / ``url_state(url)`` ask the outside world
    (narrative.source_lookup.check_doi / check_url); None = nothing is asked
    and each such check is reported as not made.  ``known_doi_state(doi)``
    answers for the papers of a knowledge base from what is on file.
    """
    from rendering.citations import _PROBE, numbered
    from rendering.html_generator import generate_html

    probe = generate_html({**data, _PROBE: True, "references": {"paragraphs": [_MARKER]},
                           "_override_stale": []}, tree=tree)
    text = _plain(probe)
    list_printed = _MARKER in text
    body = text.replace(_MARKER, " ")
    tracked = bool(data.get("sources")) or bool(TOKEN_RE.search(body))

    if tracked:
        findings, references, shape = _examine_tracked(
            data, tree, body, list_printed, numbered, generate_html,
            doi_state, url_state, known_doi_state)
    else:
        findings, references, shape = _examine_as_printed(data, body, list_printed)

    # Two writers, two shapes: the Background's issues name one token and its
    # sentence; an interpretation's name a stratum, its tokens and sentences.
    for issue in data.get("citation_warnings") or []:
        tokens = issue.get("tokens") or ([issue["token"]] if issue.get("token") else [])
        tokens = [t if str(t).startswith("[") else f"[{t}]" for t in tokens]
        where = ", ".join(str(x) for x in (
            issue.get("study"), issue.get("where"), issue.get("organ"), issue.get("sex"),
            {"gene_set": "gene sets", "gene": "genes"}.get(issue.get("kind"))) if x)
        sentences = issue.get("sentences") or ([issue["sentence"]] if issue.get("sentence") else [])
        findings.append(_finding(
            WARNING, "writer_citation_dropped",
            f"A writer cited {', '.join(tokens) or 'a source'}, which "
            f"{'is' if len(tokens) <= 1 else 'are'} none of the sources offered to it"
            f"{(' (' + where + ')') if where else ''}. The citation is not printed; "
            "the sentence stands without it.",
            sentences=sentences[:_SHOWN]))

    order = {ERROR: 0, WARNING: 1, NOTE: 2}
    findings.sort(key=lambda f: order[f["severity"]])
    counts = {
        "citations": shape["citations"], "cited_sources": len(references),
        "listed": shape["listed"], "recorded_sources": shape["recorded"],
        "errors": sum(f["severity"] == ERROR for f in findings),
        "warnings": sum(f["severity"] == WARNING for f in findings),
        "notes": sum(f["severity"] == NOTE for f in findings),
    }
    printed = json.dumps([shape["runs"], [r["entry"] for r in references]], ensure_ascii=False)
    return {
        "tracked": tracked, "passed": counts["errors"] == 0, "counts": counts,
        "findings": findings, "references": references, "not_listed": shape["not_listed"],
        "print_fingerprint": hashlib.sha256(printed.encode("utf-8")).hexdigest()[:32],
        "not_judged": list(NOT_JUDGED),
    }


def _examine_tracked(data, tree, body, list_printed, numbered, generate_html,
                     doi_state, url_state, known_doi_state):
    findings: list[dict] = []
    done = numbered(data, tree)
    cites = done.get("citations") or {"order": [], "numbers": {}, "unknown": [], "not_cited": []}
    sources = done.get("sources") or {}
    numbers = cites["numbers"]

    # Where each source is cited, as printed.
    where: dict[str, list[str]] = {}
    runs: list[list[str]] = []
    for m in RUN_RE.finditer(body):
        slugs = list(dict.fromkeys(TOKEN_RE.findall(m.group(0))))
        runs.append(slugs)
        sentence = _sentence(_around(body, m.start(), m.end()))
        for slug in slugs:
            where.setdefault(slug, []).append(sentence)

    for slug in cites["unknown"]:
        named = (f"number {slug.split('-', 1)[1]}, which its writer's list does not have"
                 if is_unknown(slug) else f"“{slug}”, which is not a recorded source")
        findings.append(_finding(
            ERROR, "no_source",
            f"The text cites {named}. Nothing can be listed for it; the report prints "
            "“Citation pending” in its place.",
            slug=slug, sentences=where.get(slug, [])[:_SHOWN]))

    typed = [(m.group(0), _sentence(_around(body, m.start(), m.end())))
             for m in _TYPED.finditer(body)]
    if typed:
        findings.append(_finding(
            ERROR, "typed_number",
            f"{_plural(len(typed), 'citation is', 'citations are')} typed as a number "
            f"({', '.join(dict.fromkeys(t for t, _ in typed[:_SHOWN]))}"
            f"{', …' if len(typed) > _SHOWN else ''}). No record ties a typed number to a "
            "source, and the numbers of the list change with what the report prints. Cite the "
            "source by its record instead.",
            sentences=[s for _, s in typed[:_SHOWN]]))

    if cites["order"] and not list_printed:
        findings.append(_finding(
            ERROR, "list_not_printed",
            f"The text cites {_plural(len(cites['order']), 'source')}, and this report's "
            "definition prints no reference list."))

    references = []
    for slug in cites["order"]:
        source = sources[slug]
        origin = (source.get("origin") or {}).get("from") or "unknown"
        entry = {"number": numbers[slug], **_describe(slug, source),
                 "cited": len(where.get(slug, [])),
                 "sentences": list(dict.fromkeys(where.get(slug, [])))[:_SENTENCES_KEPT]}
        label = f"[{numbers[slug]}] {str(source.get('title') or source.get('text') or slug).rstrip('.')}"
        missing = missing_fields(source)
        if missing:
            entry["missing"] = missing
            findings.append(_finding(
                ERROR, "entry_incomplete",
                f"The entry of {label} lacks: {', '.join(missing)}.", slug=slug))
        doi = normalize_doi(source.get("doi"))
        url = (source.get("url") or "").strip()
        if doi:
            if origin == "knowledge_base":
                state = known_doi_state(doi) if known_doi_state else "not_checked"
                advice = ("The DOIs of a knowledge base are checked for the knowledge base as a "
                          "whole (tooling/citations.py kb-dois), never for the papers one study "
                          "cites.")
            else:
                state = doi_state(doi) if doi_state else "not_checked"
                advice = "The DOI system was not asked, or did not answer."
            entry["doi_state"] = state
            if state == "not_registered":
                findings.append(_finding(
                    ERROR, "doi_not_registered",
                    f"The DOI of {label} ({doi}) is not registered with the DOI system.",
                    slug=slug))
            elif state != "registered":
                findings.append(_finding(
                    WARNING, "doi_not_checked",
                    f"The DOI of {label} ({doi}) was not checked against the DOI system. "
                    f"{advice}", slug=slug))
        elif url:
            state = url_state(url) if url_state else "not_checked"
            entry["address_state"] = state
            if state == "not_found":
                findings.append(_finding(
                    ERROR, "address_not_found",
                    f"The address of {label} answers “not found”: {url}", slug=slug))
            elif state in ("not_reached", "not_checked"):
                findings.append(_finding(
                    WARNING, "address_not_checked",
                    f"The address of {label} could not be reached from this machine, so it "
                    f"was not checked: {url}", slug=slug))
            elif state == "refuses":
                findings.append(_finding(
                    NOTE, "address_refuses",
                    f"The address of {label} exists and turns a program away; a person can "
                    f"open it: {url}", slug=slug))
        references.append(entry)

    # The report as it will be read: no citation may be left unnumbered.
    final = _plain(generate_html(done, tree=tree))
    left = len(TOKEN_RE.findall(final))
    pending = final.count(_PENDING) - sum(len(where.get(s, [])) for s in cites["unknown"])
    if left or pending > 0:
        findings.append(_finding(
            ERROR, "citation_not_numbered",
            f"{_plural(left + max(pending, 0), 'citation')} in the printed report did not get "
            "a number."))

    # Recorded and not listed: the text that cites it is not printed here, or
    # no text cites it at all.
    in_text = set(TOKEN_RE.findall(json.dumps(_strings(data), ensure_ascii=False)))
    idle = [s for s in cites["not_cited"]]
    unprinted = [s for s in idle if s in in_text]
    uncited = [s for s in idle if s not in in_text]
    if unprinted:
        findings.append(_finding(
            NOTE, "cited_by_unprinted_text",
            f"{_plural(len(unprinted), 'recorded source is', 'recorded sources are')} cited only "
            "by text this report does not print (its definition leaves that text out), so "
            f"{'it is' if len(unprinted) == 1 else 'they are'} not listed. "
            f"By origin: {_by_origin(sources, unprinted)}.",
            slugs=unprinted))
    if uncited:
        findings.append(_finding(
            NOTE, "recorded_not_cited",
            f"{_plural(len(uncited), 'recorded source is', 'recorded sources are')} cited by no "
            f"text, so {'it is' if len(uncited) == 1 else 'they are'} not listed. "
            f"By origin: {_by_origin(sources, uncited)}.",
            slugs=uncited))

    shape = {"citations": len(runs), "listed": len(references) if list_printed else 0,
             "recorded": len(sources), "runs": runs,
             "not_listed": [{**_describe(s, sources[s]),
                             "reason": "unprinted_text" if s in in_text else "not_cited"}
                            for s in idle]}
    return findings, references, shape


def _describe(slug: str, source: dict) -> dict:
    """A source as the record keeps it: its entry as printed, and the parts
    a page shows beside it."""
    origin = source.get("origin") or {}
    out = {"slug": slug, "kind": source.get("kind") or "other",
           "origin": origin.get("from") or "unknown", "entry": format_entry(source)}
    for key in ("title", "text", "container", "year", "doi", "url", "genes"):
        if source.get(key) not in (None, "", []):
            out[key] = source[key]
    for key in ("knowledge_base", "paper_id", "added_by"):
        if origin.get(key):
            out[key] = origin[key]
    return out


def _examine_as_printed(data, body, list_printed):
    """A report whose text and list arrive numbered (no source records): the
    numbers the text cites against the entries the list has."""
    findings = [_finding(
        NOTE, "not_tracked",
        "This report's citations are not tracked as records: its text and its reference list "
        "are numbered as given. The check compares the numbers the text cites with the "
        "entries the list has.")]
    given = data.get("references") or []
    lines = [line for line in (_flat(p) for p in (
        given.get("paragraphs") or [] if isinstance(given, dict) else given)) if line.strip()]
    listed: dict[int, str] = {}
    for i, line in enumerate(lines, start=1):
        m = _LEADING.match(line)
        listed[int(m.group(1) or m.group(2)) if m else i] = line

    cited: dict[int, list[str]] = {}
    runs: list[list[str]] = []
    for m in _TYPED.finditer(body):
        ns = _numbers(m.group(1))
        runs.append([str(n) for n in ns])
        for n in ns:
            cited.setdefault(n, []).append(_around(body, m.start(), m.end()))

    if lines and not list_printed:
        findings.append(_finding(
            WARNING, "list_not_printed",
            f"The report has {_plural(len(lines), 'reference')} and its definition prints no "
            "reference list."))
    if lines and not cited:
        findings.append(_finding(
            WARNING, "citations_not_recognized",
            f"The list has {_plural(len(lines), 'entry', 'entries')} and the text has no "
            "citation written as a bracketed number (a book as given may cite by superscript "
            "or by author and year), so the list was not compared with the text."))
    else:
        missing = sorted(n for n in cited if n not in listed)
        if missing:
            findings.append(_finding(
                ERROR, "number_without_entry",
                f"The text cites {_plural(len(missing), 'number')} the list does not have: "
                f"{', '.join(str(n) for n in missing[:20])}{', …' if len(missing) > 20 else ''}.",
                sentences=[cited[n][0] for n in missing[:_SHOWN]]))
        idle = sorted(n for n in listed if n not in cited)
        if idle:
            findings.append(_finding(
                ERROR, "entry_not_cited",
                f"{_plural(len(idle), 'entry', 'entries')} of the list "
                f"{'is' if len(idle) == 1 else 'are'} cited nowhere in the printed text: "
                f"{_ranges(idle)}. The list has {len(listed)}; the text cites "
                f"{len(set(cited) & set(listed))}."))

    seen: dict[str, int] = {}
    twice: list[str] = []
    for n, line in sorted(listed.items()):
        m = _DOI_IN_TEXT.search(line) or _URL_IN_TEXT.search(line)
        key = (m.group(0).rstrip(".,;)").lower() if m else " ".join(_LEADING.sub("", line).lower().split()))
        if key in seen:
            twice.append(f"[{seen[key]}] and [{n}]")
        else:
            seen[key] = n
    if twice:
        findings.append(_finding(
            ERROR, "listed_twice",
            f"{_plural(len(twice), 'source is', 'sources are')} listed twice: "
            f"{', '.join(twice[:10])}{', …' if len(twice) > 10 else ''}."))

    references = [{"number": n, "slug": None, "kind": "other", "origin": "as given",
                   "entry": _LEADING.sub("", line).strip(), "cited": len(cited.get(n, [])),
                   "sentences": list(dict.fromkeys(cited.get(n, [])))[:_SENTENCES_KEPT]}
                  for n, line in sorted(listed.items())]
    shape = {"citations": len(runs), "listed": len(listed) if list_printed else 0,
             "recorded": 0, "runs": runs, "not_listed": []}
    return findings, references, shape


def _flat(paragraph) -> str:
    """A paragraph as plain text: a string, or inline content (strings and
    {"type": ..., "text": ...} parts, render_common's inline model)."""
    if isinstance(paragraph, str):
        return paragraph
    if isinstance(paragraph, dict):
        return str(paragraph.get("text") or "")
    if isinstance(paragraph, (list, tuple)):
        return "".join(_flat(part) for part in paragraph)
    return ""


def _strings(obj) -> list[str]:
    if isinstance(obj, str):
        return [obj] if "[[cite:" in obj else []
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in _strings(v)]
    if isinstance(obj, (list, tuple)):
        return [s for v in obj for s in _strings(v)]
    return []


_ORIGIN_WORDS = {
    "knowledge_base": "papers of the knowledge base", "background": "the Background's sources",
    "library": "the definitions' source library", "person": "added by a person",
}


def _by_origin(sources: dict, slugs: list[str]) -> str:
    counts: dict[str, int] = {}
    for slug in slugs:
        origin = ((sources.get(slug) or {}).get("origin") or {}).get("from") or "unknown"
        counts[origin] = counts.get(origin, 0) + 1
    return "; ".join(f"{_ORIGIN_WORDS.get(o, o)}, {n}" for o, n in sorted(counts.items()))


def _ranges(numbers: list[int]) -> str:
    out, start, last = [], None, None
    for n in numbers:
        if start is None:
            start = last = n
        elif n == last + 1:
            last = n
        else:
            out.append(f"{start}" if start == last else f"{start}–{last}")
            start = last = n
    if start is not None:
        out.append(f"{start}" if start == last else f"{start}–{last}")
    return ", ".join(out)


# ---------------------------------------------------------------------------
# The act and its record
# ---------------------------------------------------------------------------

def _session_dir(dtxsid: str) -> Path:
    from common.dtxsid import validate_dtxsid
    from common.paths import SESSIONS_DIR
    return Path(SESSIONS_DIR) / validate_dtxsid(dtxsid)


def validate(dtxsid: str, *, view: str | None = None, network: bool = True,
             checked_by: str | None = None, save: bool = True, inputs=None) -> dict:
    """Check the report's citations as it is presented and (``save``) record
    the result in its session.  ``network=False`` asks nothing of the outside
    world: every DOI and address check is then reported as not made."""
    from common.clock import now_iso
    from document_model.view_config import DEFAULT_VIEW
    from narrative import source_lookup
    from rendering.kept_render import content_fingerprint

    view = view or DEFAULT_VIEW
    # The state the check is made on is taken before the report is read, so a
    # change made while it runs shows the record out of date.
    fingerprint = content_fingerprint(dtxsid)
    if inputs is None:
        from rendering.preview_surface import _preview_inputs
        inputs = _preview_inputs(dtxsid, view)
    data, tree = inputs
    found = examine(
        data, tree,
        doi_state=source_lookup.check_doi if network else None,
        url_state=source_lookup.check_url if network else None,
        known_doi_state=source_lookup.known_doi)
    record = {"dtxsid": dtxsid, "view": view, "checked_at": now_iso(),
              "checked_by": checked_by, "network": bool(network),
              "content_fingerprint": fingerprint, **found}
    if save:
        path = _session_dir(dtxsid) / RECORD_FILE
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return record


def read_record(dtxsid: str) -> dict | None:
    try:
        blob = json.loads((_session_dir(dtxsid) / RECORD_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return blob if isinstance(blob, dict) else None


def status(dtxsid: str, record: dict | None | bool = False) -> dict:
    """Where the report's citation check stands, derived: ``not_checked``,
    ``out_of_date`` (the report changed after the check), ``failed`` (the
    check that holds found errors) or ``passed``.  ``record``: the record when
    the caller has read it (None = there is none)."""
    from rendering.kept_render import content_fingerprint

    if record is False:
        record = read_record(dtxsid)
    if not isinstance(record, dict):
        return {"state": NOT_CHECKED}
    out = {"checked_at": record.get("checked_at"), "checked_by": record.get("checked_by"),
           "counts": record.get("counts") or {}}
    if record.get("content_fingerprint") != content_fingerprint(dtxsid):
        return {"state": OUT_OF_DATE, **out}
    return {"state": PASSED if record.get("passed") else FAILED, **out}
