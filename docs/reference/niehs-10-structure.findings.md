# NIEHS Report 10 structure vs. the template grammar

**Date:** 2026-09-25. **Source:** `examples/NIEHS-10 PFHxSAm_Final.docx` (the reference
report's Word file; gitignored). The outline was read from the docx itself: paragraph
styles that declare outline levels (`3-02a_Head1_NoNumber` = level 0, `3-03a_Head2` = 1,
`3-04a_Head3` = 2; `Heading 1` = appendix titles; `4-05`/`4-06_Appendix_Head_*` = appendix
sub-levels), the NTP front-matter head styles, table-title and figure-caption styles,
tables, drawings and the 14 section breaks (portrait/landscape), all in body order.
An earlier pass from `docs/NIEHS-Report-10-Reference.pdf` (heading font sizes) was
superseded by this one; the differences are listed at the end.

**Artifact:** `niehs-10-structure.faithful.yaml` — 84 nodes, one per heading / table /
figure in the reference, typed as naturally as the grammar allows. It does **not**
validate. Checked exhaustively against `render_capabilities.COMPONENT_CATALOG`
(allowed children + required bindings) → **37 violations**, and the real validator
(`document_config._tree_from_document_list`) stops at the first:
`template node 'authors': type 'heading-only' is not an allowed child of parent type 'front-matter'`.

## What lines up (no violations)

Everything in the **body**: Background; the full Materials and Methods sub-tree
(3 levels, 21 narratives + the sample-counts table); Results with the three
narrative+tables groups (Tables 2–7 bound to platforms), the BMD summary (Table 8)
and the two genomics sections (Tables 9–12); Summary; References. The front matter's
*flat* parts (title page, Foreword, ToC, Tables list, Peer Review, Abstract) also fit.

## What does not line up

### 1. Front-matter parts with sub-parts (3 violations)

The reference nests headings inside one front-matter part: **About This Report →
Authors, Contributors** (`1-23a_About_This_Report_Head` → `1-10a_Author_Head`,
`1-10_Contrib_Head`). The grammar's `front-matter` is a leaf (`allowed_children: []`),
so the sub-parts have no home. The shipped template flattens them (Authors /
Contributors become role-based content inside `about_report`, see
`render_capabilities.FRONT_MATTER_ROLES_BY_DATA_KEY`). (Acknowledgments is styled
`4-10a_Acknowledgement_HeadFront`, the same level as Publication Details, so it is a
sibling, not a child — the PDF pass had it wrong.) That is a *rendering* choice
encoded as a *structural* impossibility: the tree cannot express the document's own
hierarchy.

### 2. Appendices (34 violations)

`appendix` may contain only `freeform-block` / `freeform-page` — i.e. an appendix is
authored prose supplied as a file. The reference's appendices are **structured
documents in their own right**:

| construct in the reference | example | grammar today |
|---|---|---|
| per-appendix mini table of contents | Appendices A, C, E | `toc` allowed only at root |
| per-appendix lists of tables / figures | B, C, D | `tables-list` allowed only at root; no figures-list type at all |
| numbered narrative subsections, nested two deep | A.1, C.1, C.2 → C.2.1 Methods, C.2.2 Results; E.1, F.1–F.4 | `narrative` not allowed under `appendix`, and `narrative` is a leaf (cannot hold C.2.1 / C.2.2 or the figures and table that sit inside C.2.2) |
| data tables that are not dose-response platforms | Table B-1 animal identifiers; C-1 false positives; D-1 model rules | `table` not allowed under `appendix`, and `table` **requires `platform`** |
| figures | C-1…C-6 (PCA, boxplots), D-1, D-2 (flowcharts) | `figure` exists in the catalog but is an allowed child of **no** type — it can only sit at a region root |
| appendix-scoped numbering | Table B-1, Figure C-5 | numbering is one positional sequence; "Table B-1" is a string literal in three emitters (2026-09-18 review, finding 3) |
| supplementary-material lists | Appendix F: 55 `4-09a_Supplementary_Material_Title` entries (title + data-file name) under F.1–F.4 | no node type for a list of supplied files; modelled here as four `narrative`s |
| landscape pages | Tables 2–6 (two landscape sections), Figures D-1, D-2 | `table` and `figure` are `orientable`, so this one fits — recorded as `orientation: landscape` |

### 3. Not violations, but worth noting

- The body has **no figures**; all figures live in appendices. Figure support is
  therefore an appendix concern first. In the docx each figure is a drawing in a
  `0-32a_Fig_Graphic` paragraph followed by a `0-32_Fig_Caption` paragraph.
- Appendix titles carry **no "Appendix X." prefix** in the docx (plain `Heading 1`
  text); the prefix is added by numbering, as the grammar already does for `appendix`.
- Captions use a period after the number ("Table B-1. …"), matching the template's
  body captions; the PDF pass had rendered them with a colon.
- The reference places **References inside the body** (before Appendix A), which the
  grammar handles as a body `narrative`; BITS would put it in back matter.
- `Table 1` sits inside Methods → Transcriptomics; the grammar's `sample-counts-table`
  fits exactly.

## What this implies

The grammar is a faithful model of the *generated* part of the report (body + flat
front matter) and an explicit non-model of the rest: appendices and nested front
matter are "supplied", not "constructed". Two ways to close the gap:

1. **Grow the grammar** so the tree can express the reference: let `front-matter`
   take `front-matter` / `heading-only` children (or add a `front-matter-part`); let
   `appendix` take `narrative`, `table` (with `platform` optional or a new
   non-platform `data-table` kind), `figure`, `toc`, `tables-list` (+ a
   `figures-list`); give `figure` legal parents; add appendix-scoped numbering
   (letter prefix from the enclosing appendix) to the numbering walk, replacing the
   hardcoded "B-1". Each is a catalog change plus emitter work on all four surfaces.
2. **Keep the grammar and declare the boundary**: appendices remain authored files
   (ADR-0023's provenance boundary already argues data-figures are constructed and
   authored-figures supplied), and the faithful YAML is documentation of what the
   supplied files must contain, not a template.

The choice is a product decision. The section-catalog work (2026-09-22/23) makes
option 1 cheaper than it was: a new node type declared in the catalog reaches the
workflow, the editor and the validator without further registries.

## Docx pass vs. the earlier PDF pass

What the docx exposed that the PDF's font-size outline had missed or got wrong:

| item | PDF pass | docx pass |
|---|---|---|
| Acknowledgments | child of Publication Details | sibling (same head level) |
| Appendix C.2 Empirical False Discovery Rate | flat, with Figures C-5/C-6 + Table C-1 as direct appendix children | has `Head2` sub-parts **C.2.1 Methods** and **C.2.2 Results**; the two figures and Table C-1 sit inside Results |
| Appendix F | four narrative sub-parts | same four, but each is a 55-entry supplementary-material list |
| Orientation | not captured | Tables 2–3, 4–6 and Figures D-1, D-2 are in landscape sections |
| Caption punctuation | "Table B-1:" | "Table B-1." |
| Appendix D's "Figures" list | — | uses the *List of Tables* heading style, i.e. a styling slip in the source |

Net effect on the violation count: 35 → 37 (front matter −2, appendices +4: the nested
C.2 narratives). The conclusion is unchanged: the body and the flat front matter fit
the grammar exactly; nested front matter and every structured appendix do not.
