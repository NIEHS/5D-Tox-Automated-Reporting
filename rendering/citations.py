"""
rendering/citations.py — the citations a presented report prints, numbered, and
the reference list that follows from them (ADR-0038).

The report's data carries the sources it may cite (``data["sources"]``,
narrative.sources) and text that cites them by token (``[[cite:<slug>]]``).
Neither a number nor a reference list is stored.  They are derived here, for
the report as it is presented:

  * the report is rendered once to HTML with the tokens left in, which gives
    the citations in reading order for exactly the tree (the view) presented;
  * a source is numbered at its first citation;
  * the reference list holds the cited sources and no other, each once;
  * every token in the data is replaced by its number ("[3]", "[3, 7]").

So a source nothing printed cites is not listed, a paper two studies cite is
listed once, and a view that prints fewer sections has a shorter list.  It is
the rule table numbers follow (the document tree drives the structure).

Each surface calls ``numbered`` on entry; the result is marked, so a second
call (the probe itself, a generator calling another) changes nothing.  Data
with no sources and no token is returned as it is: the request-body path and
its fixtures, whose references arrive numbered, are untouched.
"""

from __future__ import annotations

from narrative.sources import RUN_RE, TOKEN_RE, format_entry, is_unknown, load_library

_DONE = "_citations_numbered"
_PROBE = "_citations_probe"
_SIDE_CHANNEL = "_override_stale"

# Printed in place of a citation that cannot be numbered; a strict build
# refuses a report that still has one (render_common.scan_pending_markers).
UNKNOWN_SOURCE = "[Citation pending: no source is recorded for this citation]"
NOT_NUMBERED = "[Citation pending: this citation was not numbered]"


def _has_token(obj) -> bool:
    if isinstance(obj, str):
        return "[[cite:" in obj
    if isinstance(obj, dict):
        return any(_has_token(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return any(_has_token(v) for v in obj)
    return False


def _rewrite(obj, sub):
    """``obj`` with ``sub`` applied to every string that cites; containers
    with nothing to change are returned as they are (no copy)."""
    if isinstance(obj, str):
        return sub(obj) if "[[cite:" in obj else obj
    if isinstance(obj, dict):
        changed, out = False, {}
        for key, value in obj.items():
            new = _rewrite(value, sub)
            changed = changed or new is not value
            out[key] = new
        return out if changed else obj
    if isinstance(obj, list):
        new = [_rewrite(v, sub) for v in obj]
        return new if any(a is not b for a, b in zip(new, obj)) else obj
    if isinstance(obj, tuple):
        new = tuple(_rewrite(v, sub) for v in obj)
        return new if any(a is not b for a, b in zip(new, obj)) else obj
    return obj


def printed_order(data: dict, tree=None) -> list[str]:
    """The slugs the presented report cites, in reading order, each once."""
    from rendering.html_generator import generate_html
    probe = {**data, _PROBE: True, "references": {"paragraphs": []}, _SIDE_CHANNEL: []}
    return list(dict.fromkeys(TOKEN_RE.findall(generate_html(probe, tree=tree))))


def numbered(data: dict, tree=None) -> dict:
    """The report's data with its citations numbered as the presented report
    prints them and ``data["references"]`` holding exactly the cited sources.

    Adds ``data["citations"]``::

        {"order": [slug, ...],             the cited sources, in order
         "numbers": {slug: n},
         "unknown": [slug, ...],            citations of no recorded source
         "not_cited": [slug, ...]}          recorded sources nothing printed cites
    """
    if not isinstance(data, dict) or data.get(_DONE) or data.get(_PROBE):
        return data
    sources = data.get("sources")
    if not sources and not _has_token(data):
        return data
    sources = dict(sources or {})

    order = printed_order(data, tree)
    # A boilerplate source is cited by its key in the definitions' library.
    library = load_library()
    for slug in order:
        if slug not in sources and slug in library:
            sources[slug] = library[slug]
    unknown = [s for s in order if is_unknown(s) or s not in sources]
    # One number per source: two records of one identity (a paper offered to
    # two studies, a library entry the knowledge base also holds) are one.
    numbers: dict[str, int] = {}
    cited: list[str] = []
    first_of: dict[str, str] = {}
    for slug in order:
        if slug in unknown:
            continue
        first = first_of.setdefault(sources[slug].get("identity") or slug, slug)
        if first == slug:
            cited.append(slug)
            numbers[slug] = len(cited)
        else:
            numbers[slug] = numbers[first]

    def sub_run(match) -> str:
        slugs = list(dict.fromkeys(TOKEN_RE.findall(match.group(0))))
        if any(s in unknown or (s not in sources and s not in library) for s in slugs):
            return UNKNOWN_SOURCE
        if any(s not in numbers for s in slugs):
            return NOT_NUMBERED
        return "[" + ", ".join(str(n) for n in dict.fromkeys(numbers[s] for s in slugs)) + "]"

    out = _rewrite(data, lambda text: RUN_RE.sub(sub_run, text))
    out = dict(out) if out is data else out
    out["references"] = {"paragraphs": [f"[{numbers[s]}] {format_entry(sources[s])}"
                                        for s in cited]}
    out["sources"] = sources
    out["citations"] = {"order": cited, "numbers": numbers, "unknown": unknown,
                        "not_cited": [s for s in sources if s not in numbers]}
    # What a renderer notes on the data for its caller (the overrides it
    # found stale) is noted on the caller's data, not on this copy alone.
    out[_SIDE_CHANNEL] = data.setdefault(_SIDE_CHANNEL, [])
    out[_DONE] = True
    return out
