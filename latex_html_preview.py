r"""
latex_html_preview.py — LaTeX → HTML rendering for in-app previews.

After the Typst → PDF pipeline was retired (2026-05-19, "no PDFs, no
Typst" mandate), the web app's preview iframes need to show the report
content without going through a PDF.  This module is what bridges the
new LaTeX renderer and those preview iframes.

Pipeline
--------

    generate_latex(data, section_filter=…)   ← .tex source
        │
        ▼
    _preprocess_for_pandoc(tex)              ← swap niehs.cls + niehstable
        │                                       for plain LaTeX equivalents
        ▼
    pandoc -f latex -t html5 --standalone    ← subprocess
        │
        ▼
    html string  → /api/preview-latex-html   ← what the iframe srcdoc gets

Why pandoc and not a custom renderer
-------------------------------------
pandoc is a well-maintained universal document converter that handles
the bulk of standard LaTeX cleanly — sections, paragraphs, tabular,
hyperlinks, lists.  Writing a parallel LaTeX-to-HTML walker just for
the preview path would duplicate ~400 lines of tree-walk logic with
no offsetting benefit.  Pandoc's known weakness (custom .cls handling)
we work around with a small preprocessor.

Why preprocessing
-----------------
The generated .tex starts with `\documentclass{niehs}` and uses the
custom `\begin{niehstable}{id}{caption}` environment.  pandoc has no
knowledge of either, so we substitute them for stock LaTeX equivalents
before invoking pandoc:

  - `\documentclass{niehs}`             → `\documentclass{article}`
  - `\begin{niehstable}{id}{caption}`   → `\begin{table}\caption{...}\centering`
  - `\end{niehstable}`                  → `\end{table}`
  - `\listoftables`, `\tableofcontents` → stripped (fragment previews
                                          have no body to enumerate)

The visual fidelity in the preview is intentionally lossy compared to
what Overleaf will render — this is an iteration aid, not a publishing
preview.  The Overleaf bundle (built from the unmodified .tex) is the
source of truth for the final rendered output.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from typing import Optional

from latex_generator import generate_latex


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Hard upper bound on a single pandoc compile.  Even a full-report .tex
# (~700 lines) finishes in under a second; if pandoc is wedged for
# 30s something is wrong and we'd rather fail loud than hang the UI.
_PANDOC_TIMEOUT_SEC = 30

# Pattern for our custom niehstable environment opener.  Matches the
# two-argument form the generator emits:
#   \begin{niehstable}{<table-id>}{<caption>}
# Caption may contain spaces, periods, em-dashes — anything except
# unbalanced braces.  We don't try to handle nested braces in the
# caption; the generator doesn't emit them.
_NIEHSTABLE_OPEN_RE = re.compile(
    r"\\begin\{niehstable\}\{([^}]*)\}\{([^}]*)\}"
)


# ---------------------------------------------------------------------------
# Helpers (private)
# ---------------------------------------------------------------------------

def _preprocess_for_pandoc(tex: str) -> str:
    """
    Rewrite custom-class constructs in the generated .tex so pandoc can
    render them as plain LaTeX.

    Substitutions:
      - documentclass{niehs} → documentclass{article}.  pandoc reads
        the class to decide which preamble to honour; it doesn't have
        a parser for our niehs.cls.
      - \\begin{niehstable}{id}{caption} → \\begin{table}\\caption{caption}\\centering.
        pandoc treats the opaque "niehstable" as an unknown env and
        emits its contents as a div, which loses the table semantics
        (no <table> tag in the HTML output).  Rewriting to the stock
        `table` float restores the <table>+<caption> structure.
      - \\listoftables, \\tableofcontents → removed.  Fragments don't
        contain the body the lists would enumerate; pandoc otherwise
        emits an empty bullet list, which looks broken in the preview.
    """
    # Class swap.  Anchored on the literal string — niehs.cls is the
    # only document class our generator emits.
    out = tex.replace(r"\documentclass{niehs}", r"\documentclass{article}")

    # niehstable env: open and close substituted independently.  The
    # opener carries the caption which we splice into a \caption call;
    # the id (first capture group) is dropped because pandoc doesn't
    # produce LaTeX-style \label cross-references in HTML output.
    out = _NIEHSTABLE_OPEN_RE.sub(
        lambda m: rf"\begin{{table}}\caption{{{m.group(2)}}}\centering",
        out,
    )
    out = out.replace(r"\end{niehstable}", r"\end{table}")

    # Strip TOC-building commands.  pandoc can't fill them from a
    # fragment, and we don't want their failure modes in the preview.
    out = re.sub(r"\\listoftables\b", "", out)
    out = re.sub(r"\\tableofcontents\b", "", out)

    return out


def _run_pandoc(tex_pandoc_ready: str) -> str:
    """
    Run pandoc on the preprocessed .tex and return the HTML output.

    Raises RuntimeError if pandoc is not installed or returns an error;
    the caller surfaces that as a 500 in the API so the frontend can
    show a sensible error message instead of a blank iframe.
    """
    if shutil.which("pandoc") is None:
        raise RuntimeError(
            "pandoc is required for in-app LaTeX previews but was not "
            "found on PATH.  Install it via your distro's package "
            "manager (e.g., `pacman -S pandoc` on Arch)."
        )

    result = subprocess.run(
        ["pandoc",
         "--from=latex",
         "--to=html5",
         "--standalone",
         # Inline math via katex would slow each preview down without
         # adding meaningful value for our content (we don't render
         # equations).  Stick to default text-mode rendering.
         ],
        input=tex_pandoc_ready,
        capture_output=True,
        text=True,
        timeout=_PANDOC_TIMEOUT_SEC,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"pandoc exited {result.returncode}: {result.stderr.strip()[:400]}"
        )
    return result.stdout


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_html_preview(
    data: dict,
    section_filter: Optional[str] = None,
) -> str:
    """
    Render the report (or a single subtree of it) to a stand-alone HTML
    string suitable for an iframe srcdoc.

    Args:
        data:           The report data dict — same shape generate_latex
                        consumes (the output of marshal_export_data).
        section_filter: Optional DocNode id.  When set, only that
                        subtree renders — same semantics as
                        generate_latex's section_filter (decision #10).

    Returns:
        A complete HTML document string.  The caller is responsible for
        setting Content-Type: text/html when serving it.
    """
    tex = generate_latex(data, section_filter=section_filter)
    tex_pandoc = _preprocess_for_pandoc(tex)
    return _run_pandoc(tex_pandoc)
