r"""
test_latex_to_html.py — the conservative LaTeX→HTML translator (ADR-0005,
divergence #2 Phase B).

The translator's contract is deliberately narrow: render the prose vocabulary
the generator emits into editable regions, and return None for ANYTHING else so
the preview degrades to a "may be stale" marker instead of emitting broken HTML.
These tests pin both halves — what it renders, and what it refuses.
"""

import pytest

from roundtrip.latex_to_html import latex_to_html


# ---------------------------------------------------------------------------
# Supported vocabulary
# ---------------------------------------------------------------------------

def test_plain_paragraph():
    assert latex_to_html("Just some prose.") == "<p>Just some prose.</p>"


def test_textbf_and_emph():
    assert latex_to_html("A \\textbf{bold} and \\emph{italic} run.") == (
        "<p>A <strong>bold</strong> and <em>italic</em> run.</p>"
    )


def test_run_in_label_pattern():
    """The generator's labeled run-in: \\noindent\\textbf{Label.} text."""
    assert latex_to_html("\\noindent\\textbf{Background.} The study tested...") == (
        "<p><strong>Background.</strong> The study tested...</p>"
    )


def test_escaped_specials_become_literals():
    assert latex_to_html("100\\% at \\$5 \\& rising, ref\\_id \\#3") == (
        "<p>100% at $5 &amp; rising, ref_id #3</p>"
    )


def test_escaped_braces_and_backslash():
    assert latex_to_html("set \\{a\\} via \\textbackslash{}cmd") == (
        "<p>set {a} via \\cmd</p>"
    )


def test_blank_line_splits_paragraphs():
    assert latex_to_html("First para.\n\nSecond para.") == (
        "<p>First para.</p>\n<p>Second para.</p>"
    )


def test_nested_markup():
    assert latex_to_html("\\textbf{bold \\emph{and italic}}") == (
        "<p><strong>bold <em>and italic</em></strong></p>"
    )


def test_raw_angle_brackets_are_escaped():
    assert latex_to_html("a < b > c") == "<p>a &lt; b &gt; c</p>"


# ---------------------------------------------------------------------------
# Refused (→ None → preview shows the stale marker)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tex", [
    "",
    "   \n  ",
    "\\begin{niehstable}{x}\n1 & 2 \\\\\n\\end{niehstable}",  # environment
    "see \\ref{tab:1}",                                       # cross-ref macro
    "\\includegraphics{figures/x.pdf}",                       # graphics
    "visit \\url{https://example.com}",                       # url macro
    "\\ensuremath{\\le} 0.05",                                # math macro
    "row one & row two",                                      # bare alignment &
    "inline $x^2$ math",                                      # math mode
    "a stray % comment",                                      # comment char
    "\\textbf{unbalanced",                                    # missing close brace
    "\\unknownmacro{arg}",                                    # unknown command
])
def test_unsupported_returns_none(tex):
    assert latex_to_html(tex) is None
