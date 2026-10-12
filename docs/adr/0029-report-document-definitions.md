# 0029: Each report has a document definition — an era base plus alterations

- **Status:** Accepted (2026-10-09)
- **Amends:**
  - [ADR-0027](0027-pinned-method-profiles.md) §1. A study's version-controlled
    overlay now also holds its document definition (`document.yaml`), next to its
    view (`view.yaml`, filters and charts).
  - [ADR-0028](0028-yaml-is-a-bits-profile-one-to-one.md). The one-to-one structure
    is per report, not a single shared template.
- **Deciders:** Dan Svoboda
- **Related:**
  - `document_model/document_definition.py`;
  - `templates/eras/`;
  - `templates/studies/<DTXSID>/document.yaml`;
  - `tooling/bits_structure.py`.

## Context

The 12 published NIEHS/NTP 5-day reports are "the same, only different". Compared
part by part (`rendering/bits_bundle.outline`), they fall into four generations:

| Era | Reports | Differences within the era | How the era differs |
|---|---|---|---|
| 2018 | RR-8 | — | NTP Research Report series. Single file. Acknowledgments and Collaborators come first; there is no Foreword or Authors. The body ends with Discussion. Appendices A–E. |
| 2022 | NIEHS-02 … 06 | study facts only | Single file: one whole-book `book-part` whose chapters are `sec`, whose appendices are `app`, plus `ack` and a back `ref-list`. Appendices A–F. |
| 2023 | NIEHS-07 … 10 | study facts only | Chunked (TOC.nxml plus one file per part). Appendix A is Internal Dose. |
| 2026 | NIEHS-12, 13 | NIEHS-13 orders A.2/A.3 differently and places some tables differently | Inhalation. Appendices A–G. |

The user decided that these differences must come from a **document definition for
each report**, never from a renderer adjusted until its output matches. They also
decided the form: **an era base, plus alterations to it and additions to it.**

## Decision

1. **A definition is a template file that may `extend` another.** It states only how
   it differs:
   - `packaging` is `chunked` or `single-file`;
   - `book_meta` is deep-merged over the base's;
   - `changes` is an ordered list. Each change is one of:
     - `set` a node's fields (null removes a field);
     - `remove` a node with its subtree;
     - `insert` nodes after or before a node, or into a node or region (first or last);
     - `move` a node.

   Composition works on the raw entries before instantiation, so the template
   validator checks the composed document as it would an authored one. An unknown
   id, an unknown key or an `extends` cycle is an error.
2. **Three levels, one mechanism:**
   - `niehs-5day-report` is the shared base grammar the eras extend;
   - `eras/<era>` reproduce the published generations;
   - `studies/<DTXSID>/document` extends its era for a published study.
   - A new (unpublished) study, one with no definition of its own, is written
     to the latest generation, `eras/niehs-2026`
     (`document_definition.DEFAULT_DEFINITION`; amended 2026-10-12, §10).
3. **Resolution.** A study's tree comes from the first of these that exists:
   1. the session view's `document`;
   2. the legacy session `document.yaml`;
   3. the study's definition;
   4. the definition of a new study (`eras/niehs-2026`).

   The same layer gives the study's `book_meta`, `packaging` and
   `object_position`.
4. **Renderers stay generic.** Emitters and the Bookshelf facsimile handle BITS
   shapes (part elements, single-file versus chunked packaging), never reports or
   eras. Whatever differs between reports is in the definitions.
5. **The published books are the check.** Each published report's outline is a
   committed fixture. A test builds each report from its definition and compares the
   two outlines, apart from a commented list of known *content* gaps.

6. **A definition states structure, never data.** A title or caption may
   name a study fact the data holds (`${chemical_name}`; the animals and
   treatment, `${subject} ${treatment}`, as the 2026 captions end), filled per
   study by `document_tree.study_tree`. A definition never lists what the data
   decides: which species or tissues a study has, or how many tables there
   are.

7. **The parts come from one grammar, the NTP template's.** The NTP Word
   template (`NTP Template 11-04-21.dot`) is built for Inera's eXtyles, the
   Word-to-BITS converter. The books' `content-type`s are its style names.
   `vocab/ntp-bits-grammar.yaml` records which BITS construct each structural
   style becomes, per packaging. A definition may declare only parts the
   grammar makes in its packaging. Every part and roster paragraph of the 12
   published books is one it makes.
8. **A study's supplied files are its data deposit, not authored text.** The
   Supplemental Data lists come from the files deposited with the report,
   recorded as a session sidecar (`deposit.json`, `pipeline/deposit.py`):
   - each file's kind (apical, genomic, study tables, animal data, …) and
     species are read from the depositors' naming convention;
   - a derived `supplementary-material` node lists one kind;
   - a `repeat: deposit_species` section repeats per species.
   A study may state a file's kind or caption, and the deposit's DOI (`templates/studies/<id>/deposit.yaml`); the appendix opens with that DOI (a node's `deposit_text`).
9. **A report may cover several studies, each one a session (2026-10-11).**
   NIEHS-12 and 13 report a rat study and a mouse study of one chemical. Each
   study has its own animals, dose levels, workbooks and genomic project.
   - Each study runs through the pipeline unchanged, in its own session
     (`<DTXSID>_rat`, `<DTXSID>_mouse`).
   - The report session lists them in `studies.json` (species → session, in
     the book's order). It keeps what belongs to the report: front matter,
     Background, deposit, views and overrides.
   - `rendering/report_compose.py` merges the studies' data into the report's
     at the one data entry point (`latex_export.load_session_data`):
     - Each combined table groups its rows by study ("Rats" / "Mice"; "Female
       Rats" … when a study has both sexes). Studies tested at different dose
       levels share the union of the levels, with NA for a level a study did
       not test (`render_common.table_groups`).
     - The studies' References are numbered on from the Background's.
     - The design names their animals together ("Rats and Mice"), and so do
       the title and the captions.
   - The definition repeats sections over the data (§6):
     - `repeat: study_species` gives one copy per study ("Study Design for
       ${species}"); a single study is one unscoped copy.
     - `repeat: genomic_organs` gives one copy per tissue of the genomic
       analyses (`${organ}`).
     - A `first_copy` node in a repeated section stays in its first copy
       only, unscoped: the tables the studies share stand under the first
       study's heading, after its prose (NIEHS-13 Tables 2–5 under "Rats").
   - A copy scoped to one study renders from that study's data
     (`render_common.node_data`, applied where each of the four surfaces
     dispatches a node).
   - A definition states the order of the genomic tissues (`tissue_order`).
   - A definition states whether the abstract names individual genes
     (`abstract_genes`; the 2026 books name gene sets only). A member study's
     abstract is written for its report's definition
     (`load_session_data(..., definition_of=)`).
     The tissues it names come first and the rest follow alphabetically:
     Liver then Kidney in 2023, all alphabetical in 2026. Genomic tables are
     numbered where their section stands, and the tables after them follow.

## Consequences

- Making a published report structurally right is an edit to YAML, reviewed as a
  diff against its era.
- A new study has no study definition, so it uses the definition of a new
  study: the shared template until 2026-10-12, the 2026 generation since (§10).
- The single-file packaging (2018, 2022) needs the emitter, the bundle writer and
  the facsimile to handle the whole-book `book-part` shape.
  `render_capabilities.PACKAGING_PART_ELEMENTS` names the part elements each
  packaging holds. The template loader and the emitter both refuse a part
  that the packaging cannot hold.
- The template's other blocks (filters, charts, chart and layout styles) still come
  from the shared template and the study view; a definition may carry them later.

## Outcome (2026-10-09)

| Definition | Extends | Reports |
|---|---|---|
| `eras/niehs-2023` | `niehs-5day-report` | NIEHS-07 … 10 |
| `eras/niehs-2022` (single-file) | `eras/niehs-2023` | NIEHS-02 … 06 |
| `eras/ntp-rr-2018` (single-file, NTP series) | `eras/niehs-2022` | RR-8 |
| `eras/niehs-2026` | `eras/niehs-2023` | NIEHS-12, 13 (13 moves A.3 before A.2) |

- **Section structure:** RR-8 and NIEHS-02 … 10 match their published books
  exactly.
- **NIEHS-12 and 13** are built over their rat and mouse studies (§9,
  2026-10-11). Their per-species and per-tissue sections are repeats. The
  only remaining difference is content: the study's analytical-method
  sections (Appendix B). `tests/unit/test_report_definitions.py` lists these.
- **Supplemental Data** (2026-10-10, §8): every report lists its deposited
  files in the published sections, file for file. The 2026 G.3 Rats / G.4 Mice
  split comes from the deposit. The file-name rules reproduce the grouping of
  all 672 published entries.
- **The series ISSN** is a per-book fact. NIEHS-02 … 04, 07, 08 and RR-8
  carry 2473-4756; the others carry 2768-5632.
- **Section labels and headings that had been written into content are now
  nodes:**
  - Appendix E's "E.1";
  - NIEHS-10's "A.1 Quantitation of … in Plasma".
  Their labels follow the appendix letter.

## 10. Amendment (2026-10-12): new studies are written to the 2026 generation

The user decided that new reports follow the latest published conventions,
those of NIEHS-12 and 13 (April 2026). A study with no definition of its own
now renders from `eras/niehs-2026` (`document_definition.definition_name`),
in `view_config.build_view_tree` and `study_document_facts`. The shared
template stays the base grammar the eras extend, and the editor's default.

Both 2026 books are whole-body inhalation studies of two species. What they
state only for that reason follows the study's data, not the era:

- **Route gate.** `requires_route: inhaled` keeps a node only for a study
  whose design states that route (`pipeline.study_design`, after its
  sanctioned fallback). The gated nodes are:
  - the vapor generation, vapor monitoring and chamber atmosphere sections;
  - Appendix A (Chemical Characterization and Generation of Chamber
    Concentrations);
  - the Theoretical Inhaled Dose section and its Supplemental Data files.
- **Dose words.** `${dose_term}` and `${internal_dose_term}`
  (`study_design.heading_terms`) give "Exposure Concentration Selection
  Rationale" and "Internal Concentration Assessment" for an inhaled study
  (NIEHS-12, 13). An oral study gets "Dose Selection Rationale" and "Internal
  Dose Assessment" (NIEHS-07 … 10). The books never use the concentration
  words for an oral study or the dose words for an inhaled one. So the words
  are inferred from the route, not stated for an oral study by any 2026 book.
- **A single study.** `study_title` is the title of each study's copy when a
  report covers several studies ("Study Design for ${species}", "${species}").
  A single study's copy keeps the node's own `title`. For "Study Design" that
  is the base title. For an empty title, the parent heading takes in the
  copy's content when the copy is its only child and the parent says nothing
  itself (`document_tree._take_in_untitled`). The prose then stands directly
  under "Animal Condition …", as in every single-study book.
- **Tissue prose.** On a genomics section, `entry_narrative: false` keeps each
  tissue's prose out of the tables block. It stands under the tissue's own
  heading after the tables, in the 2026 order.

The published 2026 studies render unchanged: NIEHS-12 and 13 give
byte-identical text.

What the 2026 books cannot settle for a new study, because both are
two-species inhalation studies, comes from the data. Each item below is an
inference to review:

- the oral dose words;
- a single study without per-species sub-sections;
- the hormone table placed after clinical chemistry (no 2026 book has
  hormone data).

The Gene Set Benchmark Dose Summary section has no generator yet. It renders
as a pending placeholder in every new report until one exists.

