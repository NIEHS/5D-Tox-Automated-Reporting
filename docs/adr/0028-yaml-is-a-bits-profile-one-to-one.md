# 0028: The structure YAML corresponds one-to-one with the published BITS book

- **Status:** Accepted (2026-10-09). The Bookshelf surface (the BITS emitter and the
  facsimile) is migrated first; print surfaces follow, one at a time.
- **Amends:**
  - [ADR-0025](0025-bits-profile-as-structural-grammar.md). Its role vocabulary
    stays. The YAML now also names each part's BITS element and type, labels are
    computed, and ADR-0025 §6's "flow before sub-sections" is enforced.
  - [ADR-0004](0004-bits-jats-export-surface.md) amendment d. Region containers stay,
    but a region no longer decides which element a node becomes.
- **Deciders:** Dan Svoboda
- **Related:**
  - the structure review of 2026-10-09: our NIEHS-10 against the published Bookshelf
    bundle (`assets/cebs/_bookshelf/NIEHS-10`), 14 differences;
  - `rendering/bits_bundle.py` (outline + bundle reader);
  - `tooling/bits_structure.py` (the per-study diff).

## Context

The structure YAML was derived from one Word document. ADR-0025 aligned its
vocabulary with BITS. The comparison with the published book shows that the
remaining gaps come from places where the YAML is BITS-*like* but not BITS-*shaped*:

- **A region decides the element.** Every top-level body node became a
  `book-part book-part-type="chapter"`, and its content was emitted again as a `sec`
  with the same title, so each body part had a doubled section. Published parts are
  `book-part-type="section"`, and their body holds the content directly.
- **Front matter has one generic element.** Acknowledgments became `<ack>`. "About This
  Report" was one node where the book has two typed parts, Authors and Contributors.
  The published front matter is `foreword` plus `front-matter-part`, typed `authors`,
  `contributors`, `peer-review`, `section` or `acknowledgments`.
- **Labels are baked into titles.** Examples are "C.1. Gene Expression Quality Control"
  and "A.1." in authored headings. BITS keeps `<label>` separate. Appendix labels
  ("Appendix A") live in the part's title-group.
- **Tables get their own sections.** A table among sibling sections was wrapped in a
  `sec` of its own, to keep the container valid. In the published book Table 1 sits
  inside "Sequencing Quality Checks…", and Appendix B's table sits directly in the
  appendix body.
- **References is a narrative in the back.** It became a bare `ref-list` in
  `book-back`. The published book has a body `book-part` "References" whose
  `<back><ref-list>` holds numbered (`<label>`) refs.
- **There is no book-meta declaration.** The title was just the chemical name. The
  series, ISSN, publisher and permissions were code defaults or absent. The
  abstract's four parts (Background, Methods, Results, Summary) were whatever the
  data happened to hold.

## Decision

### 1. Each top-level node names its BITS element and part type

Two optional authored fields join `DocNode`:

- **`element`** is the BITS element the node projects to. Its values form a closed
  set:

  | value | used for |
  |---|---|
  | `book-meta` | the title page |
  | `abstract` | `book-meta/abstract` |
  | `foreword` | the Foreword |
  | `front-matter-part` | other front-matter parts |
  | `book-part` | body parts |
  | `book-app` | appendices |

  It is defaulted from the type and region when omitted. The shipped template states
  it on every top-level part, so the YAML reads like the book's part list. Print-only
  nodes (`toc`, `tables-list`, `page-break`) declare no element; Bookshelf generates
  its own table of contents.
- **`book_part_type`** is the `@book-part-type`. It is allowed on top-level parts
  only, and defaults to `section` for front-matter and body parts and `appendix` for
  appendices.

### 2. A part's body is its content

A `book-part` body holds the node's own flow content and its child sections, never
the node again as a `sec`. A narrative part (Background, Summary) holds paragraphs.
A container part (Materials and Methods, Results) holds its child sections.

### 3. Labels are computed, never authored in titles

- Appendix labels come from `appendix_letter` (already computed).
- Sections inside an appendix get a computed `sec_label` (`C.1`, `C.2.1`). Body
  sections get none, as published.
- Print surfaces compose "C.1. Title" through a shared helper
  (`render_common.section_heading_text`), so their headings do not change.
- Authored freeform headings keep their own numbering. The BITS projection splits a
  leading "A.1." into `<label>`.

### 4. Flow precedes sub-sections, enforced at load

A `table-wrap`, `fig` or `supplementary-material` child may not follow a `sec`
child. ADR-0025 §6 claimed this rule; the instantiator now refuses a template that
breaks it.

Table-role nodes are always blocks inside their section, never wrapped in a `sec` of
their own. The sample-counts table therefore moves into "Sequencing Quality Checks
and Outlier Removal".

### 5. References is the last body part

A `reference-list` preset (role `ref-list`, binding `derived`) projects to a
`book-part` whose `<back><ref-list>` holds `<ref><label>n</label><mixed-citation>`.
It sits at the end of the body region, where the published book has it. On print it
renders exactly as the References narrative did.

### 6. book-meta is declared

- **Template declaration.** A top-level `book_meta:` block in the template holds the
  facts that belong to the series, not the study:
  - the collection;
  - the series title and ISSN;
  - the publisher;
  - the permissions statement.
- **Title.** The book title is the title page's own title (its cover layout's title
  builder), so print and BITS cannot differ.
- **Study-supplied metadata** comes from front matter, and is emitted only when
  supplied:
  - the subtitle (report number);
  - the DOI;
  - the publication date;
  - the authors (`contrib-group` + `aff`).
- **Abstract.** The abstract node declares `parts: [Background, Methods, Results,
  Summary]`. Each declared part is emitted, and a missing one is a visible pending
  paragraph.

### 7. Packaging is chunked, as NIEHS-07 onward

The `<book>` is the internal form. The Bookshelf deliverable is a bundle:

- **`TOC.nxml`** is a `book-part-wrapper` holding:
  - the collection-meta;
  - the book-meta with the abstract;
  - a `<toc>` in reading order.
- **One `book-part-wrapper` file per part** holds:
  - the collection-meta;
  - the book-meta without the abstract;
  - the part.

File and document ids are our node ids. NCBI's own names (`bp1`, `a-2-A`), its pmcid
ids, its `sec-type="otherN"` and its prev/next part links are assigned at ingest and
are not reproduced.

### 8. Surfaces migrate one at a time

The YAML changes are shared, and print diffs they cause are accepted and eyeballed.
These diffs are:
- About This Report → Authors + Contributors;
- Table 1 inside its section.

The BITS emitter and the Bookshelf facsimile consume the new declarations first. The
print emitters adopt them in their own stages. That includes re-grouping Authors and
Contributors under an "About This Report" heading on paper, if the print reference
still wants it.

## Consequences

- The published outline of NIEHS-10 is a committed fixture
  (`tests/fixtures/reference/NIEHS-10/bookshelf-outline.json`).
  `tests/unit/test_bits_published_structure.py` diffs our book against it. Remaining
  differences are listed there explicitly as content gaps, so any change shows up.
  They are:
  - Appendix C figures and eFDR;
  - Appendix D content;
  - Appendix F's media lists;
  - a front matter that is not supplied.
- `tooling/bits_structure.py` and the `structure` check of `tooling/report_qc.py` give
  the same diff for every downloaded published study.
- Node ids `about` and the region of `references` change. No session artifact keys on
  them; the template's own `styles.instances` is updated.
