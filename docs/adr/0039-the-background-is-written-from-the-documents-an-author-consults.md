# 0039: The Background is written from the documents an author consults

- **Status:** Accepted (2026-11-23).
- **Deciders:** Dan Svoboda
- **Related:**
  - ADR-0038 (citations are records, and the list is derived);
  - `narrative/agency_sources.py` (the documents and how each is found),
    `narrative/source_fetch.py` (reading and keeping a document),
    `tooling/browser_document.py` (the browser a site that refuses a program
    is asked with);
  - `narrative/data_gatherer.py` (`gather_documents`, `BackgroundData`),
    `narrative/background_writer.py` (the prompt's numbered documents,
    `cited_source_records`), `narrative/sources.py` (`background_sources`,
    `format_entry`);
  - `tests/unit/test_agency_sources.py`.

## Context

The rebuilt NIEHS Report 12 listed 12 references; the book lists 38. Of the
book's 13 Background sources, the writer had been offered two (ATSDR's profile
and EPA's IRIS summary, each as a web line) and three others (PubChem, an OSHA
page, the NIOSH Pocket Guide). It cited everything it was offered. The other
eleven were never offered: the gatherer had no step for them, one of its steps
asked PubChem for a heading that no longer exists and swallowed the refusal,
its paper search (two fixed Semantic Scholar queries) returned off-topic
papers or nothing, and EPA's CompTox service had moved from the address it
called.

The maintainer's rule (2026-11-23): **first understand what a human author
would have done, and do that; what only a model can do comes after.**

What the authors did was read from the Background of all twelve published
books (95 references):

| Books | What the Background cites |
|---|---|
| RR-8, NIEHS-02 to 06 (2018, 2022) | 5 to 7 journal papers, and one EPA fact sheet the 2022 books share |
| NIEHS-07 to 10 (2023), little-studied chemicals | EPA's CompTox dashboard, the PubChem summary, the ECHA substance card, 2 to 4 papers |
| NIEHS-12, 13 (2026), well-studied chemicals | the agency documents: ATSDR's profile, OSHA's Table Z-1, ACGIH, the IARC monograph, an NTP report, EPA documents, a state agency, OECD or EU where one exists; 1 to 3 papers |

Journal papers are the largest group (50 of 95; 48 have a PubMed ID). An
author cites each limit to the body that set it, and each assessment to the
document itself, never to a database that repeats it.

## Decision

1. **The gatherer consults the documents of the authors' routine, each found
   from the chemical's public identifiers.** `narrative/agency_sources.py` has
   one function per document. None names a chemical:

   | Document | Found by |
   |---|---|
   | PubChem compound summary | the compound's PubChem ID |
   | EPA CompTox Chemicals Dashboard | the DTXSID, through EPA's data service (`CTX_API_KEY`) |
   | ATSDR toxicological profile | ATSDR's list of minimal risk levels by CAS number, then the substance page, then the profile page and its chapters |
   | OECD SIDS initial assessment | OECD's Existing Chemicals Database, searched by CAS number |
   | EPA IRIS summary | the address PubChem's record gives |
   | IARC monograph | IARC's entry in PubChem's record (group, volume, address), then the volume's page |
   | NTP technical reports | NTP's entries in PubChem's record (number, title, year, conclusions, address), then the abstract page |
   | OSHA limit | the row of 29 CFR 1910.1000, Table Z-1, with the CAS number, from the Code of Federal Regulations |
   | NIOSH Pocket Guide | the address PubChem's record gives |
   | ACGIH Data Hub | ACGIH's site search by CAS number |
   | EPA drinking water limits | the chemical's row in the National Primary Drinking Water Regulations, by name |
   | Papers | PubMed: the chemical's names in the title, with toxicity, metabolism, kinetics or poisoning as the subject, in a laboratory mammal or humans; the most relevant first, with abstracts |

2. **A document is a reference record and a text.** The record is the entry a
   reference list prints (ADR-0038 fields): the issuing body as author, the
   document's title, where and when it was published, the address read and the
   day it was read. The text is the part of the document a Background draws on
   (for ATSDR: the chapter on relevance to public health and the sections on
   toxicokinetics and mechanisms). The model is given each text under its
   reference number and told to cite a statement to the document that states
   it, and a limit or a classification to the body that set it.

3. **The Background keeps its cited sources as records.** `background.json`
   gains `sources` (each record with the number `n` the text cites it by)
   beside the printed `references` lines; the report's reference list is built
   from the records. A Background saved before this decision (lines only)
   reads as before.

4. **What was read is kept, with the day it was read.**
   `OUTPUT_DIR/_background_documents` holds each document for a month. A
   second Background of the same chemical asks no site again, and an entry's
   "Accessed" date is the day the document was read.

5. **A site that refuses a program is asked with a browser.** A plain request
   first; on a refusal (403, 429, 503) or no answer, the same address through
   a real browser window run as its own process. Needed today for NIOSH; ATSDR's
   document host, OSHA and ECHA also refuse a plain request at times.

6. **Not found is not unreachable.** A document that does not exist for a
   chemical is absent, with a note where the absence is itself informative (no
   ATSDR profile, no IRIS assessment). A site that could not be read is named
   in `unreachable_sources`; the refusal to write a Background without ATSDR
   and IRIS (`safeguards.sources`) is unchanged.

7. **Only public identifiers leave.** An address carries the chemical's CAS
   number, name, or a database's own id. Nothing of a study's data is sent.

## Consequences

- NIEHS-12's Background is offered 11 documents and 14 papers, where it was
  offered 5 sources. The three kinds of fact the old steps got wrong or
  missed are now read from their documents: the OSHA limit as a ceiling, the
  ACGIH limit (was a fixed "subscription required" note), the drinking water
  limits (the PubChem heading asked for no longer exists).
- The Semantic Scholar paper search and the direct calls to the old CompTox
  address are gone from the gatherer.
- A first Background of a chemical takes longer (ATSDR's chapters are large,
  and a browser fetch takes about half a minute); later ones read the kept
  copies.
- The entries are built from what each site prints. A site that changes its
  pages breaks one finder; the failure is a note on that document and the
  rest are still gathered.

## Not decided here

- **The books' one-off sources.** A state fact sheet (New Jersey, New York,
  California), an EPA technical factsheet or pesticide notice, an EU
  regulation: the authors chose these per chemical, and no rule finds them. A
  person can add one as a source (`tooling/citations.py add`); the writer
  would not see it.
- **The ECHA substance card** of the 2023 books is not consulted yet (its site
  answers only a browser, after a bot check).
- **The Background's shape.** The prompt still asks for seven paragraphs, one
  of them a data-gap analysis, and the text runs to several times a book's
  length. No published Background has that paragraph. Bringing the shape in
  line with the books is a separate decision.
- **Whether a statement is supported by the document it cites** is the
  correctness-of-meaning effort, not this one.
