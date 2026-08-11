# NLM / PMC StyleChecker — vendored transform (v5.48)

These files are the downloadable **NLM StyleChecker**, the authoritative
validator PMC/Bookshelf run against submitted JATS/BITS XML (see ADR-0004,
"Validation strategy — the Style Checker is the golden gate").

They were fetched **on the host** (the sandbox firewall blocks
`pmc.ncbi.nlm.nih.gov` and the FTP mirror) and vendored here so the gate runs
fully offline through the project's existing `lxml` (libxslt) path.

## Source

- Landing page: https://pmc.ncbi.nlm.nih.gov/pub/stylechecker-info/
- Package:      https://cdn.ncbi.nlm.nih.gov/pmc/cms/files/nlm-style-5.48.tar.gz
- Version:      5.48  (`stylechecker-version` param in `nlm-stylechecker.xsl`)
- Retrieved:    2026-08-08

Archive sha256 (`nlm-style-5.48.tar.gz`):

    b0bc899f345bf7465399b336566b78d9da7c457ad68c8009f8f43f6687c46ea8

## Files (sha256)

    c8c600f2218eaa0217cd8da202ce0c60db24a344318ed2ac542fcffc6badce4a  nlm-stylechecker.xsl
    657e85662ee27675283da17d02d5f3b402e8dd8b427521d301091d27c4460d3b  stylecheck-match-templates.xsl
    27e9c292ff93a4bd0324131a73cae88c52e53ebeae972599acf277fbdcd38cea  stylecheck-helper-templates.xsl
    ac3d88566986813265fb8872399c223a47018f35d9a27fa1abcd7737ccd357b0  stylecheck-named-tests.xsl
    cd605f65de3596219d9bde9a909ede6f245f88e5e2567cdc74d4483cf0056841  style-reporter.xsl

`nlm-stylechecker.xsl` is the entry point; it `xsl:include`s the three
`stylecheck-*.xsl` helpers, so all four must stay together — the transform is
broken if any helper is missing. `style-reporter.xsl` is a separate second-stage
transform: it turns the `<ERR>` document the checker emits into an HTML
error/warning report.

## How it runs (offline, two stages)

1. `nlm-stylechecker.xsl` with stylesheet param `style=article` (also accepts
   `manuscript` / `book`; it auto-sniffs `book` from a `<book-part>` root).
   Output: an `<ERR>` document — a copy of the input with `<error>`/`<warning>`
   elements injected at the offending nodes.
2. `style-reporter.xsl` over that `<ERR>` document → an HTML report.

Both stages run through `lxml.etree.XSLT` (libxslt) — the same engine
`jats_generator.py` already uses. No `xsltproc` binary is required.

## Updating

The Tagging Guidelines and StyleChecker are refreshed quarterly. To bump:
re-download the latest `nlm-style-*.tar.gz` on the host, replace these five
files, and update the version + checksums above.

## License / rights

Produced by the U.S. National Library of Medicine (NCBI/NLM), a U.S. Government
body; the transform is distributed for public use as the PMC submission
validator. Vendored here unmodified.
