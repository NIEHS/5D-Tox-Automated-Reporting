"""rendering.bits_compare_tables — which cell of one table faces which of another.

Two tables of the same name in the published book and ours often say the same
in different layouts: the 2023 books group rows under "Male" / "Female" heading
rows where ours has a Sex column; the book names an endpoint "Total T4 (μg/dL)"
where ours says "Total Thyroxine"; a column is "BMD<sub>1Std</sub> (mg/kg)" in
one and "BMD" in the other; the rows come in another order.  Cell-by-cell
comparison is only worth reading when each cell faces the cell that means the
same, so:

  columns pair by heading, units and footnote marks aside (`column_map`);
  rows pair by IDENTITY — the group they stand under and their label — never by
  their numbers alone, except that a row named differently whose data agree is
  the same row (`align_rows`); a row both tables hold in another order is
  still paired, and marked reordered.

Public API:
    column_map(a, b) -> [(published column, our column)]
    align_rows(a, b, cols=None) -> [(published row, our row, reordered)]
"""

from __future__ import annotations

import re

from rendering.bits_compare import (SUB_CLOSE, SUB_OPEN, Block, align_by, plain, similarity,
                                    typo_norm, words)


def _column_head(blk: Block, c: int) -> str:
    """A column's heading as a key: its header cells' words without units in
    parentheses or footnote marks, a subscript kept as part of its word
    ("BMD<sub>L1Std</sub> (mg/kg)<sup>a</sup>" → "bmdl1std")."""
    txt = " ".join(r[c] for r in (blk.grid or [])[:blk.head_rows] if c < len(r) and r[c])
    txt = re.sub(r"\x01[^\x02]*\x02|\([^)]*\)", " ", txt)
    txt = txt.replace(SUB_OPEN, "").replace(SUB_CLOSE, "")
    return " ".join(w.lower() for w in words(txt))


def column_map(a: Block, b: Block) -> list[tuple[int | None, int | None]]:
    """Two tables' columns aligned by heading, in order: a column heads the
    same when its words do, or its first word does ("Direction of Change" /
    "Direction").  Tables without a header row align column for column."""
    na = len(a.grid[0]) if a.grid else 0
    nb = len(b.grid[0]) if b.grid else 0
    if not a.head_rows or not b.head_rows:
        return [(k if k < na else None, k if k < nb else None) for k in range(max(na, nb))]
    ha = [_column_head(a, c) for c in range(na)]
    hb = [_column_head(b, c) for c in range(nb)]

    def sim(i, j):
        if not ha[i] or not hb[j]:
            return 0.0
        fa, fb = ha[i].split()[0], hb[j].split()[0]
        if fa == fb:
            return 1.0
        if fa.startswith(fb) or fb.startswith(fa):      # "bmdl1std" / "bmdl"
            return 0.9
        return similarity(ha[i], hb[j])

    pairs = align_by(na, nb, lambda i: ha[i] or f"#{i}", lambda j: hb[j] or f"#{j}", sim, 0.5)
    if (0, None) in pairs and (None, 0) in pairs:
        # Neither first column found its partner: they are the row-label stubs
        # ("" / "Timepoint"), and correspond.
        pairs = [(0, 0)] + [p for p in pairs if p not in ((0, None), (None, 0))]
    return pairs


def _row_groups(grid: list[list[str]], head_rows: int, lead: list[int]) -> list[str]:
    """The group each row stands under: the last body row before it that holds
    only its first cell ("Male", "Female", "Liver"), as a table groups rows,
    joined with the row's own cells in `lead` — leading columns the other
    table has no counterpart for (a "Sex" column groups as a "Male" row does)."""
    out, group = [], ""         # "#head" a header row, "#group" a group's own row
    for k, row in enumerate(grid):
        if k < head_rows:
            out.append("#head")
        elif row and row[0] and not any(c for c in row[1:]):
            group = typo_norm(plain(row[0])).lower()
            out.append("#group")
        else:
            own = " ".join(typo_norm(plain(row[c])).lower() for c in lead if c < len(row))
            out.append(" ".join(x for x in (group, own) if x))
    return out


# Cells that say there is no value: they agree with each other by saying nothing.
_PLACEHOLDER = frozenset({"", "-", "NA", "NR", "ND", "—"})


def _abbreviates(short: str, long_: str) -> bool:
    """Whether `short` abbreviates `long_` ("wt" / "weight"): same first letter,
    its letters in order within the longer word."""
    if len(short) >= len(long_) or not short or short[0] != long_[0]:
        return False
    rest = iter(long_)
    return all(ch in rest for ch in short)


def align_rows(a: Block, b: Block,
               cols: list[tuple[int | None, int | None]] | None = None
               ) -> list[tuple[int | None, int | None, bool]]:
    """Two tables' rows aligned, in the published table's order: (published
    row, our row, reordered).  A row pairs only with one under the same group
    (Male / Female …) whose row label (its first shared column) is the same, or
    whose shared cells mostly are; a row both tables hold in a different order
    is still paired, and marked reordered, so its cells face their
    counterparts.  `cols` is the column alignment (column_map)."""
    ga, gb = a.grid or [], b.grid or []
    cols = column_map(a, b) if cols is None else cols
    shared = [(i, j) for i, j in cols if i is not None and j is not None]
    first_i = shared[0][0] if shared else 0
    first_j = shared[0][1] if shared else 0
    lead_a = [i for i, j in cols if j is None and i is not None and i < first_i]
    lead_b = [j for i, j in cols if i is None and j is not None and j < first_j]
    grp_a = _row_groups(ga, a.head_rows, lead_a)
    grp_b = _row_groups(gb, b.head_rows, lead_b)

    def cell(row, c):
        return typo_norm(plain(row[c])).lower() if c is not None and c < len(row) else ""

    # A row's identity: its group and its label (the first shared column).
    def ident(grp, row, c):
        if grp.startswith("#") or c is None or c >= len(row):
            return ""
        # Neither footnote marks nor units are the name: "Total T4 (μg/dL)^a" → "total t4".
        label = re.sub(r"\x01[^\x02]*\x02|\([^)]*\)", " ", row[c])
        return " ".join(words(f"{grp} {typo_norm(plain(label)).lower()}"))

    ident_a = [ident(grp_a[i], ga[i], first_i) for i in range(len(ga))]
    ident_b = [ident(grp_b[j], gb[j], first_j) for j in range(len(gb))]
    ka = [(ident_a[i], tuple(cell(ga[i], x) for x, _ in shared)) for i in range(len(ga))]
    kb = [(ident_b[j], tuple(cell(gb[j], y) for _, y in shared)) for j in range(len(gb))]

    # Words that name a group in either table ("male", "female", "liver"): a
    # row may carry one the other table leaves to a heading, but two rows
    # naming different groups are different rows.
    group_words = {w for g in grp_a + grp_b if not g.startswith("#") for w in g.split()}

    def data(row, c):
        """A data cell as compared for identity: no significance or footnote marks."""
        v = re.sub(r"\x01[^\x02]*\x02", "", row[c]) if c is not None and c < len(row) else ""
        return typo_norm(plain(v)).replace("*", "").strip()

    def same_row(i, j) -> float:
        """How surely two rows are the same row: the same name, group words
        aside ("absolute g" under "Liver" / "Male › Liver Absolute (g)"); one
        name within the other ("terminal body weight (sd4) g" / "terminal body
        weight g"); one an abbreviation of the other ("wt" / "weight"); or,
        named differently ("Total T4" / "Total Thyroxine"), the same data in
        most of its shared cells.  A heading or group row pairs only with its
        own kind."""
        if grp_a[i].startswith("#") or grp_b[j].startswith("#"):
            if grp_a[i] != grp_b[j]:
                return 0.0
            return 1.0 if grp_a[i] == "#head" or ga[i][:1] == gb[j][:1] else 0.0
        x, y = ident_a[i].split(), ident_b[j].split()
        if x == y:
            return 1.0
        dx, dy = [w for w in x if w not in y], [w for w in y if w not in x]
        if any(w in group_words for w in dx) and any(w in group_words for w in dy):
            return 0.0                                   # Male's row is not Female's
        dx = [w for w in dx if w not in group_words]
        dy = [w for w in dy if w not in group_words]
        if not dx or not dy:
            return 0.9
        if len(dx) == len(dy) and all(_abbreviates(u, v) or _abbreviates(v, u)
                                      for u, v in zip(dx, dy)):
            return 0.85
        cells = [(data(ga[i], x_), data(gb[j], y_)) for x_, y_ in shared[1:]]
        cells = [(u, v) for u, v in cells if u not in _PLACEHOLDER or v not in _PLACEHOLDER]
        if len(cells) >= 3 and sum(u == v for u, v in cells) >= 2 / 3 * len(cells):
            return 0.8
        return 0.0

    def sim(i, j):
        if not ident_a[i] and not ident_b[j] and not grp_a[i] and not grp_b[j]:
            return similarity(" ".join(ka[i][1]), " ".join(kb[j][1]))   # unlabelled rows
        return same_row(i, j)

    pairs = align_by(len(ga), len(gb), lambda i: ka[i], lambda j: kb[j], sim, 0.5)
    left_alone = [i for i, j in pairs if j is None]
    right_alone = [j for i, j in pairs if i is None]
    moved: dict[int, int] = {}
    for i in left_alone:
        for test in (lambda j: kb[j] == ka[i], lambda j: same_row(i, j) > 0):
            j = next((j for j in right_alone if j not in moved.values() and test(j)), None)
            if j is not None:
                moved[i] = j
                break
    taken = set(moved.values())
    out = []
    for i, j in pairs:
        if i is not None and j is None and i in moved:
            out.append((i, moved[i], True))
        elif i is None and j in taken:
            continue
        else:
            out.append((i, j, False))
    return out
