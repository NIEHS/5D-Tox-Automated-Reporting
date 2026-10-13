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
- **Dose words.** The headings name the dose as the 2026 books do, whatever
  the route: "Exposure Concentration Selection Rationale" and "Internal
  Concentration Assessment". This was the user's decision (2026-10-12), over
  the oral books' "Dose Selection Rationale" / "Internal Dose Assessment".
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

- a single study without per-species sub-sections;
- the hormone table placed after clinical chemistry (no 2026 book has
  hormone data).

**The genomic results as the books write them** (2026-10-12, the user's
decision). The 2026 books' gene set and gene prose consists of fixed
sentences built from the tables. `rendering.genomics_results` writes those
sentences from the report's numbered tables, with no model:

- the analyses' openings (`gene_set_intro`, `gene_intro`, bound by a genomics
  section's `intro_key`);
- each tissue's results per study, reached through `render_common.node_data`
  as `gene_set_results` / `gene_results`;
- the Gene Set Benchmark Dose Summary (`gene_set_summary`).

The rules are the books' majority wording:

- An item is "reliably calculated" at or above the lower limit of
  extrapolation (lowest dose / 3). One below it is stated apart.
- The gene sets named are the two most potent, plus any tied with the
  second.
- Genes are listed upregulated first, then downregulated. The special forms
  are "One gene, …", "All 10 of …", "Half of …" and "Only eight genes met
  the criteria".
- Symbols are in italics (a new `italic` inline unit) and the L of BMDL is a
  subscript (`sub`).
- Each gene's name is NCBI Gene's, from a version-controlled cache
  (`assets/gene_names.json`, `genomics.gene_names`). Filling the cache sends
  the study's genes to NCBI, so it fails closed unless
  `BMDX_ALLOW_NCBI_GENE=1`, like Enrichr. A gene without a cached name prints
  "[Placeholder: gene name]".
- The test article's short name ("1,4-DCB", `--compound-name`) is recorded
  in `identity.json` as `abbreviation`.

The 2026 era binds these keys in place of the model-written tissue
interpretation. The earlier eras still print the interpretation.

**Comparison with the published books.** Of NIEHS-13's 50 genomic-results
sentences, 38 are identical. Of NIEHS-12's 52, 37 are identical. The rest
differ for these reasons:

- The books word the same sentence two ways; we use the majority form
  ("exhibiting an increase in expression" against "upregulated genes with a
  calculated BMD").
- NCBI has renamed some genes since publication ("HLF transcription factor,
  PAR bZIP family", where the book has "hepatic leukemia factor").
- The books add alias symbols ("Car3/Ca3").
- NIEHS-12 has a typo ("… and …, and …").

**The deposit's address.** A published book opens its Supplemental Data
with the deposit's DOI. A new study has no DOI until the publishing package
is created. Until then the appendix names a LOCAL url, the study's
supplemental folder `sessions/<id>/supplemental/`. The app serves that
folder (`web_routes.supplemental_routes`; `BMDX_LOCAL_URL` overrides the
`http://127.0.0.1:9000` server address).

- With no recorded deposit, the lists are the folder's files, each linked to
  its own local url.
- A list with no file of its kind says it is filled from the deposit when
  the package is created.
- When the study states its DOI (`deposit.yaml: doi`), every local url is
  replaced (`pipeline.deposit.load_deposit` / `deposit_address`). The
  package's file references are the files' own names.

**The genomic appendices** (2026-10-13). The 2026 era's Appendix D.2 and E
now have the books' shape, built from the data (`rendering.genomics_appendix`).

- **D.2 Empirical False Discovery Rate.** The Methods is the books' paragraph
  (`efdr_methods`). The Results is the summary sentences (`efdr_results`) and
  the table "Empirical False Discovery Results" (`appendix_efdr_matrix`), in
  place of the 2023 boxplots. The data is the study's synthetic-null analysis
  (`genomics.efdr`, the session's `efdr.json`), which is recorded from the
  deposit's `*_eFDR_Synthetic_Null_Analysis.zip` when `--deposit` names it.
  - Gene eFDR is the share of the analysed genes that pass the gene
    analysis's filters in each null experiment. The universe comes from the
    Fisher tail, K/U.
  - GO eFDR is the processes active by the profile's `go_display` criteria.
    The GO universe is not in the export, so a null experiment with active
    processes prints a pending cell.
  - The Methods names whose control data were used only when the null
    analyses' doses are the study's own.
- **E Gene Set and Gene Definitions.**
  - One table per tissue (`repeat: genomic_organs`) gives its top gene sets
    with their GO term definitions, from `go-basic.obo` (`genomics.go_definitions`).
    The file goes in `resources/go/go-basic.obo`, or the path in `BMDX_GO_OBO`.
  - One table per study (`repeat: study_species`) gives the genes of its top
    gene tables with their Entrez and probe ids.
  - A repeated table takes its own matrix from a `by_organ` / `by_species`
    mapping (`render_common.scoped_value`).
  - The gene definitions (the books' human UniProt function) have no source
    yet and print a placeholder.

Comparison with the NIEHS-13 book:

- The gene identifier tables list the book's genes exactly: 47 rat, 45 mouse.
- 9 of 10 eFDR means match. Mouse liver is 0.04 against the book's 0.05.
- The book's rat ranges cannot be right: each is below its own mean ("0.02",
  "0–0.005"). They look like the maxima divided by the 20 experiments.
- NIEHS-13 deposited NIEHS-12's synthetic-null analysis. The two zips are
  identical, the null doses are 1,2-DCB's, and the NIEHS-13 Methods itself
  says "1,2-dichlorobenzene". Two livers were run on yet another design.
- Our criteria find 8 active GO processes in one rat heart null experiment,
  all from one probe shared by eight RT1 genes. The book reports 0.

