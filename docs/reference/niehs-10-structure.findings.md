# NIEHS Report 10 structure vs. the template grammar

**Date:** 2026-09-25. **Source:** `docs/NIEHS-Report-10-Reference.pdf` (80 pp), outline
extracted with `pdf_text` (ToC pages 4–5, heading font sizes, appendix caption lines).
The reference docx (`examples/NIEHS-10 PFHxSAm_Final.docx`) was not on this host when
this was written; re-derive from it when available (it may expose style-level detail
the PDF flattens).

**Artifact:** `niehs-10-structure.faithful.yaml` — 82 nodes, one per heading / table /
figure in the reference, typed as naturally as the grammar allows. It does **not**
validate. Checked exhaustively against `render_capabilities.COMPONENT_CATALOG`
(allowed children + required bindings) → **35 violations**, and the real validator
(`document_config._tree_from_document_list`) stops at the first:
`template node 'authors': type 'heading-only' is not an allowed child of parent type 'front-matter'`.

## What lines up (no violations)

Everything in the **body**: Background; the full Materials and Methods sub-tree
(3 levels, 21 narratives + the sample-counts table); Results with the three
narrative+tables groups (Tables 2–7 bound to platforms), the BMD summary (Table 8)
and the two genomics sections (Tables 9–12); Summary; References. The front matter's
*flat* parts (title page, Foreword, ToC, Tables list, Peer Review, Abstract) also fit.

## What does not line up

### 1. Front-matter parts with sub-parts (5 violations)

The reference nests headings inside two front-matter parts: **About This Report →
Authors, Contributors** (16 pt → 14 pt) and **Publication Details → Acknowledgments**.
The grammar's `front-matter` is a leaf (`allowed_children: []`), so the sub-parts have
no home. The shipped template flattens them (Acknowledgments becomes a sibling; Authors /
Contributors become role-based content inside `about_report`, see
`render_capabilities.FRONT_MATTER_ROLES_BY_DATA_KEY`). That is a *rendering* choice
encoded as a *structural* impossibility: the tree cannot express the document's own
hierarchy.

### 2. Appendices (30 violations)

`appendix` may contain only `freeform-block` / `freeform-page` — i.e. an appendix is
authored prose supplied as a file. The reference's appendices are **structured
documents in their own right**:

| construct in the reference | example | grammar today |
|---|---|---|
| per-appendix mini table of contents | Appendices A, C, E | `toc` allowed only at root |
| per-appendix lists of tables / figures | B, C, D | `tables-list` allowed only at root; no figures-list type at all |
| numbered narrative subsections | A.1, C.1, C.2, E.1, F.1–F.4 | `narrative` not allowed under `appendix` |
| data tables that are not dose-response platforms | Table B-1 animal identifiers; C-1 false positives; D-1 model rules | `table` not allowed under `appendix`, and `table` **requires `platform`** |
| figures | C-1…C-6 (PCA, boxplots), D-1, D-2 (flowcharts) | `figure` exists in the catalog but is an allowed child of **no** type — it can only sit at a region root |
| appendix-scoped numbering | Table B-1, Figure C-5 | numbering is one positional sequence; "Table B-1" is a string literal in three emitters (2026-09-18 review, finding 3) |

### 3. Not violations, but worth noting

- The body has **no figures**; all figures live in appendices. Figure support is
  therefore an appendix concern first.
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
