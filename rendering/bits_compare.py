"""rendering.bits_compare — a published BITS book and ours, aligned for reading.

QC by eye: the published Bookshelf book of a study (assets/cebs/_bookshelf/<R>)
and the book we generate for it are both BITS, and since ADR-0028 their
structure corresponds part for part.  So instead of diffing two flat texts, the
books are aligned the way a reader reads them:

  1. each book is reduced to SECTIONS (a part, or a <sec> inside one, keyed by
     its heading path) holding BLOCKS (paragraph, list item, table, figure,
     media, reference, footnote, formula), in reading order;
  2. sections are aligned by heading path, then the blocks of each section pair
     by content (tables and figures by label);
  3. a section, table or figure that both books hold but in different places is
     paired anyway and marked MOVED;
  4. every paired block is diffed word by word (tokens: words, numbers as one
     token, punctuation, super/subscripts) and a table cell by cell, each cell
     facing the one that means the same (rendering.bits_compare_tables).

A difference that is only typography (curly vs straight quotes, dashes, no-break
or thin spaces) is still a difference — it is counted and shown, under its own
class (``typo``) so a reader can mute it.

The result (`Comparison`) feeds two renderings: the side-by-side / unified HTML
page (rendering.bits_compare_page) and the conventional unified diff
(`unified_diff`), over the flat text of each book (`flat_lines`), which any diff
tool can read.

Public API:
    load_book(source) -> (book, {graphic href: data URI})   a bundle dir, BITS file or bits zip
    compare(published_book, our_book, *, left_images=None, right_images=None) -> Comparison
    word_ops(a, b) -> [(op, a_text, b_text)]
    flat_lines(sections) -> ([line], [section start index])
    unified_diff(cmp, left_name, right_name, context=2) -> str
"""

from __future__ import annotations

import base64
import difflib
import io
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from rendering.bits_bundle import book_regions, read_bundle

XLINK = "{http://www.w3.org/1999/xlink}href"

# Super/subscripts travel through the text as marked runs, so a footnote mark
# never fuses with the word before it ("Weight^a", not "Weighta") and the page
# can render them as <sup>/<sub>.
SUP_OPEN, SUP_CLOSE, SUB_OPEN, SUB_CLOSE = "\x01", "\x02", "\x03", "\x04"

_PART_TAGS = ("foreword", "preface", "dedication", "front-matter-part", "ack",
              "book-part", "book-app", "glossary", "notes")


def _ln(el) -> str:
    return el.tag.split("}")[-1] if isinstance(el.tag, str) else ""


def _ws(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace(" ", " ")).strip()


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------

def inline_text(el, skip: frozenset = frozenset({"fn"})) -> str:
    """An element's text with super/subscripts marked (see SUP_OPEN) and line
    breaks as spaces; the elements named in `skip` are left out."""
    out = [el.text or ""]
    for c in el:
        out += [inline_child(c, skip), c.tail or ""]
    return "".join(out)


def inline_child(c, skip: frozenset = frozenset({"fn"})) -> str:
    """One inline child element's text, without its tail (see inline_text)."""
    tag = _ln(c)
    if not tag or tag in skip:
        return ""
    if tag == "break":
        return " "
    inner = inline_text(c, skip)
    if tag in ("sup", "sub") and inner.strip():
        return (SUP_OPEN if tag == "sup" else SUB_OPEN) + inner.strip() + (
            SUP_CLOSE if tag == "sup" else SUB_CLOSE)
    return "" if tag in ("sup", "sub") else inner


def text_of(el, skip: frozenset = frozenset({"fn"})) -> str:
    return _ws(inline_text(el, skip)) if el is not None else ""


def plain(s: str) -> str:
    """Marked text as plain text: ``a^b`` / ``a_b`` for super/subscripts."""
    return (s.replace(SUP_OPEN, "^").replace(SUB_OPEN, "_")
            .replace(SUP_CLOSE, "").replace(SUB_CLOSE, ""))


# Typography: what a reader sees as the same character.
_TYPO = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'",
                       "–": "-", "—": "-", "−": "-", "‑": "-",
                       " ": " ", " ": " ", " ": " ", " ": " ",
                       " ": " ", "…": "..."})


def typo_norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.translate(_TYPO)).strip()


_TOKEN = re.compile(r"\x01[^\x02]*\x02|\x03[^\x04]*\x04|\d+(?:[.,]\d+)*|\w+|\s+|[^\w\s]")


def tokens(s: str) -> list[str]:
    return _TOKEN.findall(s)


def _matcher(a: list, b: list) -> difflib.SequenceMatcher:
    return difflib.SequenceMatcher(None, a, b, autojunk=False)


def word_ops(a: str, b: str) -> list[tuple[str, str, str]]:
    """(op, published text, our text) runs turning `a` into `b`, op in
    equal / replace / delete / insert / typo.  A run of only spaces or one
    punctuation mark between two changes joins them, so a change reads as a
    phrase rather than as confetti; a change that is only typography is
    ``typo``."""
    ta, tb = tokens(a), tokens(b)
    raw = []
    for op, i1, i2, j1, j2 in _matcher(ta, tb).get_opcodes():
        raw.append([op, "".join(ta[i1:i2]), "".join(tb[j1:j2])])
    merged: list[list[str]] = []
    for k, run in enumerate(raw):
        if (run[0] == "equal" and merged and merged[-1][0] != "equal"
                and k + 1 < len(raw) and raw[k + 1][0] != "equal"
                and len(run[1].strip()) <= 1):
            merged[-1][1] += run[1]
            merged[-1][2] += run[2]
            continue
        if merged and run[0] != "equal" and merged[-1][0] != "equal":
            merged[-1][0] = "replace"
            merged[-1][1] += run[1]
            merged[-1][2] += run[2]
        else:
            merged.append(list(run))
    out = []
    for op, x, y in merged:
        if op != "equal" and typo_norm(plain(x)) == typo_norm(plain(y)):
            op = "typo"
        out.append((op, x, y))
    return out


def words(s: str) -> list[str]:
    """The word tokens of a text: words, numbers and super/subscripts, not
    spaces or punctuation (which would make any two citations look alike)."""
    return [t for t in tokens(s) if t[0].isalnum() or t[0] in (SUP_OPEN, SUB_OPEN) or t[0] == "_"]


def word_count(s: str) -> int:
    return len(words(s))


def similarity(a: str, b: str) -> float:
    """2·matched / (words in a + words in b)."""
    wa, wb = words(a), words(b)
    if not wa and not wb:
        return 1.0
    return _matcher(wa, wb).ratio()


def _matched_words(a: str, b: str) -> int:
    return sum(m.size for m in _matcher(words(a), words(b)).get_matching_blocks())


# ---------------------------------------------------------------------------
# Books → sections of blocks
# ---------------------------------------------------------------------------

@dataclass
class Block:
    kind: str                # p, li, table, fig, media, ref, fn, formula, title, contrib
    text: str                # marked text (for a table/figure: label + caption)
    label: str = ""
    grid: list[list[str]] | None = None    # a table's rows, spans expanded
    head_rows: int = 0
    notes: list[str] = field(default_factory=list)   # table footnotes / figure notes
    image: str = ""          # a figure's graphic href

    @property
    def key(self) -> str:
        """What pairs two blocks without comparing their content."""
        if self.kind in ("table", "fig") and self.label:
            return f"{self.kind}:{self.label.lower()}"
        return f"{self.kind}:{typo_norm(plain(self.text)).lower()}"

    def body_text(self) -> str:
        """Everything the block says, for similarity and word counts."""
        parts = [self.text]
        if self.grid:
            parts += [" ".join(r) for r in self.grid]
        parts += self.notes
        return " ".join(p for p in parts if p)


@dataclass
class Section:
    path: tuple[str, ...]    # headings from the part down ("Results", "Body Weights")
    label: str
    title: str
    depth: int
    blocks: list[Block] = field(default_factory=list)

    @property
    def heading(self) -> str:
        return " ".join(x for x in (self.label, self.title) if x)

    @property
    def key(self) -> str:
        return " › ".join(typo_norm(plain(p)).lower() for p in self.path)


def expand_rows(trs) -> list[list[str]]:
    """Table rows of cell text on a full grid: a value spanning rows repeats in
    each row it covers (so a row still reads on its own); one spanning columns
    stands in its first column, the rest empty (as it reads on the page)."""
    grid, pending = [], {}          # column → [rows left, value]

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
            if _ln(c) not in ("td", "th"):
                continue
            carry(row)
            v = text_of(c)
            rs, cs = int(c.get("rowspan") or 1), int(c.get("colspan") or 1)
            for k in range(cs):
                val = v if k == 0 else ""
                if rs > 1:
                    pending[len(row)] = [rs - 1, val]
                row.append(val)
        carry(row)
        if pending:
            carry(row, upto=max(pending) + 1)
        grid.append(row)
    width = max((len(r) for r in grid), default=0)
    return [r + [""] * (width - len(r)) for r in grid]


def _caption(el) -> tuple[str, list[str]]:
    cap = el.find("caption")
    if cap is None:
        return "", []
    title = text_of(cap.find("title"))
    paras = [text_of(p) for p in cap.findall("p")]
    return title, [p for p in paras if p]


def _labelled(label: str, text: str) -> str:
    return f"{label}. {text}" if label and text else (label or text)


def _table_block(tw) -> Block:
    label = text_of(tw.find("label"))
    title, paras = _caption(tw)
    head = [tr for tr in tw.iter("tr") if _ln(tr.getparent()) == "thead"]
    body = [tr for tr in tw.iter("tr") if _ln(tr.getparent()) != "thead"]
    notes = []
    for fn in tw.findall("table-wrap-foot//fn"):
        lab = text_of(fn.find("label"))
        body_t = " ".join(text_of(p) for p in fn.findall("p")) or text_of(fn, frozenset({"label"}))
        notes.append(f"{SUP_OPEN}{lab}{SUP_CLOSE}{body_t}" if lab else body_t)
    notes += [text_of(p) for p in tw.findall("table-wrap-foot/p")]
    hrows = expand_rows(head)
    grid = expand_rows(head + body)
    return Block("table", _ws(" ".join([_labelled(label, title), *paras])), label,
                 grid, len(hrows), [n for n in notes if n])


def _fig_block(fig) -> Block:
    label = text_of(fig.find("label"))
    title, paras = _caption(fig)
    notes = [text_of(p) for p in fig.findall("caption//fn/p")]
    notes += [text_of(a) for a in fig.findall("attrib")]
    g = fig.find(".//graphic")
    return Block("fig", _ws(" ".join([_labelled(label, title), *paras])), label,
                 notes=[n for n in notes if n], image=(g.get(XLINK) or "") if g is not None else "")


def _media_block(m) -> Block:
    href = m.get(XLINK) or ""
    cap = text_of(m.find("caption"), frozenset({"fn"})) or text_of(m)
    return Block("media", _ws(f"{cap} [{href}]" if href and href not in cap else cap or href))


def _ref_block(ref) -> Block:
    cit = ref.find("mixed-citation")
    if cit is None:
        cit = ref.find("element-citation")
    lab = text_of(ref.find("label"))
    t = text_of(cit if cit is not None else ref, frozenset({"fn", "label"}))
    return Block("ref", f"{lab}. {t}" if lab else t)


_INLINE_BLOCKS = frozenset({"table-wrap", "fig", "list", "media", "disp-formula", "disp-quote",
                            "boxed-text", "supplementary-material", "fig-group"})


def _para_blocks(p, kind: str = "p") -> list[Block]:
    """A <p> as blocks, split around any block element nested in it."""
    out, buf = [], [p.text or ""]
    for c in p:
        tag = _ln(c)
        if tag in _INLINE_BLOCKS:
            s = _ws("".join(buf))
            if s:
                out.append(Block(kind, s))
            out += _blocks_of(c)
            buf = [c.tail or ""]
            continue
        buf += [inline_child(c), c.tail or ""]
    s = _ws("".join(buf))
    return out + ([Block(kind, s)] if s else [])


def _blocks_of(el) -> list[Block]:
    """The blocks a block-level element (not a section) holds."""
    tag = _ln(el)
    if tag == "p":
        return _para_blocks(el)
    if tag == "list":
        out = []
        for li in el.findall("list-item"):
            for c in li:
                if _ln(c) == "p":
                    out += _para_blocks(c, "li")
                elif _ln(c) == "list":
                    out += _blocks_of(c)
        return out
    if tag == "table-wrap":
        return [_table_block(el)]
    if tag == "fig":
        return [_fig_block(el)]
    if tag in ("media", "supplementary-material"):
        return [_media_block(el)]
    if tag == "ref":
        return [_ref_block(el)]
    if tag == "fn":
        lab = text_of(el.find("label"))
        t = " ".join(text_of(p) for p in el.findall("p")) or text_of(el, frozenset({"label"}))
        return [Block("fn", f"{SUP_OPEN}{lab}{SUP_CLOSE}{t}" if lab else t)] if t else []
    if tag == "disp-formula":
        t = text_of(el, frozenset({"label"}))
        return [Block("formula", t)] if t else []
    if tag in ("ref-list", "fn-group", "boxed-text", "disp-quote", "fig-group", "def-list",
               "app-group", "back", "body", "named-book-part-body"):
        out = []
        for c in el:
            if _ln(c) not in ("title", "label", "sec-meta"):
                out += _blocks_of(c)
        return out
    if tag in ("title", "label", "sec-meta", "book-part-meta", "alt-title", "object-id"):
        return []
    t = text_of(el)
    return [Block("p", t)] if t else []


def _walk(container, path: tuple, depth: int, sec: Section, out: list[Section]) -> None:
    for c in container:
        tag = _ln(c)
        if not tag:
            continue
        if tag in ("sec", "app") or (tag == "ref-list" and c.find("title") is not None
                                      and _ln(container) not in ("back",)):
            label, title = text_of(c.find("label")), text_of(c.find("title"))
            if not (label or title):           # an untitled sec: its content is the parent's
                _walk(c, path, depth, sec, out)
                continue
            child = Section(path + (title or label,), label, title, depth)
            out.append(child)
            _walk(c, child.path, depth + 1, child, out)
        elif tag in ("body", "named-book-part-body", "back", "app-group", "fig-group"):
            _walk(c, path, depth, sec, out)
        elif tag == "ref-list":
            for r in c:
                if _ln(r) not in ("title", "label"):
                    sec.blocks += _blocks_of(r)
        else:
            sec.blocks += _blocks_of(c)


def _part_heading(part) -> tuple[str, str]:
    tg = part.find("book-part-meta/title-group")
    if tg is None:
        tg = part
    return text_of(tg.find("label")), text_of(tg.find("title"))


def _meta_sections(book) -> list[Section]:
    bm = book.find("book-meta")
    if bm is None:
        return []
    out = []
    head = Section(("Title",), "", "Title", 0)
    btg = bm.find("book-title-group")
    if btg is not None:
        head.blocks.append(Block("title", text_of(btg.find("book-title"))))
        for sub in btg.findall("subtitle"):
            head.blocks.append(Block("title", text_of(sub)))
    for cg in bm.findall("contrib-group"):
        names = []
        for ct in cg.findall("contrib"):
            n = ct.find("name")
            if n is not None:
                names.append(_ws(f"{text_of(n.find('given-names'))} {text_of(n.find('surname'))}"))
            elif ct.find("collab") is not None:
                names.append(text_of(ct.find("collab")))
        if names:
            head.blocks.append(Block("contrib", "; ".join(names)))
    out.append(head)
    ab = bm.find("abstract")
    if ab is not None:
        sec = Section(("Abstract",), "", text_of(ab.find("title")) or "Abstract", 0)
        out.append(sec)
        _walk(ab, sec.path, 1, sec, out)
    return out


def sections(book) -> list[Section]:
    """The book as sections of blocks, in reading order: its title and abstract,
    then every part (front matter, body, appendices) and the sections in it."""
    out = _meta_sections(book)
    for reg in book_regions(book):
        parts = []
        for c in reg:
            if _ln(c) in ("book-app-group", "app-group"):
                parts.extend(a for a in c if _ln(a))
            elif _ln(c):
                parts.append(c)
        for part in parts:
            tag = _ln(part)
            if tag == "ref-list":
                sec = Section((text_of(part.find("title")) or "References",), "",
                              text_of(part.find("title")) or "References", 0)
                out.append(sec)
                _walk(part, sec.path, 1, sec, out)
                continue
            if tag in ("sec", "app"):
                label, title = text_of(part.find("label")), text_of(part.find("title"))
            elif tag in _PART_TAGS:
                label, title = _part_heading(part)
            else:
                continue
            sec = Section((title or label or tag,), label, title, 0)
            out.append(sec)
            _walk(part, sec.path, 1, sec, out)
    return out


# ---------------------------------------------------------------------------
# Alignment
# ---------------------------------------------------------------------------

def _pair_run(a: list, b: list, sim, threshold: float) -> list[tuple[int | None, int | None]]:
    """Pair two runs in order, maximising the summed similarity of pairs at or
    above `threshold` (an LCS-style dynamic programme); the rest unpaired."""
    n, m = len(a), len(b)
    if not n or not m:
        return [(i, None) for i in range(n)] + [(None, j) for j in range(m)]
    if n * m > 60000:                       # too large to weigh every pair
        return [(i, None) for i in range(n)] + [(None, j) for j in range(m)]
    s = [[0.0] * m for _ in range(n)]
    for i in range(n):
        for j in range(m):
            v = sim(a[i], b[j])
            s[i][j] = v if v >= threshold else 0.0
    best = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            best[i][j] = max(best[i + 1][j], best[i][j + 1],
                             best[i + 1][j + 1] + s[i][j] if s[i][j] else 0.0)
    out, i, j = [], 0, 0
    while i < n and j < m:
        if s[i][j] and best[i][j] == best[i + 1][j + 1] + s[i][j]:
            out.append((i, j))
            i, j = i + 1, j + 1
        elif best[i][j] == best[i + 1][j]:
            out.append((i, None))
            i += 1
        else:
            out.append((None, j))
            j += 1
    out += [(k, None) for k in range(i, n)] + [(None, k) for k in range(j, m)]
    return out


def align(a: list, b: list, key, sim, threshold: float,
          keys: tuple[list, list] | None = None) -> list[tuple[int | None, int | None]]:
    """Index pairs aligning `a` with `b`: equal keys first (longest common
    subsequence), then, within each stretch between them, pairs by similarity.
    `keys` gives both sides' keys directly instead of `key`."""
    out: list[tuple[int | None, int | None]] = []
    ka, kb = keys if keys else ([key(x) for x in a], [key(x) for x in b])
    for op, i1, i2, j1, j2 in _matcher(ka, kb).get_opcodes():
        if op == "equal":
            out += [(i1 + k, j1 + k) for k in range(i2 - i1)]
        else:
            out += [(None if i is None else i1 + i, None if j is None else j1 + j)
                    for i, j in _pair_run(a[i1:i2], b[j1:j2], sim, threshold)]
    return out


def align_by(n: int, m: int, key_a, key_b, sim, threshold: float) -> list[tuple[int | None, int | None]]:
    """`align` over positions 0…n-1 and 0…m-1, given each side's key and the
    similarity of two positions."""
    return align(list(range(n)), list(range(m)), None, sim, threshold, keys=(
        [key_a(i) for i in range(n)], [key_b(j) for j in range(m)]))


@dataclass
class BlockPair:
    left: Block | None
    right: Block | None
    status: str = "same"     # same | typo | changed | rewritten | published-only | ours-only
    sim: float = 1.0
    moved: str = ""          # where the other side stands, for a moved object
    twin: "BlockPair | None" = None   # a moved object's pair ↔ the stub it left
    words: int = 0           # published + ours words
    matched: int = 0         # matching words, counted on both sides

    @property
    def kind(self) -> str:
        return (self.left or self.right).kind


@dataclass
class SectionPair:
    left: Section | None
    right: Section | None
    blocks: list[BlockPair] = field(default_factory=list)
    moved: str = ""
    words: int = 0           # published + ours words in the pair
    matched: int = 0         # matching words, counted on both sides

    @property
    def section(self) -> Section:
        return self.left or self.right

    @property
    def sim(self) -> float:
        return self.matched / self.words if self.words else 1.0

    @property
    def status(self) -> str:
        if self.left is None:
            return "ours-only"
        if self.right is None:
            return "published-only"
        sts = {b.status for b in self.blocks}
        if sts <= {"same"}:
            return "same"
        if sts <= {"same", "typo"}:
            return "typo"
        return "changed"

    @property
    def changes(self) -> int:
        return sum(1 for b in self.blocks if b.status != "same")


@dataclass
class Comparison:
    sections: list[SectionPair]
    left_order: list[Section] = field(default_factory=list)     # each book's sections,
    right_order: list[Section] = field(default_factory=list)    # in reading order
    left_images: dict = field(default_factory=dict)    # href → data URI
    right_images: dict = field(default_factory=dict)

    @property
    def sim(self) -> float:
        w = sum(s.words for s in self.sections)
        return sum(s.matched for s in self.sections) / w if w else 1.0

    def by_kind(self) -> dict[str, tuple[float, int]]:
        """{group: (share of matching words, words)} for the kinds of content a
        reader weighs differently: text, tables, figures, references and the
        front matter's names and titles."""
        acc: dict[str, list[int]] = {}
        for s in self.sections:
            for b in s.blocks:
                g = KIND_GROUP.get(b.kind, "text")
                w = acc.setdefault(g, [0, 0])
                w[0] += b.matched
                w[1] += b.words
        return {g: (m / w if w else 1.0, w) for g, (m, w) in acc.items()}

    def subtree(self) -> list[tuple[float, str]]:
        """(share of matching words, status) of each section with the sections
        under it, so a heading that holds only subsections reads as they do:
        same, typo, or changed if anything in it differs beyond typography."""
        rank = {"same": 0, "typo": 1}
        out = []
        for k, sp in enumerate(self.sections):
            words, matched, worst = sp.words, sp.matched, rank.get(sp.status, 2)
            for sub in self.sections[k + 1:]:
                if sub.section.depth <= sp.section.depth:
                    break
                words += sub.words
                matched += sub.matched
                worst = max(worst, rank.get(sub.status, 2))
            status = sp.status if sp.status in ("published-only", "ours-only") else (
                "same", "typo", "changed")[worst]
            out.append((matched / words if words else 1.0, status))
        return out

    def counts(self) -> dict:
        c: dict[str, int] = {}
        for s in self.sections:
            for b in s.blocks:
                c[b.status] = c.get(b.status, 0) + 1
        return c


# How content is grouped when a comparison is summarised (Comparison.by_kind).
KIND_GROUP = {"p": "text", "li": "text", "fn": "text", "formula": "text", "table": "tables",
              "fig": "figures", "media": "files", "ref": "references", "title": "front matter",
              "contrib": "front matter"}


# Below this a paired paragraph is shown as rewritten, without word highlights.
REWRITE_BELOW = 0.35


# A reference pairs with another only when most of it agrees: any two citations
# share authors' initials, years and journal words.
_PAIR_AT = {"ref": 0.6}


def _block_sim(a: Block, b: Block) -> float:
    if a.kind != b.kind and not {a.kind, b.kind} <= {"p", "li"}:
        return 0.0
    if a.kind in ("table", "fig") and a.label and a.label == b.label:
        return 1.0
    v = similarity(a.body_text(), b.body_text())
    return v if v >= _PAIR_AT.get(a.kind, REWRITE_BELOW) else 0.0


def _section_sim(a: Section, b: Section) -> float:
    s = similarity(a.title or a.label, b.title or b.label)
    return s if a.path[:-1] == b.path[:-1] else s * 0.9


def _judge(p: BlockPair) -> None:
    a, b = p.left, p.right
    if a is None or b is None:
        p.status, p.sim = ("ours-only" if a is None else "published-only"), 0.0
        return
    if a.body_text() == b.body_text() and a.grid == b.grid:
        p.status, p.sim = "same", 1.0
        return
    if (typo_norm(plain(a.body_text())) == typo_norm(plain(b.body_text()))
            and len(a.grid or []) == len(b.grid or [])):
        p.status, p.sim = "typo", 1.0
        return
    p.sim = similarity(a.body_text(), b.body_text())
    p.status = "changed" if p.sim >= REWRITE_BELOW or a.kind in ("table", "fig") else "rewritten"


def _pair_blocks(a: Section | None, b: Section | None) -> list[BlockPair]:
    la, lb = (a.blocks if a else []), (b.blocks if b else [])
    pairs = []
    for i, j in align(la, lb, lambda x: x.key, _block_sim, REWRITE_BELOW):
        pairs.append(BlockPair(None if i is None else la[i], None if j is None else lb[j]))
    return _zip_leftovers(pairs)


def _zip_leftovers(pairs: list[BlockPair]) -> list[BlockPair]:
    """Between two anchored pairs, unpaired prose on each side is laid side by
    side in order (a rewritten stretch reads better facing its counterpart than
    stacked after it); tables, figures and the rest stay one-sided."""
    out: list[BlockPair] = []
    run_l: list[Block] = []
    run_r: list[Block] = []

    def flush():
        prose_l = [x for x in run_l if x.kind in ("p", "li")]
        prose_r = [x for x in run_r if x.kind in ("p", "li")]
        k = min(len(prose_l), len(prose_r))
        zl, zr = prose_l[:k], prose_r[:k]
        for x in run_l:
            if x not in zl:
                out.append(BlockPair(x, None))
        for idx in range(k):
            out.append(BlockPair(zl[idx], zr[idx]))
        for x in run_r:
            if x not in zr:
                out.append(BlockPair(None, x))
        run_l.clear()
        run_r.clear()

    for p in pairs:
        if p.left is not None and p.right is not None:
            flush()
            out.append(p)
        elif p.left is not None:
            run_l.append(p.left)
        else:
            run_r.append(p.right)
    flush()
    return out


def _where(s: Section) -> str:
    return " › ".join(plain(x) for x in s.path)


def _pair_moved_sections(pairs: list[SectionPair]) -> list[SectionPair]:
    """A section both books hold, under the same heading path, but in another
    order: paired where the published one stands, marked moved; the stub where
    ours stands says where it went."""
    only_ours = {}
    for k, p in enumerate(pairs):
        if p.left is None and p.right.key not in only_ours:
            only_ours[p.right.key] = k
    drop = set()
    for p in pairs:
        if p.right is None and p.left.key in only_ours:
            k = only_ours.pop(p.left.key)
            p.right = pairs[k].right
            p.moved = "elsewhere in ours (order differs)"
            drop.add(k)
    return [p for k, p in enumerate(pairs) if k not in drop]


def _pair_moved_objects(pairs: list[SectionPair]) -> None:
    """A table or figure both books hold under the same label, in different
    sections: paired where the published one stands, marked with where ours put
    it; ours keeps a stub."""
    ours: dict[str, tuple[SectionPair, BlockPair]] = {}
    for sp in pairs:
        for bp in sp.blocks:
            if bp.left is None and bp.right.kind in ("table", "fig") and bp.right.label:
                ours.setdefault(bp.right.key, (sp, bp))
    for sp in pairs:
        for bp in sp.blocks:
            if bp.right is None and bp.left.kind in ("table", "fig") and bp.left.key in ours:
                osp, obp = ours.pop(bp.left.key)
                bp.right = obp.right
                bp.moved = f"ours: under {_where(osp.section)}"
                obp.moved = f"published: under {_where(sp.section)}"
                obp.status = "moved-stub"
                bp.twin, obp.twin = obp, bp


def _count(bp: BlockPair) -> None:
    a = bp.left.body_text() if bp.left else ""
    b = bp.right.body_text() if bp.right else ""
    wa, wb = word_count(a), word_count(b)
    bp.words = wa + wb
    if bp.status in ("same", "typo"):
        bp.matched = wa + wb
    elif a and b:
        bp.matched = 2 * _matched_words(a, b)


def compare(published_book, our_book, *, left_images: dict | None = None,
            right_images: dict | None = None) -> Comparison:
    """The published book (left) and ours (right), aligned (module docstring)."""
    sa, sb = sections(published_book), sections(our_book)
    pairs = [SectionPair(None if i is None else sa[i], None if j is None else sb[j])
             for i, j in align(sa, sb, lambda s: s.key, _section_sim, 0.6)]
    pairs = _pair_moved_sections(pairs)
    for sp in pairs:
        sp.blocks = _pair_blocks(sp.left, sp.right)
    _pair_moved_objects(pairs)
    for sp in pairs:
        for bp in sp.blocks:
            if bp.status != "moved-stub":
                _judge(bp)
                _count(bp)
        sp.words = sum(bp.words for bp in sp.blocks)
        sp.matched = sum(bp.matched for bp in sp.blocks)
    return Comparison(pairs, sa, sb, left_images or {}, right_images or {})


# ---------------------------------------------------------------------------
# The conventional unified diff, over each book's flat text
# ---------------------------------------------------------------------------

def block_lines(b: Block) -> list[str]:
    """A block as plain text lines: one line a paragraph; a table its caption,
    one ``| … |`` line per row and its footnotes."""
    if b.kind == "table":
        lines = [plain(b.text)]
        for k, row in enumerate(b.grid or []):
            lines.append("| " + " | ".join(plain(c) for c in row) + " |")
            if k + 1 == b.head_rows:
                lines.append("|" + "---|" * len(row))
        return lines + [f"  [{plain(n)}]" for n in b.notes]
    if b.kind == "fig":
        return ([plain(b.text)] + [f"  [{plain(n)}]" for n in b.notes]
                + ([f"  [image: {b.image}]"] if b.image else []))
    prefix = {"li": "- ", "ref": "", "fn": "  ", "contrib": "Contributors: "}.get(b.kind, "")
    return [prefix + plain(b.text)]


def section_lines(s: Section) -> list[str]:
    head = "#" * min(s.depth + 1, 6) + " " + " › ".join(plain(p) for p in s.path)
    lines = [head]
    for b in s.blocks:
        lines += block_lines(b)
    return lines + [""]


def flat_lines(secs: list[Section]) -> tuple[list[str], list[int]]:
    """A book's flat text (one line per paragraph or table row), and where each
    section's lines start."""
    lines, starts = [], []
    for s in secs:
        starts.append(len(lines))
        lines += section_lines(s)
    return lines, starts


def unified_diff(cmp: Comparison, left_name: str, right_name: str, context: int = 2) -> str:
    """A unified diff of the two books' flat text that any diff tool reads, one
    hunk run per aligned section, its header naming the section.  Line numbers
    are those of the flat texts (`flat_lines`).  A moved section stands in the
    diff as removed where the published book has it and added where ours does,
    so the hunks stay in order on both sides."""
    seq = [(sp.left, None if sp.moved else sp.right) for sp in cmp.sections]
    pos = {id(s): k for k, s in enumerate(cmp.right_order)}
    for mr in (sp.right for sp in cmp.sections if sp.moved):
        at = next((idx for idx, (_, r) in enumerate(seq)
                   if r is not None and pos[id(r)] > pos[id(mr)]), len(seq))
        seq.insert(at, (None, mr))

    lo = ro = 0
    out = []
    for l, r in seq:
        ll = section_lines(l) if l else []
        rl = section_lines(r) if r else []
        where = " › ".join(plain(p) for p in (l or r).path)
        for group in _matcher(ll, rl).get_grouped_opcodes(context):
            i1, i2 = group[0][1], group[-1][2]
            j1, j2 = group[0][3], group[-1][4]
            out.append(f"@@ -{_range(lo + i1, i2 - i1)} +{_range(ro + j1, j2 - j1)} @@ {where}")
            for op, a1, a2, b1, b2 in group:
                if op == "equal":
                    out += [" " + x for x in ll[a1:a2]]
                else:
                    out += ["-" + x for x in ll[a1:a2]] + ["+" + x for x in rl[b1:b2]]
        lo, ro = lo + len(ll), ro + len(rl)
    if not out:
        return ""
    return "\n".join([f"--- {left_name}", f"+++ {right_name}", *out]) + "\n"


def _range(start: int, length: int) -> str:
    # Unified-diff ranges are 1-based; an empty range names the line before it.
    return f"{start + 1},{length}" if length else f"{start},0"


# ---------------------------------------------------------------------------
# Loading a book with its figures
# ---------------------------------------------------------------------------

_IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                ".gif": "image/gif", ".svg": "image/svg+xml"}


def _figure_images(book, files: dict[str, bytes]) -> dict[str, str]:
    """{graphic href: data URI} for the book's figures found among `files`
    (name → bytes); a published href carries no extension."""
    out = {}
    for g in book.iter("{*}graphic", "graphic"):
        href = g.get(XLINK) or ""
        for ext in ("", *_IMAGE_TYPES):
            data = files.get(href + ext)
            mime = _IMAGE_TYPES.get(Path(href + ext).suffix.lower())
            if data is not None and mime:
                out[href] = f"data:{mime};base64," + base64.b64encode(data).decode("ascii")
                break
    return out


def load_book(source) -> tuple:
    """(book, {graphic href: data URI}) from a chunked bundle directory (a
    published book, assets/cebs/_bookshelf/<R>), a BITS file, or the zipped
    bundle we emit (output/<DTXSID>/<DTXSID>-bits.zip, a path or its bytes)."""
    if isinstance(source, (bytes, bytearray)) or str(source).endswith(".zip"):
        raw = bytes(source) if isinstance(source, (bytes, bytearray)) else Path(source).read_bytes()
        with zipfile.ZipFile(io.BytesIO(raw)) as zf, tempfile.TemporaryDirectory() as tmp:
            files = {n: zf.read(n) for n in zf.namelist() if not n.endswith("/")}
            for name, data in files.items():
                if name.endswith(".nxml") and "/" not in name:
                    (Path(tmp) / name).write_bytes(data)
            book = read_bundle(Path(tmp))
        return book, _figure_images(book, files)
    path = Path(source)
    book = read_bundle(path)
    folder = path if path.is_dir() else path.parent
    names = {g.get(XLINK) or "" for g in book.iter("{*}graphic", "graphic")}
    files = {}
    for href in names:
        for ext in ("", *_IMAGE_TYPES):
            f = folder / (href + ext)
            if href and f.is_file():
                files[href + ext] = f.read_bytes()
                break
    return book, _figure_images(book, files)
