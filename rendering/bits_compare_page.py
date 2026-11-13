"""rendering.bits_compare_page — the published book and ours on one page.

Renders a rendering.bits_compare.Comparison as a self-contained HTML page for
reading by eye, in two modes the reader switches between:

  side by side  published on the left, ours on the right, block facing block,
                changed words marked in place (struck on the left, marked on
                the right); a table faces its counterpart row for row, changed
                cells marked; a figure shows both images;
  unified       one column, as a conventional diff reads: an unchanged block
                once, a changed one as its published line (−) over ours (+),
                a table as one merged grid (removed rows, added rows, changed
                cells showing both values).

Every section heads with its similarity (matching words / all words, both
sides) and the outline beside the page shows it for every section, so the
places that differ most are seen first.  Unchanged blocks can be hidden;
typography-only differences (quotes, dashes, spaces) can be muted, never
dropped.  ``j`` / ``k`` step through the changes.

Public API:
    render_page(cmp, *, title, left_label, right_label, subtitle="", links=()) -> str
    render_index(rows, *, title) -> str
"""

from __future__ import annotations

import html

from rendering.bits_compare import (SUB_CLOSE, SUB_OPEN, SUP_CLOSE, SUP_OPEN, Block, BlockPair,
                                    REWRITE_BELOW, Comparison, SectionPair, align, plain,
                                    similarity, typo_norm, word_ops)
from rendering.bits_compare_tables import align_rows, column_map


def _esc(s: str) -> str:
    """Marked text (rendering.bits_compare) as HTML: escaped, super/subscripts
    as <sup>/<sub>."""
    return (html.escape(s, quote=False)
            .replace(SUP_OPEN, "<sup>").replace(SUP_CLOSE, "</sup>")
            .replace(SUB_OPEN, "<sub>").replace(SUB_CLOSE, "</sub>"))


def _balanced(s: str) -> str:
    """A run cut from marked text may hold half a super/subscript; drop the
    stray marker so the HTML stays well formed."""
    for o, c in ((SUP_OPEN, SUP_CLOSE), (SUB_OPEN, SUB_CLOSE)):
        if s.count(o) != s.count(c):
            s = s.replace(o, "").replace(c, "")
    return s


def _attr(s: str) -> str:
    return html.escape(s, quote=True)


# ---------------------------------------------------------------------------
# Words
# ---------------------------------------------------------------------------

def _diff_sides(a: str, b: str) -> tuple[str, str]:
    """The published and our text with the words that differ marked."""
    left, right = [], []
    for op, x, y in word_ops(a, b):
        x, y = _esc(_balanced(x)), _esc(_balanced(y))
        if op == "equal":
            left.append(x)
            right.append(y)
            continue
        cls = ' class="t"' if op == "typo" else ""
        if x:
            left.append(f"<del{cls}>{x}</del>")
        if y:
            right.append(f"<ins{cls}>{y}</ins>")
    return "".join(left), "".join(right)


def _texts(bp: BlockPair, a: str | None, b: str | None) -> tuple[str, str]:
    if a is None:
        return "", _esc(b or "")
    if b is None:
        return _esc(a), ""
    if bp.status == "rewritten" or a == b:
        return _esc(a), _esc(b)
    return _diff_sides(a, b)


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------

_KIND_TAG = {"li": "li", "ref": "ref", "fn": "note", "formula": "formula", "media": "file",
             "contrib": "names", "title": "title"}


def _text_block(bp: BlockPair) -> tuple[str, str, str]:
    """(left, right, unified) HTML of a prose block pair."""
    a = bp.left.text if bp.left else None
    b = bp.right.text if bp.right else None
    l, r = _texts(bp, a, b)
    kind = bp.kind
    tag = _KIND_TAG.get(kind)
    badge = f'<span class="kind">{tag}</span>' if tag and kind not in ("li",) else ""
    bullet = "• " if kind == "li" else ""

    def cell(x: str, present: bool) -> str:
        return (f'<div class="tx k-{kind}">{badge}{bullet}{x}</div>' if present
                else '<div class="absent"></div>')

    left, right = cell(l, a is not None), cell(r, b is not None)
    if bp.status in ("same", "typo") and a is not None and b is not None:
        uni = f'<div class="u u-eq">{cell(r if bp.status == "typo" else l, True)}</div>'
        if bp.status == "typo":
            uni = (f'<div class="u u-del">{cell(l, True)}</div>'
                   f'<div class="u u-add">{cell(r, True)}</div>')
    else:
        uni = ((f'<div class="u u-del">{cell(l, True)}</div>' if a is not None else "")
               + (f'<div class="u u-add">{cell(r, True)}</div>' if b is not None else ""))
    return left, right, uni


def _grid_cell(tag: str, inner: str, cls: str = "") -> str:
    c = f' class="{cls}"' if cls else ""
    return f"<{tag}{c}>{inner}</{tag}>"


_REORDERED = '<span class="ro-mark" title="in another place in our table">↕</span>'


def _cell_pair(x: str | None, y: str | None) -> tuple[str, str, str, str, bool]:
    """(published HTML, our HTML, unified HTML, class, differs beyond
    typography) for two cells that face each other; None for a cell whose
    column the other table does not have."""
    if x is None or y is None:
        return _esc(x or ""), _esc(y or ""), (
            f"<del>{_esc(x)}</del>" if y is None and x else f"<ins>{_esc(y)}</ins>" if y else ""), "uc", False
    if x == y:
        return _esc(x), _esc(y), _esc(y), "", False
    if typo_norm(plain(x)) == typo_norm(plain(y)):
        ls, rs = _diff_sides(x, y)
        return ls, rs, rs, "ct", False
    ls, rs = _diff_sides(x, y)
    return ls, rs, f"<del>{_esc(x)}</del><ins>{_esc(y)}</ins>", "cc", True


def _table_pair(bp: BlockPair) -> tuple[str, str, str]:
    """A table facing its counterpart.  Columns pair by heading
    (bits_compare_tables.column_map) and rows by group and label (align_rows), so a
    cell is compared with the cell that means the same, however each table
    lays them out; side by side each table keeps its own layout, unified shows
    the columns of both in their aligned order."""
    a, b = bp.left, bp.right
    ga, gb = (a.grid or []) if a else [], (b.grid or []) if b else []
    if a and b:
        cols = column_map(a, b)
        rows = align_rows(a, b, cols)
    else:
        width = len((ga or gb or [[]])[0])
        cols = [(k, None) if a else (None, k) for k in range(width)]
        rows = [(i, None, False) for i in range(len(ga))] + [(None, j, False) for j in range(len(gb))]
    a_to_b = {i: j for i, j in cols if i is not None}
    b_to_a = {j: i for i, j in cols if j is not None}
    lrows, rrows, urows = [], [], []
    for i, j, reordered in rows:
        ra = ga[i] if i is not None else None
        rb = gb[j] if j is not None else None
        head = (i is not None and i < a.head_rows) or (j is not None and j < b.head_rows)
        tag = "th" if head else "td"
        if ra is None or rb is None:
            row = ra if ra is not None else rb
            cells = "".join(_grid_cell(tag, _esc(c)) for c in row)
            if ra is None:
                lrows.append(f'<tr class="gap">{_grid_cell(tag, "") * len(ga[0] if ga else row)}</tr>')
                rrows.append(f'<tr class="add">{cells}</tr>')
                urows.append('<tr class="add">' + "".join(
                    _grid_cell(tag, _esc(rb[y]) if y is not None and y < len(rb) else "")
                    for _, y in cols) + "</tr>")
            else:
                lrows.append(f'<tr class="del">{cells}</tr>')
                rrows.append(f'<tr class="gap">{_grid_cell(tag, "") * len(gb[0] if gb else row)}</tr>')
                urows.append('<tr class="del">' + "".join(
                    _grid_cell(tag, _esc(ra[x]) if x is not None and x < len(ra) else "")
                    for x, _ in cols) + "</tr>")
            continue
        changed = False
        lc, rc, uc = [], [], []
        for x in range(len(ra)):
            y = a_to_b.get(x)
            ls, _, _, cls, diff = _cell_pair(ra[x], rb[y] if y is not None and y < len(rb) else None)
            lc.append(_grid_cell(tag, ls, cls))
            changed = changed or diff
        for y in range(len(rb)):
            x = b_to_a.get(y)
            _, rs, _, cls, _ = _cell_pair(ra[x] if x is not None and x < len(ra) else None, rb[y])
            rc.append(_grid_cell(tag, rs, cls))
        for x, y in cols:
            cx = ra[x] if x is not None and x < len(ra) else None
            cy = rb[y] if y is not None and y < len(rb) else None
            _, _, us, cls, _ = _cell_pair(cx, cy)
            uc.append(_grid_cell(tag, us, cls))
        classes = " ".join(c for c in ("chg" if changed else "", "ro" if reordered else "") if c)
        rcls = f' class="{classes}"' if classes else ""
        if reordered:
            # Our table holds this row elsewhere; it is set facing its counterpart.
            rc[0] = rc[0].replace(">", ">" + _REORDERED, 1)
            uc[0] = uc[0].replace(">", ">" + _REORDERED, 1)
        lrows.append(f"<tr{rcls}>{''.join(lc)}</tr>")
        rrows.append(f"<tr{rcls}>{''.join(rc)}</tr>")
        urows.append(f"<tr{rcls}>{''.join(uc)}</tr>")

    cap_l, cap_r = _texts(bp, a.text if a else None, b.text if b else None)
    notes_l, notes_r, notes_u = _notes(bp)

    def wrap(cap: str, body: list[str], notes: str, present: bool) -> str:
        if not present:
            return '<div class="absent"></div>'
        return (f'<div class="obj"><div class="cap">{cap}</div>'
                f'<div class="tw"><table>{"".join(body)}</table></div>{notes}</div>')

    uni_cap = (f'<div class="u u-del"><div class="cap">{cap_l}</div></div>'
               f'<div class="u u-add"><div class="cap">{cap_r}</div></div>'
               if a and b and a.text != b.text else f'<div class="cap">{cap_r or cap_l}</div>')
    uni = (f'<div class="obj">{uni_cap}<div class="tw"><table>{"".join(urows)}</table></div>'
           f'{notes_u}</div>')
    return wrap(cap_l, lrows, notes_l, a is not None), wrap(cap_r, rrows, notes_r, b is not None), uni


def _notes(bp: BlockPair) -> tuple[str, str, str]:
    na = bp.left.notes if bp.left else []
    nb = bp.right.notes if bp.right else []
    if not na and not nb:
        return "", "", ""
    ls, rs, us = [], [], []
    for i, j in align(na, nb, lambda s: typo_norm(plain(s)), similarity, REWRITE_BELOW):
        x = na[i] if i is not None else None
        y = nb[j] if j is not None else None
        if x is not None and y is not None and x != y:
            lx, ry = _diff_sides(x, y)
        else:
            lx, ry = _esc(x or ""), _esc(y or "")
        ls.append(f'<li class="{"del" if y is None else ""}">{lx}</li>' if x is not None else '<li class="gap"></li>')
        rs.append(f'<li class="{"add" if x is None else ""}">{ry}</li>' if y is not None else '<li class="gap"></li>')
        if x == y:
            us.append(f"<li>{ry}</li>")
        else:
            us += ([f'<li class="del">{lx}</li>'] if x is not None else []) + (
                [f'<li class="add">{ry}</li>'] if y is not None else [])
    return (f'<ul class="notes">{"".join(ls)}</ul>', f'<ul class="notes">{"".join(rs)}</ul>',
            f'<ul class="notes">{"".join(us)}</ul>')


def _figure_pair(bp: BlockPair, cmp: Comparison) -> tuple[str, str, str]:
    a, b = bp.left, bp.right
    cap_l, cap_r = _texts(bp, a.text if a else None, b.text if b else None)
    notes_l, notes_r, _ = _notes(bp)

    def side(blk: Block | None, cap: str, notes: str, images: dict) -> str:
        if blk is None:
            return '<div class="absent"></div>'
        src = images.get(blk.image) if blk.image else None
        img = (f'<img loading="lazy" src="{_attr(src)}" alt="{_attr(plain(blk.label))}">' if src
               else f'<div class="noimg">image not in the book: {html.escape(blk.image or "none")}</div>')
        return f'<div class="obj"><div class="cap">{cap}</div><div class="fig">{img}</div>{notes}</div>'

    return side(a, cap_l, notes_l, cmp.left_images), side(b, cap_r, notes_r, cmp.right_images)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

_STATUS_TEXT = {"same": "same", "typo": "typography", "changed": "changed",
                "rewritten": "rewritten", "published-only": "published only",
                "ours-only": "ours only", "moved-stub": "moved"}


def _row(bp: BlockPair, cmp: Comparison, ids: dict) -> str:
    rid = ids[id(bp)]
    st = bp.status
    if st == "moved-stub":
        twin = ids.get(id(bp.twin)) if bp.twin else None
        what = plain(bp.right.label or bp.right.kind)
        link = f' <a href="#{twin}">go to it</a>' if twin else ""
        return (f'<div class="row st-moved-stub" id="{rid}"><div class="stub">{html.escape(what)} '
                f'is set side by side where the published book places it ({html.escape(bp.moved)}).'
                f'{link}</div></div>')
    if bp.kind == "table":
        left, right, uni = _table_pair(bp)
    elif bp.kind == "fig":
        # A figure reads the same in both modes (its images side by side), so
        # it is written once.
        left, right = _figure_pair(bp, cmp)
        uni = None
    else:
        left, right, uni = _text_block(bp)
    pct = f"{bp.sim:.0%}" if st in ("changed", "rewritten") else ""
    meta = f'<span class="st">{_STATUS_TEXT[st]}{" · " + pct if pct else ""}</span>'
    if bp.moved:
        twin = ids.get(id(bp.twin)) if bp.twin else None
        where = html.escape(bp.moved)
        meta += f' <span class="mv">moved — {f"<a href=#{twin}>{where}</a>" if twin else where}</span>'
    views = (f'<div class="v-both"><div class="L">{left}</div><div class="R">{right}</div></div>'
             if uni is None else
             f'<div class="v-sbs"><div class="L">{left}</div><div class="R">{right}</div></div>'
             f'<div class="v-uni">{uni}</div>')
    return (f'<div class="row st-{st} k-{bp.kind}" id="{rid}">'
            f'<div class="meta">{meta}</div>{views}</div>')


def _section(sp: SectionPair, k: int, cmp: Comparison, ids: dict,
             tree: tuple[float, str]) -> str:
    s = sp.section
    sim, st = tree
    path = " › ".join(plain(p) for p in s.path[:-1])
    crumbs = f'<span class="crumbs">{html.escape(path)} ›</span> ' if path else ""
    head_l = html.escape(plain(sp.left.heading)) if sp.left else ""
    head_r = html.escape(plain(sp.right.heading)) if sp.right else ""
    if head_l == head_r or not head_l or not head_r:
        title = head_l or head_r
    else:
        title = f'<del>{head_l}</del> <ins>{head_r}</ins>'
    moved = f'<span class="mv">moved — {html.escape(sp.moved)}</span>' if sp.moved else ""
    rows = "".join(_row(bp, cmp, ids) for bp in sp.blocks)
    level = min(s.depth + 2, 5)
    # The section's own status classes it (what "hide unchanged" folds); the
    # chip and figure speak for it with its subsections.
    return (f'<section class="sec st-{sp.status}" id="s{k}" data-depth="{s.depth}">'
            f'<h{level} class="sh">{crumbs}<span class="ttl">{title}</span>'
            f'<span class="sm"><span class="chip c-{st}">{_STATUS_TEXT.get(st, st)}</span>'
            f'<span class="pct" title="matching words, both sides, with its subsections">'
            f'{sim:.0%}</span>{moved}</span>'
            f'</h{level}>{rows}</section>')


def _outline(cmp: Comparison, tree: list[tuple[float, str]]) -> str:
    items = []
    for k, sp in enumerate(cmp.sections):
        s = sp.section
        pct, st = tree[k]
        items.append(
            f'<li class="st-{st}" style="--d:{s.depth}"><a href="#s{k}" title="'
            f'{_attr(" › ".join(plain(p) for p in s.path))} — {pct:.0%} of words match">'
            f'<span class="on">{html.escape(plain(s.heading) or plain(s.path[-1]))}</span>'
            f'<span class="bar"><i style="width:{pct * 100:.0f}%"></i></span>'
            f'<span class="n">{sp.changes or ""}</span></a></li>')
    return f'<ol class="outline">{"".join(items)}</ol>'


def _summary(cmp: Comparison) -> str:
    c = cmp.counts()
    chips = []
    for st in ("same", "typo", "changed", "rewritten", "published-only", "ours-only"):
        if c.get(st):
            chips.append(f'<span class="chip c-{st}">{c[st]} {_STATUS_TEXT[st]}</span>')
    moved = sum(1 for sp in cmp.sections if sp.moved) + c.get("moved-stub", 0)
    if moved:
        chips.append(f'<span class="chip c-moved">{moved} moved</span>')
    kinds = "".join(
        f'<span class="kd" title="{w:,} words, both books"><b>{v:.0%}</b> {html.escape(g)}</span>'
        for g, (v, w) in sorted(cmp.by_kind().items(), key=lambda x: -x[1][1]) if w)
    return (f'<div class="sum"><div class="big" title="matching words over all words, both books">'
            f'{cmp.sim:.0%}<small>of the words match</small></div>'
            f'<div><div class="kinds">{kinds}</div>'
            f'<div class="chips">{"".join(chips)}<span class="unit">blocks</span></div></div></div>')


def render_page(cmp: Comparison, *, title: str, left_label: str, right_label: str,
                subtitle: str = "", links: tuple = ()) -> str:
    """The comparison as one self-contained HTML page (module docstring).
    `links` are (label, href) pairs shown under the title (the .diff, the flat
    texts, the facsimiles)."""
    ids: dict[int, str] = {}
    n = 0
    for sp in cmp.sections:
        for bp in sp.blocks:
            n += 1
            ids[id(bp)] = f"b{n}"
    tree = cmp.subtree()
    body = "".join(_section(sp, k, cmp, ids, tree[k]) for k, sp in enumerate(cmp.sections))
    link_html = " · ".join(f'<a href="{_attr(h)}">{html.escape(t)}</a>' for t, h in links)
    sub = html.escape(subtitle)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{_CSS}</style></head>
<body class="mode-sbs">
<header class="top">
  <div class="tl"><h1>{html.escape(title)}</h1><p class="sub">{sub}</p>
  <p class="links">{link_html}</p></div>
  {_summary(cmp)}
</header>
<div class="bar-tools" role="toolbar">
  <div class="seg" role="group" aria-label="View">
    <button type="button" data-mode="sbs" aria-pressed="true">Side by side</button>
    <button type="button" data-mode="uni" aria-pressed="false">Unified</button>
  </div>
  <label><input type="checkbox" id="hide-same"> Hide unchanged</label>
  <label><input type="checkbox" id="mute-typo"> Mute typography</label>
  <span class="nav"><button type="button" id="prev" title="previous change (k)">&#9650;</button>
  <span id="pos">–</span>
  <button type="button" id="next" title="next change (j)">&#9660;</button></span>
  <span class="legend"><del>published</del> <ins>ours</ins> <del class="t">typography</del></span>
</div>
<div class="layout">
  <nav class="side" aria-label="Sections">{_outline(cmp, tree)}</nav>
  <main>
    <div class="colheads"><div>{html.escape(left_label)}</div><div>{html.escape(right_label)}</div></div>
    {body}
  </main>
</div>
<script>{_JS}</script>
</body></html>"""


def render_index(rows: list[dict], *, title: str, note: str = "") -> str:
    """A table of comparisons: rows of {report, name, dtxsid, sim, counts, links:
    [(label, href)]}, best first or as given."""
    trs = []
    for r in rows:
        c = r.get("counts", {})
        links = " · ".join(f'<a href="{_attr(h)}">{html.escape(t)}</a>' for t, h in r["links"])
        sim = r.get("sim")
        bar = (f'<span class="bar"><i style="width:{sim * 100:.0f}%"></i></span> {sim:.0%}'
               if sim is not None else html.escape(r.get("error", "—")))
        trs.append(
            f'<tr><td><b>{html.escape(r["report"])}</b></td><td>{html.escape(r["name"])}'
            f'<div class="id">{html.escape(r["dtxsid"])}</div></td><td class="simc">{bar}</td>'
            f'<td class="num">{c.get("changed", 0) + c.get("rewritten", 0)}</td>'
            f'<td class="num">{c.get("published-only", 0)}</td><td class="num">{c.get("ours-only", 0)}</td>'
            f'<td>{links}</td></tr>')
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title><style>{_CSS}</style></head>
<body class="index"><header class="top"><div class="tl"><h1>{html.escape(title)}</h1>
<p class="sub">{html.escape(note)}</p></div></header>
<main class="idx"><table class="idx">
<thead><tr><th>Report</th><th>Test article</th><th>Words matching</th><th>Changed</th>
<th>Published only</th><th>Ours only</th><th>Open</th></tr></thead>
<tbody>{"".join(trs)}</tbody></table></main></body></html>"""


_CSS = """
:root{--bg:#fbfbfa;--panel:#fff;--ink:#1d2329;--muted:#66707a;--rule:#e1e4e8;--soft:#f3f4f6;
--del-bg:#fde2e1;--del-ink:#8c1d18;--add-bg:#d9f2df;--add-ink:#14532d;--typo-bg:#ece7f8;--typo-ink:#4a3a7a;
--chg:#b8860b;--accent:#1f5f99;--gap:repeating-linear-gradient(135deg,#f4f4f4 0 6px,#ececec 6px 12px);
--c-same:#2e7d4f;--c-typo:#7a62b8;--c-changed:#c08410;--c-rewritten:#c0571a;--c-published-only:#b3261e;
--c-ours-only:#1f6fb2;--c-moved:#5f6b76;}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#15181b;--panel:#1c2024;--ink:#e3e6e9;
--muted:#97a1ab;--rule:#30363d;--soft:#22272c;--del-bg:#4b1d1b;--del-ink:#ffb4ab;--add-bg:#173a24;
--add-ink:#a6e3b5;--typo-bg:#2f2846;--typo-ink:#cfc2f5;--accent:#7fb2e5;
--gap:repeating-linear-gradient(135deg,#1f2327 0 6px,#25292e 6px 12px);}}
:root[data-theme="dark"]{--bg:#15181b;--panel:#1c2024;--ink:#e3e6e9;--muted:#97a1ab;--rule:#30363d;--soft:#22272c;
--del-bg:#4b1d1b;--del-ink:#ffb4ab;--add-bg:#173a24;--add-ink:#a6e3b5;--typo-bg:#2f2846;--typo-ink:#cfc2f5;
--accent:#7fb2e5;--gap:repeating-linear-gradient(135deg,#1f2327 0 6px,#25292e 6px 12px);}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
a{color:var(--accent)}
header.top{display:flex;gap:24px;align-items:flex-end;justify-content:space-between;flex-wrap:wrap;
padding:18px 20px 12px;border-bottom:1px solid var(--rule);background:var(--panel)}
h1{font-size:1.25rem;margin:0}
.sub{margin:2px 0 0;color:var(--muted)}
.links{margin:6px 0 0;font-size:.85rem}
.sum{display:flex;gap:18px;align-items:center}
.big{font-size:2rem;font-weight:700;line-height:1;font-variant-numeric:tabular-nums}
.big small{display:block;font-size:.7rem;font-weight:400;color:var(--muted)}
.chips{display:flex;flex-wrap:wrap;gap:6px;max-width:520px;align-items:center}
.unit{color:var(--muted);font-size:.75rem}
.kinds{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:.8rem;color:var(--muted);margin-bottom:6px}
.kinds b{color:var(--ink);font-variant-numeric:tabular-nums}
.chip{font-size:.72rem;padding:1px 8px;border-radius:10px;border:1px solid currentColor;white-space:nowrap}
.c-same{color:var(--c-same)}.c-typo{color:var(--c-typo)}.c-changed{color:var(--c-changed)}
.c-rewritten{color:var(--c-rewritten)}.c-published-only{color:var(--c-published-only)}
.c-ours-only{color:var(--c-ours-only)}.c-moved{color:var(--c-moved)}
.bar-tools{position:sticky;top:0;z-index:5;display:flex;gap:16px;align-items:center;flex-wrap:wrap;
padding:8px 20px;background:var(--panel);border-bottom:1px solid var(--rule)}
.seg{display:inline-flex;border:1px solid var(--rule);border-radius:6px;overflow:hidden}
.seg button{border:0;background:transparent;color:var(--ink);padding:5px 12px;cursor:pointer;font:inherit}
.seg button[aria-pressed="true"]{background:var(--accent);color:#fff}
.nav{display:inline-flex;align-items:center;gap:6px;font-variant-numeric:tabular-nums}
.nav button{border:1px solid var(--rule);background:var(--panel);color:var(--ink);border-radius:5px;cursor:pointer;padding:2px 8px}
.legend{margin-left:auto;font-size:.8rem;display:flex;gap:8px}
.layout{display:grid;grid-template-columns:270px minmax(0,1fr)}
nav.side{position:sticky;top:46px;align-self:start;max-height:calc(100vh - 46px);overflow:auto;
border-right:1px solid var(--rule);padding:10px 8px 40px;font-size:.8rem}
ol.outline{list-style:none;margin:0;padding:0}
ol.outline li a{display:grid;grid-template-columns:1fr 46px 22px;gap:6px;align-items:center;
padding:2px 6px 2px calc(6px + var(--d) * 12px);color:var(--ink);text-decoration:none;border-radius:4px}
ol.outline li a:hover,ol.outline li.cur a{background:var(--soft)}
ol.outline .on{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
ol.outline .n{color:var(--muted);text-align:right;font-variant-numeric:tabular-nums}
.bar{display:inline-block;width:46px;height:6px;background:var(--soft);border-radius:3px;overflow:hidden;vertical-align:middle}
.bar i{display:block;height:100%;background:var(--c-same)}
li.st-changed .bar i,li.st-typo .bar i{background:var(--c-changed)}
li.st-published-only .bar i,li.st-ours-only .bar i{background:transparent}
li.st-published-only .on{color:var(--c-published-only)}li.st-ours-only .on{color:var(--c-ours-only)}
main{padding:0 20px 120px;min-width:0}
.colheads{position:sticky;top:46px;z-index:4;display:grid;grid-template-columns:1fr 1fr;gap:16px;
background:var(--bg);padding:8px 0;font-weight:600;color:var(--muted);border-bottom:1px solid var(--rule)}
body.mode-uni .colheads{display:none}
section.sec{margin:18px 0 6px}
.sh{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;margin:0 0 6px;padding:6px 0;border-bottom:1px solid var(--rule);font-size:1rem}
h2.sh{font-size:1.15rem}
.crumbs{color:var(--muted);font-weight:400;font-size:.85em}
.sm{margin-left:auto;display:flex;gap:8px;align-items:center;font-weight:400}
.pct{font-variant-numeric:tabular-nums;color:var(--muted);font-size:.8rem}
.mv{font-size:.75rem;color:var(--c-moved)}
.row{margin:4px 0;padding:6px 0 6px 10px;border-left:3px solid transparent;border-radius:2px}
.row.st-changed{border-left-color:var(--c-changed)}.row.st-rewritten{border-left-color:var(--c-rewritten)}
.row.st-published-only{border-left-color:var(--c-published-only)}.row.st-ours-only{border-left-color:var(--c-ours-only)}
.row.st-typo{border-left-color:var(--c-typo)}
.row.focus{outline:2px solid var(--accent);outline-offset:2px}
.meta{display:flex;justify-content:flex-end;gap:8px;font-size:.68rem;color:var(--muted);margin:-4px 0 1px}
.row.st-same .meta{display:none}
.v-sbs,.v-both{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.v-uni{display:none}
body.mode-uni .v-sbs{display:none}body.mode-uni .v-uni{display:block}
.L,.R{min-width:0}
.absent{height:100%;min-height:1.6em;background:var(--gap);border-radius:3px;opacity:.7}
.tx{white-space:normal;overflow-wrap:anywhere}
.kind{display:inline-block;font-size:.65rem;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);
border:1px solid var(--rule);border-radius:3px;padding:0 4px;margin-right:6px;vertical-align:1px}
.k-ref,.k-fn,.k-media{font-size:.88em}
.k-title{font-weight:600}
del{background:var(--del-bg);color:var(--del-ink);text-decoration:line-through;text-decoration-thickness:1px;border-radius:2px}
ins{background:var(--add-bg);color:var(--add-ink);text-decoration:none;border-radius:2px}
del.t,ins.t{background:var(--typo-bg);color:var(--typo-ink)}
body.mute-typo del.t,body.mute-typo ins.t{background:none;color:inherit;text-decoration:none}
.st-rewritten .L .tx{background:var(--del-bg)}.st-rewritten .R .tx{background:var(--add-bg)}
.st-published-only .L .tx{background:var(--del-bg)}.st-ours-only .R .tx{background:var(--add-bg)}
.u{display:grid;grid-template-columns:18px 1fr;gap:4px;padding:1px 0}
.u::before{color:var(--muted);font-family:ui-monospace,monospace}
.u-eq::before{content:" "}.u-del::before{content:"−";color:var(--c-published-only)}
.u-add::before{content:"+";color:var(--c-same)}
.u-del>.tx,.u-del>.cap{background:color-mix(in srgb,var(--del-bg) 45%,transparent)}
.u-add>.tx,.u-add>.cap{background:color-mix(in srgb,var(--add-bg) 45%,transparent)}
.obj .cap{font-weight:600;margin-bottom:4px}
.tw{overflow-x:auto;max-width:100%;border:1px solid var(--rule);border-radius:4px;background:var(--panel)}
.tw table{border-collapse:collapse;font-size:.78rem;width:max-content;min-width:100%}
.tw td,.tw th{border-bottom:1px solid var(--rule);padding:2px 6px;text-align:left;vertical-align:top;max-width:260px}
.tw th{background:var(--soft);font-weight:600}
.tw tr.gap td,.tw tr.gap th{background:var(--gap);height:1.5em}
.tw tr.del>*{background:var(--del-bg)}.tw tr.add>*{background:var(--add-bg)}
.tw td.cc,.tw th.cc{box-shadow:inset 0 0 0 1px var(--c-changed)}
.ro-mark{color:var(--c-moved);font-weight:700;margin-right:4px}
.tw td.uc,.tw th.uc{color:var(--muted);font-style:italic}
.tw td del,.tw td ins{display:inline}
body.mode-uni .tw td.cc del{display:block}
ul.notes{margin:4px 0 0;padding-left:16px;font-size:.78rem;color:var(--muted)}
ul.notes li.del{background:var(--del-bg)}ul.notes li.add{background:var(--add-bg)}
ul.notes li.gap{list-style:none;background:var(--gap);height:1.2em}
.fig img{max-width:100%;height:auto;border:1px solid var(--rule);background:#fff}
.noimg{padding:20px;text-align:center;color:var(--muted);background:var(--gap);border-radius:4px;font-size:.8rem}
.stub{font-size:.8rem;color:var(--c-moved);font-style:italic}
body.hide-same .row.st-same,body.hide-same.mute-typo .row.st-typo{display:none}
body.hide-same section.sec.st-same>.row,body.hide-same.mute-typo section.sec.st-typo>.row{display:none}
body.hide-same section.sec.st-same .sh,body.hide-same.mute-typo section.sec.st-typo .sh{opacity:.55}
table.idx{border-collapse:collapse;width:100%;background:var(--panel);font-size:.9rem}
table.idx th,table.idx td{border-bottom:1px solid var(--rule);padding:8px 10px;text-align:left;vertical-align:top}
table.idx .num{font-variant-numeric:tabular-nums}
table.idx .id{font-size:.75rem;color:var(--muted);font-family:ui-monospace,monospace}
table.idx .bar{width:120px}
main.idx{padding:20px}
@media (max-width:900px){.layout{grid-template-columns:1fr}nav.side{display:none}
.v-sbs,.v-both,.colheads{grid-template-columns:1fr}.legend{margin-left:0}}
@media print{.bar-tools,nav.side{display:none}.layout{display:block}}
"""

_JS = """
(function(){
const B=document.body, store={get(k){try{return localStorage.getItem(k)}catch(e){return null}},
 set(k,v){try{localStorage.setItem(k,v)}catch(e){}}};
const modeBtns=[...document.querySelectorAll('[data-mode]')];
function setMode(m){B.classList.toggle('mode-sbs',m==='sbs');B.classList.toggle('mode-uni',m==='uni');
 modeBtns.forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.mode===m)));store.set('cmp-mode',m);}
modeBtns.forEach(b=>b.addEventListener('click',()=>setMode(b.dataset.mode)));
const params=new URLSearchParams(location.search);
setMode(params.get('mode')||store.get('cmp-mode')||'sbs');
function toggle(id,cls){const el=document.getElementById(id);el.checked=store.get('cmp-'+id)==='1';
 B.classList.toggle(cls,el.checked);el.addEventListener('change',()=>{B.classList.toggle(cls,el.checked);
 store.set('cmp-'+id,el.checked?'1':'0');count();});}
toggle('hide-same','hide-same');toggle('mute-typo','mute-typo');
let changes=[],cur=-1;const pos=document.getElementById('pos');
function count(){const mute=B.classList.contains('mute-typo');
 changes=[...document.querySelectorAll('.row')].filter(r=>!r.classList.contains('st-same')&&
  !(mute&&r.classList.contains('st-typo'))&&!r.classList.contains('st-moved-stub'));
 pos.textContent=(cur>=0?cur+1:'–')+' / '+changes.length;}
function go(d){if(!changes.length)return;cur=(cur+d+changes.length)%changes.length;
 document.querySelectorAll('.row.focus').forEach(r=>r.classList.remove('focus'));
 const r=changes[cur];r.classList.add('focus');r.scrollIntoView({block:'center'});count();}
document.getElementById('next').addEventListener('click',()=>go(1));
document.getElementById('prev').addEventListener('click',()=>go(-1));
document.addEventListener('keydown',e=>{const t=e.target;if(e.ctrlKey||e.metaKey||e.altKey||
 t.closest('textarea,select,[contenteditable]')||(t.tagName==='INPUT'&&!['checkbox','radio'].includes(t.type)))return;
 if(e.key==='j')go(1);else if(e.key==='k')go(-1);else if(e.key==='u')setMode(B.classList.contains('mode-uni')?'sbs':'uni');});
count();
const links=new Map([...document.querySelectorAll('ol.outline a')].map(a=>[a.getAttribute('href').slice(1),a.parentElement]));
const io=new IntersectionObserver(es=>{es.forEach(e=>{if(e.isIntersecting){
 document.querySelectorAll('ol.outline li.cur').forEach(l=>l.classList.remove('cur'));
 const li=links.get(e.target.id);if(li){li.classList.add('cur');li.scrollIntoView({block:'nearest'});}}});},
 {rootMargin:'-90px 0px -70% 0px'});
document.querySelectorAll('section.sec').forEach(s=>io.observe(s));
})();
"""
