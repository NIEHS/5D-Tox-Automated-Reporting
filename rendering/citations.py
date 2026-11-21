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
  * every token in the data is replaced by its number, written in the
    citation style of the section that prints it.

So a source nothing printed cites is not listed, a paper two studies cite is
listed once, and a view that prints fewer sections has a shorter list.  It is
the rule table numbers follow (the document tree drives the structure).

**The citation style** is declared by the document definition
(document_template.CITATION_STYLES): ``citation_style:`` for the document,
and on any node for that section and the sections under it.

  * ``superscript``, as every published book prints them: the numbers in
    ascending order, joined by a comma, three or more in a row as a range
    ("18,19", "3-6"), set as a superscript after the punctuation that follows
    ("…Dunnett.²⁰").  The paragraph becomes inline units (render_common's
    inline model: text and ``sup`` units), which every surface renders.
  * ``bracket``: "[3]", "[3, 7]", in the order written, where the token was.

Each surface calls ``numbered`` on entry; the result is marked, so a second
call (the probe itself, a generator calling another) changes nothing.  Data
with no sources and no token is returned as it is: the request-body path and
its fixtures, whose references arrive numbered, are untouched.
"""

from __future__ import annotations

import re

from narrative.sources import RUN_RE, TOKEN_RE, format_entry, is_unknown, load_library
from rendering.render_common import (
    INLINE_EXT_LINK, INLINE_STYLES, make_sup,
)

SUPERSCRIPT, BRACKET = "superscript", "bracket"

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


# In the probe every token carries the index of the data string it sits in,
# and the HTML surface marks where each node starts: together they say which
# node prints which string.
_AT = "[[at:{}]]"
_PROBE_RE = re.compile(
    r'<span id="sec-([^"]*)" class="sec-anchor">|\[\[cite:([A-Za-z0-9_.\-]+)\]\]\[\[at:(\d+)\]\]')
_SUPERSCRIPT_DIGITS = str.maketrans("0123456789-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻")
_INLINE_TYPES = (INLINE_EXT_LINK, *INLINE_STYLES)


def _token_strings(obj, found: dict[str, int]) -> dict[str, int]:
    """{each distinct string of the data that cites: its index}."""
    if isinstance(obj, str):
        if "[[cite:" in obj:
            found.setdefault(obj, len(found))
    elif isinstance(obj, dict):
        for value in obj.values():
            _token_strings(value, found)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            _token_strings(value, found)
    return found


def _probe(data: dict, tree=None) -> tuple[list[str], dict[int, str]]:
    """(the slugs the presented report cites, in reading order, each once;
    {index of a citing string of the data: the id of the node that prints it})."""
    import html as _html

    from rendering.html_generator import generate_html

    index = _token_strings(data, {})
    marked = _rewrite(data, lambda text: TOKEN_RE.sub(
        lambda m: m.group(0) + _AT.format(index[text]), text))
    probe = {**marked, _PROBE: True, "references": {"paragraphs": []}, _SIDE_CHANNEL: []}
    order: dict[str, None] = {}
    printed_in: dict[int, str] = {}
    node = ""
    for m in _PROBE_RE.finditer(generate_html(probe, tree=tree)):
        if m.group(1) is not None:
            node = _html.unescape(m.group(1))
        else:
            order.setdefault(m.group(2))
            printed_in.setdefault(int(m.group(3)), node)
    return list(order), printed_in


def printed_order(data: dict, tree=None) -> list[str]:
    """The slugs the presented report cites, in reading order, each once."""
    return _probe(data, tree)[0]


def node_styles(tree, document_style: str) -> dict[str, str]:
    """{node id: the citation style in force there}: the node's own, else the
    nearest declaring node above it, else the document's."""
    if tree is None:
        from document_model.document_tree import DOCUMENT_TREE
        tree = DOCUMENT_TREE
    styles: dict[str, str] = {}

    def walk(nodes, inherited: str) -> None:
        for node in nodes or []:
            style = getattr(node, "citation_style", None) or inherited
            styles[node.id] = style
            walk(getattr(node, "children", None), style)

    walk(tree, document_style)
    return styles


def superscript_numbers(numbers) -> str:
    """Numbers as a superscript citation prints them: ascending, each once,
    joined by a comma, three or more in a row as a range ("18,19", "3-6")."""
    ordered = sorted(set(numbers))
    parts: list[str] = []
    i = 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1] == ordered[j] + 1:
            j += 1
        if j - i >= 2:
            parts.append(f"{ordered[i]}-{ordered[j]}")
        else:
            parts.extend(str(n) for n in ordered[i:j + 1])
        i = j + 1
    return ",".join(parts)


def _is_inline_paragraph(items) -> bool:
    return any(isinstance(u, dict) and u.get("type") in _INLINE_TYPES for u in items)


def _write(obj, rewrite, position: str = "value"):
    """``obj`` with every citing string rewritten by ``rewrite(text)``, which
    returns a string, or inline units (a list) for a superscript paragraph.

    Units take the place of the string where a paragraph may be units: an item
    of a list of paragraphs becomes the unit list; a text unit of a paragraph
    that already is units is replaced by them.  Anywhere else (a string that
    is a value, where no markup can go) the superscript is written with
    superscript digits.  Containers with nothing to change are returned as
    they are (no copy)."""
    if isinstance(obj, str):
        if "[[cite:" not in obj:
            return obj
        new = rewrite(obj)
        if isinstance(new, list) and position == "value":
            return "".join(u if isinstance(u, str) else str(u.get("text", "")).translate(
                _SUPERSCRIPT_DIGITS) for u in new)
        return new
    if isinstance(obj, dict):
        changed, out = False, {}
        for key, value in obj.items():
            new = _write(value, rewrite)
            changed = changed or new is not value
            out[key] = new
        return out if changed else obj
    if isinstance(obj, (list, tuple)):
        if _is_inline_paragraph(obj):
            new: list = []
            for unit in obj:
                written = _write(unit, rewrite, "unit") if isinstance(unit, str) else unit
                new.extend(written) if isinstance(written, list) else new.append(written)
            same = len(new) == len(obj) and all(a is b for a, b in zip(new, obj))
        else:
            new = [_write(v, rewrite, "item") for v in obj]
            same = all(a is b for a, b in zip(new, obj))
        return obj if same else (new if isinstance(obj, list) else tuple(new))
    return obj


def numbered(data: dict, tree=None) -> dict:
    """The report's data with its citations numbered as the presented report
    prints them, each written in the citation style of the section that prints
    it, and ``data["references"]`` holding exactly the cited sources.

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

    order, printed_in = _probe(data, tree)
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

    def pending(slugs) -> str | None:
        """What is printed in place of a run that cannot be numbered."""
        if any(s in unknown or (s not in sources and s not in library) for s in slugs):
            return UNKNOWN_SOURCE
        if any(s not in numbers for s in slugs):
            return NOT_NUMBERED
        return None

    def bracketed(text: str) -> str:
        def sub_run(match) -> str:
            slugs = list(dict.fromkeys(TOKEN_RE.findall(match.group(0))))
            return pending(slugs) or (
                "[" + ", ".join(str(n) for n in dict.fromkeys(numbers[s] for s in slugs)) + "]")
        return RUN_RE.sub(sub_run, text)

    def superscripted(text: str) -> list:
        """The paragraph as inline units: each citation a superscript, set
        after the punctuation that follows it, with no space before it."""
        units: list = []
        literal, at = "", 0
        for match in RUN_RE.finditer(text):
            slugs = list(dict.fromkeys(TOKEN_RE.findall(match.group(0))))
            literal += text[at:match.start()]
            at = match.end()
            marker = pending(slugs)
            if marker:
                literal += marker
                continue
            literal = literal.rstrip(" ")
            after = _PUNCTUATION.match(text, at)
            if after:
                literal += after.group(0)
                at = after.end()
            if literal:
                units.append(literal)
            units.append({**make_sup(superscript_numbers(numbers[s] for s in slugs)),
                          "cites": list(dict.fromkeys(numbers[s] for s in slugs))})
            literal = ""
        literal += text[at:]
        if literal:
            units.append(literal)
        return units

    styles = node_styles(tree, data.get("citation_style") or _default_style())
    index = _token_strings(data, {})

    def rewrite(text: str):
        node = printed_in.get(index[text])
        # A string no node prints has no style to follow: its citations are
        # not numbered, and say so.
        style = styles.get(node, data.get("citation_style") or _default_style()) \
            if node is not None else BRACKET
        return superscripted(text) if style == SUPERSCRIPT else bracketed(text)

    out = _write(data, rewrite)
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


_PUNCTUATION = re.compile(r"[.,;:]+")


def _default_style() -> str:
    from document_model.document_template import DEFAULT_CITATION_STYLE
    return DEFAULT_CITATION_STYLE
