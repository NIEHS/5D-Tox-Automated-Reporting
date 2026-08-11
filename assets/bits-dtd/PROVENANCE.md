# NISO BITS 2.0 Book Interchange DTD — vendored module set

The NLM/NISO **Book Interchange Tag Suite (BITS) v2.0** DTD plus its complete
transitive module set.  BITS reuses the JATS 1.x content modules (para, section,
table, math, references, char entities) and adds the book-specific modules
(`BITS-book2`, `BITS-bookmeta2`, `BITS-book-part2`, TOC/index).

## Why it's here

The reports are published on NCBI Bookshelf as BITS **`<book>`**s, not journal
`<article>`s — confirmed from the real published reference (NIEHS Report 10 =
NBK589955, `output/published.xml`): its parts are served as book front-matter
(`foreword1`, `fm-peer`, `fm1`, `ack1`) and body-parts (`bp2`/`bp3`/`bp4`).  The
export surface pivoted from JATS `<article>` to BITS `<book>` accordingly.

`jats_stylecheck.dtd_validate(xml, grammar="book")` validates the book export's
**content model** against this DTD — the check NCBI's pipeline runs and the
StyleChecker does not.  It caught the same `<table-wrap>`-after-`<sec>` ordering
class of error for the book body model
(`(block)*, sec*, (book-part | xi:include)*`) in testing.

## Source

- Entry DTD: https://jats.nlm.nih.gov/extensions/bits/2.0/BITS-book2.dtd
- Version:   BITS v2.0 (20151225)
- Modules fetched from the same base (`.../extensions/bits/2.0/`) plus the JATS
  archiving base (`https://jats.nlm.nih.gov/archiving/1.3/`) for the shared
  JATS-*1 modules, and the MathML/ISO char-entity subtrees (`mathml/`,
  `iso8879/`, `iso9573-13/`, `xmlchars/`) — the latter are byte-identical to the
  ones under `../jats-dtd/` and were copied from there.
- Retrieved: 2026-08-10

## How it runs (offline)

`dtd_validate(xml, grammar="book")` pins CWD to this directory and parses with
`lxml.etree.XMLParser(load_dtd=True, dtd_validation=True, no_network=True,
resolve_entities=True)`, so the entry DTD's relative SYSTEM ids resolve against
the vendored files with **no network**.  Verified: a minimal book with a table
and a Greek char entity validates clean offline.  All files must stay together —
a missing module surfaces as a `failed to load` error.

## Refresh

Re-fetch `BITS-book2.dtd`, then run the iterative "fetch every `failed to load`
module" loop (network on for fetch, validation stays no_network) until a known-
valid book validates with no errors.  Update the version + retrieved date above.
