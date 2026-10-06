#!/usr/bin/env python3
"""tooling/bookshelf_breakdown.py — break the published NIEHS 5-day reports
into reference pieces: sections, tables, figures and supplementary-file links.

Input: NCBI Bookshelf source bundles, one directory per report under
assets/cebs/_bookshelf/<REPORT>/ (RR-8, NIEHS-02 … NIEHS-13), each the
unpacked litarch package (ftp.ncbi.nlm.nih.gov/pub/litarch/<book>_<NBK>.tar.gz,
fetched on the host; SOURCE.txt names it).  A bundle holds the report as BITS
XML, the whole-report PDF (TOC.pdf), figure images and the supplementary files.

Two layouts:
  * whole book in one file — RR-8, NIEHS-02 … 06: TOC.nxml carries the
    abstract, front matter, body sections, references and appendices;
  * one file per part — NIEHS-07 onward: TOC.nxml carries the abstract and
    the reading order (toc-entry → document-id); each part is <id>.nxml.
Both reduce to the same parts: the abstract, each front-matter part, each
top-level body section (Background, Materials and Methods, Results, …), the
references, each appendix.

Output, per report, in <REPORT>/breakdown/:
  sections/NN_<slug>.md   each part as Markdown; tables, figures and
                          supplementary files appear as links
  tables/<id>.json        caption, header rows, body rows (row/col spans
                          expanded into a full grid), footnotes, location
  tables/<id>.md          the same table as Markdown
  report.json             metadata + parts, section outline, tables, figures, media
  CATALOGUE.md            readable outline with every file
and <root>/INDEX.md over all reports.  Cell and paragraph text keep <sup>/<sub>;
no-break spaces become plain spaces.

    python -m tooling.bookshelf_breakdown [--root assets/cebs/_bookshelf] [--report NIEHS-13]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from dataclasses import dataclass, field

from lxml import etree

XLINK = "{http://www.w3.org/1999/xlink}href"
_PARSER = etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False)

# Containers whose children are rendered in place.
_TRANSPARENT = {"body", "named-book-part-body", "back", "front-matter", "book-part-body", "app-group"}
# Headed blocks: a heading from label + title, then the children one level down.
_HEADED = {"sec", "app", "ack", "ref-list", "fn-group", "glossary", "boxed-text", "abstract",
           "foreword", "front-matter-part", "book-app", "book-part", "preface", "dedication"}
_META = {"label", "title", "title-group", "book-part-meta", "sec-meta", "alt-title", "subtitle"}
_UNIT_TAGS = {"foreword", "front-matter-part", "ack", "preface", "dedication"}


def _ws(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace(" ", " ")).strip()


def slug(s: str, n: int = 60) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _ws(re.sub(r"<[^>]+>", "", s)).lower()).strip("-")[:n] or "part"


def inline(el, cell: bool = False) -> str:
    """Inline Markdown for an element's text content (<sup>/<sub> kept as HTML).

    In table cells (cell=True) italic/bold are dropped: the cells carry literal
    significance asterisks that emphasis markup would collide with."""
    out = [el.text or ""]
    for c in el:
        if isinstance(c.tag, str):
            out.append(_inline_child(c, cell))
        out.append(c.tail or "")
    return "".join(out)


def _inline_child(c, cell: bool) -> str:
    tag = etree.QName(c).localname
    txt = inline(c, cell)
    if tag in ("sup", "sub"):
        return f"<{tag}>{txt.strip()}</{tag}>" if txt.strip() else ""
    if tag in ("italic", "bold") and not cell and txt.strip():
        mark = "*" if tag == "italic" else "**"
        lead, core, trail = re.match(r"(\s*)(.*?)(\s*)$", txt, re.S).groups()
        return f"{lead}{mark}{core}{mark}{trail}"
    if tag in ("ext-link", "uri") and c.get(XLINK) and not cell:
        return f"[{_ws(txt) or c.get(XLINK)}]({c.get(XLINK)})"
    if tag == "break":
        return " "
    if tag == "fn":
        return ""          # footnotes inside captions are collected separately
    return txt


def text(el, cell: bool = False) -> str:
    return _ws(inline(el, cell)) if el is not None else ""


def plain(s: str) -> str:
    return _ws(re.sub(r"<[^>]+>", "", s))


# ── tables ───────────────────────────────────────────────────────────────────

def expand(trs) -> list[list[str]]:
    """Rows of cell text with rowspan/colspan expanded: a spanned value is
    repeated in every grid position it covers."""
    grid, pending = [], {}          # pending: column → [rows left, value]

    def carry(row, upto=None):
        while True:
            col = len(row)
            if col in pending and (upto is None or col < upto):
                left, val = pending[col]
                row.append(val)
                if left == 1:
                    del pending[col]
                else:
                    pending[col][0] -= 1
            elif upto is not None and col < upto:
                row.append("")
            else:
                return

    for tr in trs:
        row: list[str] = []
        for c in tr:
            if not isinstance(c.tag, str) or etree.QName(c).localname not in ("td", "th"):
                continue
            carry(row)
            v = text(c, cell=True)
            rs, cs = int(c.get("rowspan") or 1), int(c.get("colspan") or 1)
            for _ in range(cs):
                if rs > 1:
                    pending[len(row)] = [rs - 1, v]
                row.append(v)
        carry(row)
        if pending:
            carry(row, upto=max(pending) + 1)
        grid.append(row)
    width = max((len(r) for r in grid), default=0)
    return [r + [""] * (width - len(r)) for r in grid]


def table_record(tw, report: str, where: dict) -> dict:
    cap = tw.find("caption")
    trs_head = tw.findall(".//thead/tr")
    trs_body = [tr for tr in tw.findall(".//tr") if tr.getparent().tag != "thead"]
    foot = []
    for fn in tw.findall("table-wrap-foot//fn") + tw.findall("table-wrap-foot/p"):
        if fn.tag == "fn":
            body = " ".join(text(p) for p in fn.findall("p")) or text(fn)
            foot.append({"label": text(fn.find("label")), "text": body})
        else:
            foot.append({"label": "", "text": text(fn)})
    header, rows = expand(trs_head), expand(trs_body)
    return {
        "report": report, "id": tw.get("id"), "label": text(tw.find("label")),
        "title": text(cap.find("title")) if cap is not None else "",
        "caption": [text(p) for p in cap.findall("p")] if cap is not None else [],
        **where, "columns": max([len(r) for r in header + rows] or [0]),
        "header": header, "rows": rows, "footnotes": foot,
    }


def _caption(rec: dict) -> str:
    """'Table 2. Title', or just the title for an unlabelled table/figure."""
    return f"{rec['label']}. {rec['title']}" if rec["label"] else rec["title"]


def table_markdown(t: dict) -> str:
    esc = lambda s: s.replace("|", "\\|").replace("*", "\\*")
    lines = [f"# {_caption(t)}", "",
             f"{t['report']} · {' › '.join([t['part']] + t['section'])} · `{t['source']}`", ""]
    lines += [c for c in t["caption"]] + ([""] if t["caption"] else [])
    n = t["columns"]
    if n:
        head = [" / ".join(dict.fromkeys(h[j] for h in t["header"] if h[j])) for j in range(n)] \
            if t["header"] else [""] * n
        lines.append("| " + " | ".join(esc(h) for h in head) + " |")
        lines.append("|" + "---|" * n)
        for r in t["rows"]:
            lines.append("| " + " | ".join(esc(c) for c in r) + " |")
        lines.append("")
    for f in t["footnotes"]:
        lines.append(f"- {f['label'] + ' ' if f['label'] else ''}{f['text']}")
    return "\n".join(lines).rstrip() + "\n"


# ── parts ────────────────────────────────────────────────────────────────────

@dataclass
class Ctx:
    report: str
    bundle: str
    part: str = ""
    source: str = ""
    path: list = field(default_factory=list)
    tables: list = field(default_factory=list)
    figures: list = field(default_factory=list)
    media: list = field(default_factory=list)
    outline: list = field(default_factory=list)

    def where(self) -> dict:
        # The part's own heading is the first path entry when the part is a headed element.
        path = self.path[1:] if self.path[:1] == [self.part] else self.path
        return {"part": self.part, "section": list(path), "source": self.source}


def bundle_file(bundle: str, href: str) -> str | None:
    for ext in ("", ".jpg", ".png", ".gif", ".tif"):
        if os.path.isfile(os.path.join(bundle, href + ext)):
            return href + ext
    return None


def heading(el) -> str:
    title = el.find("title")
    if title is None:
        title = el.find("book-part-meta/title-group/title")
    label = text(el.find("label"))
    t = text(title) if title is not None else ""
    return f"{label}. {t}" if label and t and not t.startswith(label) else (t or label)


def render(el, level: int, ctx: Ctx) -> list[str]:
    """Markdown lines for a block element."""
    tag = etree.QName(el).localname
    if tag in _META or tag in ("book-meta", "collection-meta", "permissions", "toc"):
        return []
    if tag in _TRANSPARENT:
        return _children(el, level, ctx)
    if tag in _HEADED:
        h = heading(el)
        out = []
        if h:
            out = ["#" * min(level, 6) + " " + h, ""]
            ctx.outline.append({"level": level, "title": plain(h), "id": el.get("id")})
            ctx.path.append(plain(h))
        out += _children(el, level + 1, ctx)
        if h:
            ctx.path.pop()
        return out
    if tag == "p":
        return _paragraph(el, level, ctx)
    if tag == "list":
        ordered = el.get("list-type") in ("order", "arabic", "alpha-lower", "roman-lower")
        out = []
        for i, li in enumerate(el.findall("list-item"), 1):
            body = " ".join(" ".join(_paragraph(p, level, ctx)).strip() for p in li if isinstance(p.tag, str))
            out.append(f"{i}. {body}" if ordered else f"- {body}")
        return out + [""]
    if tag == "table-wrap":
        t = table_record(el, ctx.report, ctx.where())
        ctx.tables.append(t)
        return [f"**{_caption(t)}** — [`tables/{t['id']}.md`](../tables/{t['id']}.md)", ""]
    if tag == "fig":
        cap = el.find("caption")
        title = text(cap.find("title")) if cap is not None and cap.find("title") is not None else ""
        paras = [text(p) for p in cap.findall("p")] if cap is not None else []
        notes = [text(p) for p in el.findall("caption//fn/p")]
        g = el.find(".//graphic")
        f = bundle_file(ctx.bundle, g.get(XLINK)) if g is not None else None
        rec = {"report": ctx.report, "id": el.get("id"), "label": text(el.find("label")),
               "title": title or (paras[0] if paras else ""), "caption": paras, "notes": [n for n in notes if n],
               "file": f, **ctx.where()}
        ctx.figures.append(rec)
        out = [f"**{_caption(rec)}**", ""]
        out += [p for p in paras if p and p != rec["title"]] + [f"_{n}_" for n in rec["notes"]]
        return out + ([f"![{rec['label']}](../../{f})", ""] if f else [""])
    if tag == "media":
        href = el.get(XLINK)
        f = bundle_file(ctx.bundle, href) if href else None
        label = text(el.find("caption")) or text(el) or href
        ctx.media.append({"report": ctx.report, "file": f or href, "label": label, **ctx.where()})
        return [f"- [{label}](../../{f or href})"]
    if tag == "ref":
        cit = el.find("mixed-citation")
        if cit is None:
            cit = el.find("element-citation")
        lab = text(el.find("label"))
        return [f"{lab + '. ' if lab else ''}{text(cit if cit is not None else el)}", ""]
    if tag == "fn":
        lab = text(el.find("label"))
        return [f"{lab + ' ' if lab else ''}{' '.join(text(p) for p in el.findall('p')) or text(el)}", ""]
    if tag in ("disp-formula", "disp-quote", "attrib", "statement", "def-list", "verse-group"):
        return [text(el), ""]
    # anything else: blocks inside → recurse, otherwise its text
    kids = [c for c in el if isinstance(c.tag, str)]
    if any(etree.QName(c).localname in _HEADED | {"p", "table-wrap", "fig", "list"} for c in kids):
        return _children(el, level, ctx)
    t = text(el)
    return [t, ""] if t else []


def _children(el, level, ctx) -> list[str]:
    out = []
    for c in el:
        if isinstance(c.tag, str):
            out += render(c, level, ctx)
    return out


_BLOCKS_IN_P = {"table-wrap", "fig", "list", "media", "disp-formula", "disp-quote", "boxed-text"}


def _paragraph(p, level, ctx) -> list[str]:
    """A <p>, split around any block element nested inside it."""
    out, buf = [], [p.text or ""]
    for c in p:
        if not isinstance(c.tag, str):
            buf.append(c.tail or "")
            continue
        if etree.QName(c).localname in _BLOCKS_IN_P:
            s = _ws("".join(buf))
            if s:
                out += [s, ""]
            out += render(c, level, ctx)
            buf = [c.tail or ""]
        else:
            buf += [_inline_child(c, False), c.tail or ""]
    s = _ws("".join(buf))
    return out + ([s, ""] if s else [])


def units(bundle: str) -> list[tuple[str, str, object]]:
    """(key, source file, element) for every part, in reading order."""
    toc = etree.parse(os.path.join(bundle, "TOC.nxml"), _PARSER).getroot()
    out = []
    abstract = toc.find("book-meta/abstract")
    if abstract is not None:
        out.append(("abstract", "TOC.nxml", abstract))
    if toc.find("book-part") is not None:                       # whole book in one file
        bp = toc.find("book-part")
        for c in bp.findall("front-matter/*"):
            if c.tag in _UNIT_TAGS:
                out.append((c.get("id") or slug(heading(c)), "TOC.nxml", c))
        for c in bp.findall("body/sec"):
            out.append((c.get("id"), "TOC.nxml", c))
        for c in bp.findall("back/*"):
            if c.tag in ("ref-list", "app", "ack", "fn-group", "glossary"):
                out.append((c.get("id") or c.tag, "TOC.nxml", c))
            elif c.tag == "app-group":
                out += [(a.get("id"), "TOC.nxml", a) for a in c.findall("app")]
        return out
    order = [r.get("document-id") for r in toc.iter("related-object") if r.get("document-id")]
    files = sorted(f[:-5] for f in os.listdir(bundle) if f.endswith(".nxml") and f != "TOC.nxml")
    for doc in list(dict.fromkeys(order)) + [f for f in files if f not in order]:
        path = os.path.join(bundle, doc + ".nxml")
        if not os.path.exists(path):
            continue
        root = etree.parse(path, _PARSER).getroot()
        content = next((c for c in root if isinstance(c.tag, str)
                        and c.tag not in ("collection-meta", "book-meta")), None)
        if content is not None:
            out.append((doc, doc + ".nxml", content))
    return out


def book_meta(bundle: str) -> dict:
    bm = etree.parse(os.path.join(bundle, "TOC.nxml"), _PARSER).getroot().find("book-meta")
    ids = {b.get("book-id-type"): text(b) for b in bm.findall("book-id")}
    pd = bm.find("pub-date")
    src = open(os.path.join(bundle, "SOURCE.txt")).read() if os.path.exists(os.path.join(bundle, "SOURCE.txt")) else ""
    nbk = re.search(r"(NBK\d+)", src)
    return {
        "title": text(bm.find("book-title-group/book-title")),
        "subtitle": text(bm.find("book-title-group/subtitle")),
        "doi": ids.get("doi"), "book_id": ids.get("pmcid"), "nbk": nbk.group(1) if nbk else None,
        "published": "-".join(x for x in (text(pd.find("year")), text(pd.find("month")).zfill(2)) if x.strip("0"))
        if pd is not None else None,
        "pdf": "TOC.pdf" if os.path.exists(os.path.join(bundle, "TOC.pdf")) else None,
        "source": src.strip(),
    }


def break_down(bundle: str, report: str) -> dict:
    out_dir = os.path.join(bundle, "breakdown")
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)                  # generated; rebuilt from the bundle every run
    os.makedirs(os.path.join(out_dir, "sections"))
    os.makedirs(os.path.join(out_dir, "tables"))
    meta = book_meta(bundle)
    ctx = Ctx(report=report, bundle=bundle)
    parts = []
    for i, (key, src, el) in enumerate(units(bundle)):
        title = plain(heading(el)) or ("Abstract" if key == "abstract" else key)
        ctx.part, ctx.source, ctx.outline = title, src, []
        n_t, n_f, n_m = len(ctx.tables), len(ctx.figures), len(ctx.media)
        tag = etree.QName(el).localname
        if tag in _HEADED:
            body = render(el, 1, ctx)
        else:
            body = ["# " + title, ""] + render(el, 2, ctx)
        name = f"sections/{i:02d}_{slug(title)}.md"
        hdr = f"<!-- {report} · {meta['nbk']} · {src} · part {key} -->"
        with open(os.path.join(out_dir, name), "w") as f:
            f.write(hdr + "\n\n" + re.sub(r"\n{3,}", "\n\n", "\n".join(body)).strip() + "\n")
        parts.append({"order": i, "key": key, "title": title, "source": src, "file": name,
                      "outline": ctx.outline[1:] if tag in _HEADED else ctx.outline,
                      "tables": [t["id"] for t in ctx.tables[n_t:]],
                      "figures": [f["id"] for f in ctx.figures[n_f:]], "media": len(ctx.media) - n_m})
    for t in ctx.tables:
        with open(os.path.join(out_dir, "tables", f"{t['id']}.json"), "w") as f:
            json.dump(t, f, indent=1, ensure_ascii=False)
        with open(os.path.join(out_dir, "tables", f"{t['id']}.md"), "w") as f:
            f.write(table_markdown(t))
    rep = {"report": report, **meta, "parts": parts,
           "tables": [{k: t[k] for k in ("id", "label", "title", "part", "section", "source")} for t in ctx.tables],
           "figures": ctx.figures, "media": ctx.media}
    with open(os.path.join(out_dir, "report.json"), "w") as f:
        json.dump(rep, f, indent=1, ensure_ascii=False)
    with open(os.path.join(out_dir, "CATALOGUE.md"), "w") as f:
        f.write(catalogue(rep))
    return rep


def catalogue(rep: dict) -> str:
    L = [f"# {rep['report']}: {rep['title']}", "",
         f"{rep['subtitle']} · {rep['nbk']} · DOI {rep['doi']} · published {rep['published']} · "
         f"whole report: `../{rep['pdf']}`" if rep["pdf"] else "", "",
         f"{len(rep['parts'])} parts · {len(rep['tables'])} tables · {len(rep['figures'])} figures · "
         f"{len(rep['media'])} supplementary-file links", ""]
    tables = {t["id"]: t for t in rep["tables"]}
    figs = {f["id"]: f for f in rep["figures"]}
    for p in rep["parts"]:
        L.append(f"## {p['title']}  — `{p['file']}`")
        for o in p["outline"]:
            L.append("  " * max(o["level"] - 2, 0) + f"- {o['title']}")
        for tid in p["tables"]:
            L.append(f"- {_caption(tables[tid])} — `tables/{tid}.md`")
        for fid in p["figures"]:
            L.append(f"- {_caption(figs[fid])} — `../{figs[fid]['file']}`")
        if p["media"]:
            L.append(f"- {p['media']} supplementary-file links")
        L.append("")
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default="assets/cebs/_bookshelf")
    ap.add_argument("--report", action="append", default=[])
    a = ap.parse_args()
    reports = a.report or sorted(d for d in os.listdir(a.root)
                                 if os.path.exists(os.path.join(a.root, d, "TOC.nxml")))
    reps = []
    for r in reports:
        rep = break_down(os.path.join(a.root, r), r)
        reps.append(rep)
        print(f"{r:9} {rep['nbk']:10} parts {len(rep['parts']):2}  tables {len(rep['tables']):3}  "
              f"figures {len(rep['figures']):2}  media {len(rep['media']):3}")
    key = lambda r: (not r["report"].startswith("RR"), r["report"])
    lines = ["# Published NIEHS 5-day reports — Bookshelf breakdown", "",
             "Built by `tooling/bookshelf_breakdown.py` from the litarch bundles in this directory.", "",
             "| report | NBK | DOI | published | parts | tables | figures | catalogue |",
             "|---|---|---|---|---|---|---|---|"]
    for r in sorted(reps, key=key):
        lines.append(f"| {r['report']} | {r['nbk']} | {r['doi']} | {r['published']} | {len(r['parts'])} | "
                     f"{len(r['tables'])} | {len(r['figures'])} | `{r['report']}/breakdown/CATALOGUE.md` |")
    if not a.report:
        with open(os.path.join(a.root, "INDEX.md"), "w") as f:
            f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
