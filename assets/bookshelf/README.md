# Vendored NCBI Bookshelf stylesheet (optional fidelity override)

`rendering/bookshelf_preview.py` renders our BITS `<book>` into a Bookshelf
reader-view **lookalike**. By default it inlines a built-in stylesheet calibrated
by eye. If a file named **`bookshelf.css`** exists in *this* directory, it is
inlined **instead**, so a copy of NCBI's real book stylesheet tightens the
appearance with no code change.

This file is **not** vendored here because the sandbox is bot-blocked from
NCBI (the page fetch returns a reCAPTCHA interstitial), and the live book pages
load their CSS via NCBI's concatenated portal bundle rather than a single
`<link rel="stylesheet">`. Grab it on a host with a normal browser:

## How to capture it (host, ~2 min)

1. Open a real book **content** page (not the TOC), e.g. a chapter of NIEHS
   Report 10: <https://www.ncbi.nlm.nih.gov/books/n/ntpniehs10/bp2/>
2. Open DevTools → **Network** → filter **CSS**, reload the page.
3. Save every stylesheet the content page loads (the NCBI core + book stylesheets;
   the portal bundle also injects rules — "Copy → Copy styles" or saving the
   computed stylesheet works). Concatenate them into a single file.
4. Save it as `assets/bookshelf/bookshelf.css` in this repo.
5. Re-render — no code change needed:
   ```
   python -m tooling.bookshelf_preview output/DTXSID50469320-report.xml
   ```
   or re-materialize the in-app preview (`surface=bookshelf`). `_stylesheet()`
   picks up the vendored file automatically.

## Scope / honesty

Keep this to the **content-column** CSS. Do **not** vendor NCBI's masthead,
portlet, or branding markup — reproducing NCBI/NIEHS chrome would make the page
read as a real NCBI page (impersonation). The preview is deliberately a
content-only lookalike with its own neutral header and a "preview" banner.
