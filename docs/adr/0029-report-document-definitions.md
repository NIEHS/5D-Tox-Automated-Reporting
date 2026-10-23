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
- **Dose words.** The headings name the dose by the study's route. The
  definition's `dose_terms:` block gives the words per route, and they fill
  `${dose_term}` / `${internal_dose_term}` in the titles
  (`document_tree.dose_term_values`). By gavage: "Dose Selection Rationale",
  "Internal Dose Assessment" (NIEHS-07 … 10). By inhalation: "Exposure
  Concentration Selection Rationale", "Internal Concentration Assessment"
  (NIEHS-12, 13). A route the definition names no words for (dermal, feed …)
  prints a placeholder rather than another route's words. This is the user's
  decision (2026-10-19). It supersedes the concentration words for every
  route (2026-10-12).
- **Sections about data the study lacks.** `drop_when_uncollected: true`
  with `requires_platform` leaves a section out, subtree included, when the
  study collected none of that data. Without the flag, the section stays and
  states `not_collected_text`. In the 2026 era the Internal Dose Methods
  subsection, Results section and appendix carry the flag, so a study with
  no Tissue Concentration has none of them, as NIEHS-02 … 06 have none. The
  later appendices take the freed letter. This is the user's decision
  (2026-10-20).
- **Organ Weight Descriptions.** The appendix describes the organs the study
  weighed (its integrated organ-weight endpoints, not the report's table,
  which a view may narrow) and the tissues it sequenced. The texts are the
  definition's `organ_descriptions`, in `organ_description_order`
  (`rendering.organ_descriptions`). The rule reproduces all eleven books'
  lists. The 2026 era orders them alphabetically.
- **Foreword.** A definition states the series' Foreword (`foreword:`, its
  paragraphs, with `[text](url)` links). The shared template's is the
  2022–2023 books' text. `eras/niehs-2026` states the 2026 books' rewording:
  no "The NIEHS Report series began in 2022", and "This report is available
  … on the NIEHS website".
- **The proposed standard.** `eras/niehs-proposed` extends `eras/niehs-2026`
  with sections no published book has, and is the definition of a new study
  (`DEFAULT_DEFINITION`). The published 2026 books keep extending
  `eras/niehs-2026`. A study a report composes (NIEHS-12/13's `_rat` /
  `_mouse`) takes its report's definition. This is the user's decision
  (2026-10-21): the gene set figures are "proposed standards moving forward".
  What it adds:
  - under Gene Set Benchmark Dose Analysis, "Gene Ontology Semantic Map" and
    "Gene Set Clusters": an opening paragraph, then a figure per genomic
    analysis (`repeat: genomic_analyses`, a tissue of one sex), its image
    the Process step's chart for that analysis (`rendering.genomic_figures`);
  - a list of the body's figures after the list of tables;
  - an appendix, "Gene Ontology Semantic Map and Gene Set Clusters"
    (`cited_as: genomic-figures-appendix`, which the opening paragraphs
    cite): how the map and its semantic clusters were derived (anc2vec →
    UMAP → HDBSCAN, settings the map's file does not record left as a
    placeholder), how the gene set clusters are made, how the two relate,
    and per analysis two membership tables — every active gene set with both
    of its clusters, by gene set cluster and by semantic cluster.
  Their wording is `phrasing.genomic_figures`, proposed for review. On the
  HTML and Bookshelf surfaces the figures are inline SVG, each marker titled
  with its GO term (the hover text); print surfaces take the PNG.
- **A figure per analysis.** `repeat: genomic_analyses` makes one copy per
  tissue × sex (× study), scoped by `scope_analysis` ("liver-male",
  `document_tree.analysis_key`); a payload keyed `by_analysis` gives each
  copy its own (`render_common.scoped_value`). Figures may repeat, as
  sections and tables do.
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


## 11. Amendment (2026-10-13): the generated prose's words are declared

The sentences of §10 were first written as strings in the renderer. That left
an era's wording in Python: a definition that words a sentence differently
would have needed a code change. The user's rule is that everything is
specified either by a rule or by the document definition.

- **Rule or word.** The code keeps the rules: which gene sets are named,
  which form a gene list takes, when a group is named, the lower limit of
  extrapolation, whose control data the eFDR names. The words are the
  definition's `phrasing:` block, one template per sentence with `{fields}`
  the rule fills (`document_model.phrasing`). This covers:
  - the gene set and gene results, openings and summary;
  - the eFDR methods and results sentences, and the eFDR table's caption,
    headers and footnote;
  - the gene set and gene definition tables' captions, headers and
    footnotes;
  - the words the sentences use: number words, statistic names,
    directions, "both" / "all three", singular and plural nouns;
  - the two percentages the eFDR results' wording names ("<1%", "below
    0.5%").
- **Closed schema.** The block is checked at load. An unknown key, a field
  the rule does not supply, or a mis-shaped word list fails loudly. A key a
  definition leaves out prints a visible placeholder naming it.
- **Inherited.** `extends` deep-merges the block, so a study re-words one
  sentence by stating only that key. The 2026 era states the whole block.
  The earlier eras state none, and their reports write none of these keys
  (they bind none).
- **What is cited.** The prose cites an appendix by letter and tables by
  number. A node declares what it is cited as: `cited_as:
  supplemental-data`, `gene-set-summary-table`, `efdr-table`
  (`document_tree.find_cited`). The code knows no node ids.
- **Method facts are the method profile's.** How the eFDR's synthetic null
  data were made (the generator, its address, the distribution, the values
  drawn per probe) is a fact of the method, not wording. It is the profile's
  `genomics.efdr` (ADR-0027 amendment). A profile that does not state it
  prints placeholders.

NIEHS-12 and 13 render text-identically before and after.

Still in code, as language rather than era wording:
- the serial list ("a, b, and c");
- the BMD and dose number formats;
- the `*x*` / `BMD_L` inline markup;
- the system placeholders.

## 12. Amendment (2026-10-13): a session pins its definition

Era files change as the tool learns the books. A finished report must not
change with them. The user decided that definitions are pinned like method
profiles (ADR-0027) (`document_model.definition_pin`):

- **The pin.** `sessions/<id>/document_definition.json` holds the name and
  content hash of the composed definition (every `extends` resolved).
  `document_definition.yaml` holds the composed definition itself.
- **TRACK** (the default) renders from the current files. The pin records
  what the report rendered from. A change re-pins, and the previous pin and
  snapshot are kept under `history/_document_definition/`. Process and
  `generate_report` keep the pin current.
- **FIXED** (`generate_report --document-definition fixed`) renders from the
  snapshot. `definition_name` returns `@pinned/<id>`, and
  `document_template._load_raw` reads the snapshot, so the tree, the series
  facts and the phrasing all come from it. `drift` reports when the files
  have moved on. An edited snapshot fails loudly. Re-pinning takes up a
  revised definition.
- **Outside the pin:** the content files a node names, and the renderers'
  code. Rules that change in code are kept as named implementations that the
  definition selects (docs/writing-rules-inventory.md).

The published reproductions still TRACK, because they are still being
refined toward the books. Each is fixed when it is final.

## 13. Amendment (2026-10-13): each published report has its published content as a companion

The user asked that each app-generated published report have, as a
companion, a clone of the published report's *content* (not the
Bookshelf page's chrome), as a session in the app.

- **The companion is a definition plus content.** `tooling.published_clone`
  reads the book's Bookshelf bundle (`rendering.published_clone.clone_book`)
  and writes `sessions/<twin>_published/`:
  - `document.yaml`: the book's structure as node entries, in the book's
    order, with node ids taken from the published ids. It is validated as a
    full tree build.
  - `published_content.json`: each node's content, the book-level facts
    (title, report number, date, authors, series, abstract) and each table's
    and figure's published label.
  - `published_clone.json`: the report, the twin, the bundle and its hash,
    and the clone format.

  `latex_export.load_session_data` lays this content over the scaffold for
  such a session, so it renders through every surface unchanged. It is a
  declaration, not a renderer branch.
- **Numbering is checked, not forced.** Tables and figures keep positional
  numbers (Invariant 2). `--check` compares every number the tree gives with
  the book's label and fails on any difference. All twelve books number as
  published.
- **General rules this brought in, for every report:**
  - **Front-matter objects.** A table or figure in the front matter is
    unnumbered and leaves the body's sequence alone (NIEHS-12/13's
    unlabelled "Author and Contributor Roles and Definitions").
  - **Untitled narratives.** An untitled narrative is a run of paragraphs
    in its parent: there is no `<sec>` and no empty heading.
  - **Inline units.** A paragraph, a cell, a caption or an abstract part may
    carry inline units: sup, sub, italic and bold, as well as links.
  - **Matrices.** A matrix may have several header rows.
  - **Lettered notes.** A lettered table note carries `<label><sup>`, or a
    plain label when the note says so.
  - **Collaborations.** A roster author with `members` is a collaboration
    (`<collab>`, RR-8).
  - **Verbatim front matter.** A front part marked `verbatim` is printed as
    given, without the roster.
- **Measured (`python -m tooling.published_clone --check`, 2026-10-13).**
  99.9–100% of the words match in every book. RR-8 matches with no block
  different. What is left is stated:
  - **The book title's ®.** It is a superscript in the books; our title is
    plain text.
  - **MathML formulas** (NIEHS-07…10, 2 each). They are written as a line of
    text: a fraction is "a / b", followed by the equation number.
  - **NIEHS-03's figure labels.** The book writes them in the caption; the
    clone moves them to the label.
