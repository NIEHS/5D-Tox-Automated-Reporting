"""
Unit tests for the two SURFACE translators that turn a resolved abstract style
spec into concrete markup:

  - latex_generator._layout_to_latex(style) -> (pre, post)
  - html_generator._layout_to_css_props(style) -> "prop: val; ..."

Both bind to the SAME resolved spec (layout_style.resolve_layout_style), so the
tests assert the parallel: an empty spec is a strict no-op on BOTH surfaces (the
byte-identical guarantee), and a representative rich spec emits the expected
directives on each.
"""

import html_generator as hg
import latex_generator as lg


RICH = {
    "font_family": "sans",
    "font_size": "12pt",
    "line_height": 1.5,
    "weight": "bold",
    "style": "italic",
    "color": "#2c5282",
    "align": "center",
    "first_line_indent": "1.5em",
    "space_before": "6pt",
    "space_after": "12pt",
    "break_before": "page",
    "keep_together": True,
}


# ---------------------------------------------------------------------------
# The no-op guarantee — an empty/None spec emits nothing on either surface.
# ---------------------------------------------------------------------------

def test_latex_empty_spec_is_noop():
    assert lg._layout_to_latex({}) == ("", "")
    assert lg._layout_to_latex(None) == ("", "")


def test_css_empty_spec_is_noop():
    assert hg._layout_to_css_props({}) == ""
    assert hg._layout_to_css_props(None) == ""


# ---------------------------------------------------------------------------
# LaTeX translator
# ---------------------------------------------------------------------------

def test_latex_font_family_maps_to_family_command():
    assert r"\sffamily" in lg._layout_to_latex({"font_family": "sans"})[0]
    assert r"\rmfamily" in lg._layout_to_latex({"font_family": "serif"})[0]
    assert r"\ttfamily" in lg._layout_to_latex({"font_family": "mono"})[0]


def test_latex_size_computes_leading_from_line_height():
    # 12pt * 1.5 = 18pt leading.
    pre, _ = lg._layout_to_latex({"font_size": "12pt", "line_height": 1.5})
    assert r"\fontsize{12pt}{18pt}\selectfont" in pre


def test_latex_size_defaults_leading_when_no_line_height():
    # No line_height → LaTeX-ish 1.2 default leading (12pt * 1.2 = 14.4pt).
    pre, _ = lg._layout_to_latex({"font_size": "12pt"})
    assert r"\fontsize{12pt}{14.4pt}\selectfont" in pre


def test_latex_weight_style_color_align_indent():
    pre, post = lg._layout_to_latex(RICH)
    assert r"\bfseries" in pre
    assert r"\itshape" in pre
    assert r"\definecolor{ctcolor2c5282}{HTML}{2C5282}" in pre
    assert r"\color{ctcolor2c5282}" in pre
    assert r"\centering" in pre
    assert r"\setlength\parindent{1.5em}" in pre
    # The declaration group is flushed with \par so the size/leading applies to
    # the paragraph it wraps.
    assert r"\par}" in post


def test_latex_flow_sits_outside_the_group():
    pre, post = lg._layout_to_latex(RICH)
    # break_before + space_before precede the group; keep_together boxes it.
    assert r"\clearpage" in pre
    assert r"\vspace{6pt}" in pre
    assert r"\begin{minipage}{\linewidth}" in pre
    # space_after + minipage close in post.
    assert r"\vspace{12pt}" in post
    assert r"\end{minipage}" in post


def test_latex_short_hex_color_expands_to_six_digits():
    pre, _ = lg._layout_to_latex({"color": "#abc"})
    assert r"\definecolor{ctcoloraabbcc}{HTML}{AABBCC}" in pre


# ---------------------------------------------------------------------------
# HTML/CSS translator
# ---------------------------------------------------------------------------

def test_css_font_family_maps_to_stack():
    assert "font-family: Georgia" in hg._layout_to_css_props({"font_family": "serif"})
    assert "-apple-system" in hg._layout_to_css_props({"font_family": "sans"})
    assert "monospace" in hg._layout_to_css_props({"font_family": "mono"})


def test_css_rich_spec_emits_all_expected_props():
    css = hg._layout_to_css_props(RICH)
    for expected in (
        "font-size: 12pt",
        "font-weight: 700",
        "font-style: italic",
        "color: #2c5282",
        "text-align: center",
        "line-height: 1.5",
        "text-indent: 1.5em",
        "margin-top: 6pt",
        "margin-bottom: 12pt",
        "break-before: page",
        "break-inside: avoid",
    ):
        assert expected in css, f"missing {expected!r} in {css!r}"


def test_css_line_height_bool_is_not_emitted():
    # bool is an int subclass; a leading is not a flag — never emit it.
    assert "line-height" not in hg._layout_to_css_props({"line_height": True})


def test_css_partial_spec_emits_only_named_props():
    css = hg._layout_to_css_props({"align": "justify"})
    assert css == "text-align: justify"


# ---------------------------------------------------------------------------
# `font` (literal family name) precedence — the key added for the docx
# bootstrap.  An explicit `font` wins over `font_family` on every surface and is
# emitted verbatim; `font_family` alone still maps to the abstract stack/command.
# ---------------------------------------------------------------------------

def test_css_literal_font_is_emitted_verbatim_with_fallback():
    css = hg._layout_to_css_props({"font": "Times New Roman"})
    # Named font first, then a graceful fallback stack.
    assert css.startswith('font-family: "Times New Roman", ')


def test_css_font_wins_over_font_family():
    css = hg._layout_to_css_props({"font": "Arial", "font_family": "serif"})
    assert '"Arial"' in css
    # The serif stack is used only as the fallback tail, not the primary.
    assert not css.startswith("font-family: Georgia")


def test_latex_literal_font_emits_guarded_fontspec():
    pre, _ = lg._layout_to_latex({"font": "Times New Roman"})
    # Guarded so it is inert under pdflatex+lmodern and active under XeTeX.
    assert r"\ifdefined\fontspec\fontspec{Times New Roman}\fi" in pre


def test_latex_font_wins_over_font_family():
    pre, _ = lg._layout_to_latex({"font": "Arial", "font_family": "serif"})
    assert r"\fontspec{Arial}" in pre
    assert r"\rmfamily" not in pre  # the abstract family command is suppressed
