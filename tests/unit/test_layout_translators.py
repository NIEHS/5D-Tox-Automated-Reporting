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
    "text_transform": "uppercase",
    "letter_spacing": "1pt",
    "color": "#2c5282",
    "align": "center",
    "first_line_indent": "1.5em",
    "space_before": "6pt",
    "space_after": "12pt",
    "break_before": "page",
    "break_after": "page",
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


def test_latex_break_after_clearpages_in_post():
    # break_after sits in POST (after the node), symmetric to break_before in pre.
    pre, post = lg._layout_to_latex({"break_after": "page"})
    assert r"\clearpage" in post
    assert r"\clearpage" not in pre


def test_latex_text_transform_wraps_uppercase_primitive():
    # The TeX primitive \uppercase (NOT \MakeUppercase, which forbids \par in its
    # argument) opens in pre, closes in post, around the chunk.
    pre, post = lg._layout_to_latex({"text_transform": "uppercase"})
    assert r"\uppercase{" in pre
    assert r"\MakeUppercase" not in pre  # would break on multi-paragraph nodes
    assert post.strip().startswith("}")


def test_latex_text_transform_closes_before_par():
    # With a font group present, the } must precede \par} (the group flush) so the
    # \uppercase group is balanced inside the declaration group.
    pre, post = lg._layout_to_latex({"weight": "bold", "text_transform": "uppercase"})
    assert post.index("}") < post.index(r"\par}")


def test_css_text_transform_only_uppercase_emits():
    assert "text-transform: uppercase" in hg._layout_to_css_props(
        {"text_transform": "uppercase"}
    )
    # `none` is a no-op (matches the byte-identical default), not an emit.
    assert "text-transform" not in hg._layout_to_css_props({"text_transform": "none"})


def test_css_letter_spacing_emits_verbatim():
    assert "letter-spacing: 0.5pt" in hg._layout_to_css_props(
        {"letter_spacing": "0.5pt"}
    )


def test_latex_letter_spacing_defines_and_wraps_soul():
    # An absolute length emits a scoped \sodef + a \rlmls wrap around the chunk.
    pre, post = lg._layout_to_latex({"letter_spacing": "2pt"})
    assert r"\sodef\rlmls{}{2pt}" in pre
    assert r"\rlmls{" in pre
    assert post.strip().startswith("}")


def test_latex_letter_spacing_rejects_relative_units():
    # soul spaces by a FIXED width; em/ex can't resolve to one here → no emit
    # (parity with docx, where _length_to_pt returns None for em/ex).
    assert lg._layout_to_latex({"letter_spacing": "0.2em"}) == ("", "")


def test_latex_letter_spacing_nests_inside_uppercase():
    # \uppercase must be OUTER, the \rlmls WRAP inner (soul receives cased char
    # tokens; it is finicky with macros in its own argument).  Assert on the wrap
    # (\rlmls{ at line start), not the \sodef\rlmls definition which precedes both.
    pre, _ = lg._layout_to_latex(
        {"letter_spacing": "1pt", "text_transform": "uppercase"}
    )
    assert pre.index(r"\uppercase{") < pre.index("\n\\rlmls{")


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
        "text-transform: uppercase",
        "letter-spacing: 1pt",
        "color: #2c5282",
        "text-align: center",
        "line-height: 1.5",
        "text-indent: 1.5em",
        "margin-top: 6pt",
        "margin-bottom: 12pt",
        "break-before: page",
        "break-after: page",
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
