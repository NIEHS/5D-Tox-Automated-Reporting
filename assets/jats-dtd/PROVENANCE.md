# NISO JATS 1.3 Archiving DTD — vendored module set

The NISO JATS (Z39.96-2021) **Journal Archiving and Interchange DTD v1.3** plus
its complete transitive module set (MathML 2.0, ISO 8879 / 9573-13 / xmlchars
character entities, the XHTML and OASIS table models).

## Why it's here

`jats_stylecheck.dtd_validate()` validates emitted JATS against this DTD's
**content model** — the check the **PMC Article Previewer** performs and the NLM
StyleChecker does **not** (StyleChecker checks tagging-guideline conformance, not
the grammar).  The gap is real: a document can be StyleChecker-clean yet DTD-
invalid.  A live Previewer upload (2026-08-10, TM Session 20024487) failed with

    element body: validity error : Element body content does not follow the DTD,
    expecting (( ... | table-wrap | ... )* , sec* , sig-block?), got
    (sec sec ... table-wrap sec ... )

because data-table `<table-wrap>`s were emitted interleaved among `<sec>`
siblings.  Vendoring the DTD lets that class of error be caught offline in CI.

## Source

- Entry DTD: https://jats.nlm.nih.gov/archiving/1.3/JATS-archivearticle1-3.dtd
- All modules fetched from the same base URL (`https://jats.nlm.nih.gov/archiving/1.3/`)
  and its relative subdirs (`mathml/`, `iso8879/`, `iso9573-13/`, `xmlchars/`).
- Version:   JATS v1.3 (ANSI/NISO Z39.96-2021)
- Retrieved: 2026-08-10

Fetched **on the host** originally would be firewalled, but `jats.nlm.nih.gov`
happens to be reachable in-sandbox; the module set was pulled by iteratively
resolving each `failed to load` reference from the entry DTD.

## How it runs (offline)

`dtd_validate(xml)` pins CWD to this directory and parses with
`lxml.etree.XMLParser(load_dtd=True, dtd_validation=True, no_network=True,
resolve_entities=True)`, so the entry DTD's relative SYSTEM ids resolve against
the vendored files with **no network**.  Returns the content-model errors (empty
= valid).  All files must stay together — a missing module surfaces as a
`failed to load` error, signalling the set is incomplete (guarded by
`test_jats_dtd_assets_present`).

## Refresh

Re-fetch the entry DTD and re-run the iterative "fetch every `failed to load`
module" loop until `dtd_validate` on a known-valid document returns no errors.
Update the version + retrieved date above.
