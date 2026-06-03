# NIEHS Biological Potency Report — Overleaf Bundle

This zip contains a LaTeX render of an NIEHS biological potency report
generated from session data.  Drop it into Overleaf to compile.

## How to use this bundle

1. Go to <https://www.overleaf.com> and sign in.
2. Click **New Project → Upload Project** and select this zip file.
3. Overleaf extracts the files and opens the project.
4. Click **Recompile** (top of the editor) — the PDF appears in the right
   pane.

The main file is `main.tex` (Overleaf's default main document) — it holds the
preamble and `\input`s `report.tex`, which carries the report body.  Edit the
prose in `report.tex`.  The class file `niehs.cls` defines the NIEHS styling
(page geometry, table layout, footnote chrome) and lives alongside; you don't
need to touch it.

## What's in the bundle

| File                | Purpose                                                |
|---------------------|--------------------------------------------------------|
| `main.tex`          | Entry document: preamble + `\input{report}`.  Compile this. |
| `report.tex`        | The report body.  Edit this in Overleaf to revise prose.|
| `niehs.cls`         | NIEHS document class.  Hand-edit only for style tweaks.|
| `figures/`          | Genomics charts (UMAP, cluster scatter) as PDFs.       |
| `README.md`         | This file.                                             |

## What's complete and what's pending

This is a generated report from an in-progress migration to LaTeX.  Some
sections render their real content, others appear as visible placeholders
flagged with `[Section pending: ...]`.  Search the .tex for that string
to find every gap; each one will be filled in as the migration progresses.

Currently rendered with real content (when session data exists):

  - Foreword, About This Report, Peer Review, Publication Details,
    Acknowledgments
  - Background
  - Summary, References

Currently rendered as placeholders (next implementation passes):

  - Cover page (deliberately deferred — replaced with `\maketitle`)
  - Materials and Methods subsections
  - Results tables (apical dose-response, BMD summary, genomics)
  - Tables list
  - Appendices

## Editing the report

Overleaf's editor is the intended authoring surface.  Edit prose directly
in `report.tex`.  Changes to the document structure (adding sections,
reordering) should not be made in the .tex — those are driven by
`document_tree.py` in the source repo and the .tex regenerates from it.

## Regenerating the bundle

When session data updates (new BMD analysis, fresh narrative), re-export
from the source app to get a fresh zip.  This is a one-way hand-off:
edits made in Overleaf do not flow back to the source session.

From a developer terminal in the source repo:

```
# Scaffold-only bundle (structural skeleton, no chemical-specific data)
uv run python -m latex_export

# Real-session bundle — overlays cached state from sessions/<dtxsid>/
uv run python -m latex_export --session --dtxsid DTXSID50469320
```
