# 0038: Sources are records, text cites them by record, and the reference list is derived from what a report prints

- **Status:** Accepted (2026-11-20).
- **Deciders:** Dan Svoboda
- **Related:**
  - ADR-0029 (per-report document definitions), ADR-0031 (the safeguards
    layer), ADR-0034 (named knowledge bases), ADR-0017 (content provenance);
    Invariant 2 (the document tree drives all structure) and Invariant 3
    (state is derived, never stored);
  - `narrative/sources.py` (the source record, the citation token, the entry a
    list prints, the boilerplate rule), `templates/sources.yaml` (the
    definitions' source library);
  - `rendering/citations.py` (`numbered`: the numbers and the list, derived per
    presented view), called on entry by the five surfaces
    (`html_generator`, `latex_generator`, `docx_generator`, `bits_book`,
    `jats_generator`);
  - `rendering/citations_validate.py` (the citation check and its record),
    `narrative/source_lookup.py` (the DOI system, the addresses),
    `knowledge_base/bibliography.py` (authors and DOIs from a knowledge base's
    own crawl records);
  - `narrative/references_builder.py` (`cited_interpretations`),
    `rendering/latex_export.py`, `rendering/report_compose.py`,
    `narrative/methods_design.py` (`cite_boilerplate` in the Methods);
  - `workflow/engine.py` (`publish_readiness`), `safeguards/publish.py`,
    `safeguards/refusals.py`; `tooling/citations.py`;
  - tests: `tests/unit/test_sources.py`, `test_citations_numbered.py`,
    `test_citations_validate.py`, `test_source_lookup.py`,
    `tests/integration/test_references_integration.py`.

## Context

The finished NIEHS-12 printed 81 references and its text cited five of them.
The other 76 were the papers of the gene-level interpretations, which this
report's definition does not print. Seven papers were listed twice (once for
the rat study, once for the mouse study). No entry had authors. No DOI was
checked against anything. The check that existed (a model's citation points
at a source it was offered) gated nothing and left no record.

The cause was structural. The list was assembled from the stores (the
Background's own list, then each study's papers, renumbered on from one
another) and not from what the report prints. A reference was a string. A
citation was a number typed into text, so a number was only right for one
arrangement of one report.

The requirements, in the maintainer's words (2026-11-20):

- "citations should only be in the citation section when text that cites
  them is present in what is presented to the user, in whatever format."
- "some citations come from the knowledge base. some are inherent to the
  study (boilerplate). some may be websites, or something else. some may be
  inserted by a user at any given stage of editing. there has to be a
  mechanism of keeping track of all this."
- "anything that's boilerplate is, de facto, part of the document
  definition. whether all such content (like citations) should be part of the
  yaml system is up for debate."
- "if the rebuilt published book's contents lack them, they should not be
  there. if the citations are not used in the completed book, it's either
  because our document definition is lacking something, or the AI generated
  text did not use them."

The published books number their references in order of first citation and
print full entries (NIEHS-12: "the procedures of Williams [18, 19] and
Dunnett [20]").

## Decision

### 1. A source is a record

One record per source, with a stable slug, a kind (paper, website, report,
book, dataset, software, other), its origin and its bibliographic parts
(`narrative/sources.py`). Identity decides sameness: the DOI, else the
address, else the entry's words. Two records of one identity are one source,
whatever their origin.

Four origins:

| Origin | Where the record comes from |
|---|---|
| `knowledge_base` | a paper an interpretation was offered and cited; its authors come from the knowledge base's own crawl records (read only) |
| `background` | a public source gathered about the chemical, kept with the Background |
| `library` | a boilerplate source: `templates/sources.yaml` |
| `person` | a source a person added to a study: `sources.json` in its session, with who and when |

### 2. Text cites by record, never by number

A citation in text is the token `[[cite:<slug>]]`. The writers still write
what they always wrote (the Background `[3]`, an interpretation `[P3]`); the
load turns those into tokens against the writer's own list or pool. A number
the list does not have becomes a citation of no source, which is printed as
"Citation pending" and reported.

### 3. The numbers and the list are derived from what is printed

Each surface calls `rendering.citations.numbered(data, tree)` on entry. It
renders the report once to HTML with the tokens left in, which gives the
citations in reading order for exactly the tree of the view being presented,
numbers a source at its first citation, lists the cited sources and no other,
each once, and rewrites the tokens to numbers ("[3]", "[3, 7]").

This is the rule table numbers follow. It follows that a source nothing
printed cites cannot be listed, a paper two studies cite is listed once, and
a view that prints fewer sections has a shorter list. Nothing numbered is
stored.

### 4. Boilerplate sources are part of the definition system

The entries are kept once, in `templates/sources.yaml`, beside the
definitions and era templates (Dunnett 1955 is written once, not in twelve
definitions). An entry may say where the Materials and Methods cite it by
rule (`cited_at`: after the first mention of some words in a subsection), so
the rule-built and model-written Methods cite the statistical procedures the
way the published books do, without the model being asked to. A subsection
that does not use the words does not cite the entry, and an entry no printed
text cites is not listed.

Whether the *use* of every boilerplate citation belongs in YAML is left open
(see Open questions). The method profiles are not the place: a profile's
hash is over its file bytes, and the pins would drift.

### 5. The citation check is an act with a record

`rendering.citations_validate.validate(dtxsid)` reads the report as it is
presented and answers:

| Finding | Severity |
|---|---|
| a citation names no recorded source | error |
| a citation typed as a bare number in a report whose citations are tracked | error |
| the text cites and the definition prints no reference list | error |
| a cited source's entry is incomplete (a paper: authors, title, journal, year, DOI or address) | error |
| a DOI is not registered with the DOI system | error |
| an address answers "not found" | error |
| a citation left unnumbered in the printed report | error |
| a DOI or an address could not be checked | warning |
| a writer cited something outside the sources offered to it (not printed) | warning |
| recorded sources cited only by text the report does not print | note |
| recorded sources no text cites | note |

For a report whose text and list arrive numbered as given (a published book
kept as a session), the check compares as printed: a cited number without an
entry, an entry cited nowhere, a source listed twice are errors.

The check passes when it has no error. The record (`citations_check.json` in
the report's session) holds when, by whom, on which state of the report
(`rendering.kept_render.content_fingerprint`: every file of its sessions and
the definitions they render from), the findings, the list as derived with the
sentences that cite each entry, the recorded sources not listed and why, and
what the check does not judge.

Whether a record still holds is derived, never stored: the fingerprint is
compared with the report as it stands. Any change to the report after the
check (new text, an approval, a re-process) shows the check out of date. The
check is therefore the last act before publishing.

### 6. The publish gate waits for it

`publish_readiness` blocks with `citations` until a check that holds has
passed: `citations_not_checked`, `citations_out_of_date`, `citations_failed`.
Each is an explained refusal. The command line's `--draft` remains the one
named override.

### 7. What is asked of the outside world

Two questions about public identifiers: is a DOI registered (the DOI
system's handle service, which answers for every registration agency), and
does an address answer. The answers are kept in
`OUTPUT_DIR/_source_lookups.json`.

The DOIs of a knowledge base's papers are checked for the knowledge base as
a whole (`tooling/citations.py kb-dois <name>`), never for the papers one
study cites: which papers a study's interpretations cite says something
about what the study found, and the DOI system is a public service. The
check of a study reads those answers and asks nothing about them.

## Consequences

- NIEHS-12 as rebuilt lists 12 references: the Background's five sources and
  the seven boilerplate sources its Methods cite. The 69 papers its
  interpretations cite are recorded and not listed, because its definition
  does not print the interpretations. The check says so.
- A report that prints its interpretations lists their papers once each,
  with authors.
- A report over several studies has one list, in reading order; a study's
  citations are no longer renumbered by an offset.
- The request-body render path and its fixtures, whose references arrive
  numbered, are untouched: `numbered` leaves data with no source and no
  token as it is.
- `references.json` (written at process time) is no longer read by the
  session render path. It is still written, and the request-body path still
  reads it.
- Every report needs a passed check before it can be published. Reports
  checked before a change need the check again.
- The knowledge base `baseline-2026-05` has 4,937 DOIs: 4,936 are registered
  and one is not (`10.1515/pjvs-2017-0085`). A report that cites that paper
  fails its check until a person records the right DOI.

## What the check does not judge

- Whether a source supports the sentence that cites it. That is a question
  of meaning, and its own effort (assertions made by models and people).
- Whether a sentence that cites nothing should cite a source.
- Whether a registered DOI belongs to the work its entry describes. Crossref
  is not reachable from the sandbox; the knowledge base's records came from
  Semantic Scholar with their DOIs.
- A Word file edited outside the application. Deferred by the maintainer
  ("word files later"). Until then, a citation typed as a number in text
  that returns from Word is caught as a typed number once the text is in the
  application.

## Open questions

1. Where the *use* of a boilerplate citation is declared. Today: a rule in
   the library entry (`cited_at`) for the Methods. A definition's own text
   blocks can already cite an entry by token. Whether the Methods' rule
   should move into the era templates is undecided.
2. Whether a check with warnings only (an address out of reach from this
   machine) should open the gate. Today it does, and the record says which
   checks were not made.
3. Whether the check should also hold across an approval (a finer currency:
   the fingerprint of the citations as printed is recorded as
   `print_fingerprint` and not yet used).
4. Inserting a citation while editing text in the application waits for
   in-application editing. `tooling/citations.py add` records a person's
   source and prints the token.
5. The boilerplate of the other books (the outlier procedure, the software
   versions) is not yet in the library.
