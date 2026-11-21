"""rendering/citations.py — the numbers and the reference list are derived
from what the presented report prints (ADR-0038)."""

import re

import pytest

from narrative.sources import token
from rendering.citations import NOT_NUMBERED, UNKNOWN_SOURCE, numbered, printed_order
from rendering.html_generator import generate_html
from rendering.report_data import scaffold_report_data

A = {"slug": "a", "identity": "doi:10.1/a", "kind": "paper", "authors": ["Able B"],
     "title": "Alpha", "container": "J", "year": 2001, "doi": "10.1/a",
     "origin": {"from": "knowledge_base"}}
B = {"slug": "b", "identity": "url:https://b.example", "kind": "website",
     "text": "Beta site.", "url": "https://b.example", "origin": {"from": "background"}}
C = {"slug": "c", "identity": "doi:10.1/c", "kind": "paper", "authors": ["Cee D"],
     "title": "Gamma", "container": "J", "year": 2003, "doi": "10.1/c",
     "origin": {"from": "knowledge_base"}}


def _report(background, sources=None, methods=None, style="bracket"):
    """A small report.  The numbering tests declare the bracket style, whose
    paragraphs stay plain strings; the style tests below declare their own."""
    data = scaffold_report_data()
    data["citation_style"] = style
    data["background"] = {"paragraphs": list(background)}
    data["sources"] = {s["slug"]: dict(s) for s in (sources if sources is not None else (A, B, C))}
    if methods:
        data["methods"]["sections"][0]["paragraphs"] = list(methods)
    return data


def _text(markup: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", markup).split())


def test_a_source_is_numbered_at_its_first_citation_and_only_the_cited_are_listed():
    data = _report([f"First {token('b')}.", f"Then {token('a')}{token('b')}."])
    out = numbered(data)
    assert out["background"]["paragraphs"] == ["First [1].", "Then [2, 1]."]
    assert out["references"]["paragraphs"] == [
        "[1] Beta site. https://b.example",
        "[2] Able B. Alpha. J. 2001. https://doi.org/10.1/a"]
    assert out["citations"] == {"order": ["b", "a"], "numbers": {"b": 1, "a": 2},
                                "unknown": [], "not_cited": ["c"]}
    # The data given is not changed: its numbers are another view's to derive.
    assert data["background"]["paragraphs"][0] == f"First {token('b')}."


def test_the_order_is_the_order_of_the_printed_report_not_of_the_data():
    # The Materials and Methods print after the Background, whatever the
    # order of the keys in the data.
    data = _report([f"Background cites {token('a')}."], methods=[f"Methods cite {token('c')}."])
    assert printed_order(data) == ["a", "c"]
    text = _text(generate_html(data))
    assert "Background cites [1]." in text and "Methods cite [2]." in text
    assert "[[cite:" not in text
    assert text.index("[1] Able B. Alpha.") < text.index("[2] Cee D. Gamma.")


def test_text_the_view_does_not_print_cites_nothing():
    data = _report([f"Printed {token('a')}."])
    data["an_unprinted_note"] = f"Not printed {token('c')}."
    out = numbered(data)
    assert out["citations"]["order"] == ["a"] and out["citations"]["not_cited"] == ["b", "c"]
    assert len(out["references"]["paragraphs"]) == 1
    # A citation the report does not print is marked, never left as a token.
    assert out["an_unprinted_note"] == f"Not printed {NOT_NUMBERED}."


def test_two_records_of_one_identity_get_one_number_and_one_entry():
    twin = {**A, "slug": "a2"}
    data = _report([f"One {token('a')}. Its twin {token('a2')}. Both {token('a')}{token('a2')}."],
                   sources=(A, twin))
    out = numbered(data)
    assert out["background"]["paragraphs"] == ["One [1]. Its twin [1]. Both [1]."]
    assert len(out["references"]["paragraphs"]) == 1


def test_a_citation_of_no_recorded_source_prints_as_pending():
    data = _report([f"Known {token('a')}. Unknown {token('unknown-7')}. Stray {token('zz')}."])
    out = numbered(data)
    assert out["background"]["paragraphs"] == [
        f"Known [1]. Unknown {UNKNOWN_SOURCE}. Stray {UNKNOWN_SOURCE}."]
    assert out["citations"]["unknown"] == ["unknown-7", "zz"]
    assert out["references"]["paragraphs"] == ["[1] Able B. Alpha. J. 2001. https://doi.org/10.1/a"]


def test_a_library_entry_is_cited_by_its_key():
    data = _report([f"The procedure of Dunnett {token('dunnett1955')}."], sources=())
    out = numbered(data)
    assert out["background"]["paragraphs"] == ["The procedure of Dunnett [1]."]
    assert out["references"]["paragraphs"][0].startswith("[1] Dunnett CW. A multiple comparison")
    assert out["sources"]["dunnett1955"]["origin"] == {"from": "library", "key": "dunnett1955"}


def test_numbering_twice_changes_nothing_and_untracked_data_is_left_alone():
    data = _report([f"First {token('b')}."])
    once = numbered(data)
    assert numbered(once) is once
    plain = scaffold_report_data()
    plain["citation_style"] = "superscript"
    plain["background"] = {"paragraphs": ["As given [3]."]}
    plain["references"] = {"paragraphs": ["[3] A reference as given."]}
    assert numbered(plain) is plain


# ── the citation style: declared by the definition, per section ────────────

def _sup(text, cites):
    return {"type": "sup", "text": text, "cites": cites}


def test_the_published_style_is_a_superscript_after_the_punctuation():
    data = _report([f"The procedures of Williams {token('a')}{token('b')} and Dunnett {token('c')}.",
                    f"Three in a row {token('a')}{token('b')}{token('c')}; then one ({token('b')})."],
                   style="superscript")
    out = numbered(data)
    assert out["background"]["paragraphs"] == [
        ["The procedures of Williams", _sup("1,2", [1, 2]), " and Dunnett.", _sup("3", [3])],
        ["Three in a row;", _sup("1-3", [1, 2, 3]), " then one (", _sup("2", [2]), ")."]]
    text = generate_html(data)
    assert "Williams<sup>1,2</sup> and Dunnett.<sup>3</sup>" in text
    assert "Three in a row;<sup>1-3</sup> then one (<sup>2</sup>)." in text


def test_superscript_numbers_are_ascending_each_once_and_three_in_a_row_are_a_range():
    from rendering.citations import superscript_numbers
    assert superscript_numbers([19, 18]) == "18,19"
    assert superscript_numbers([3, 4, 5, 6]) == "3-6"
    assert superscript_numbers([1, 2, 4, 5, 6, 9, 2]) == "1,2,4-6,9"


def test_the_style_is_superscript_where_the_definition_says_nothing():
    data = _report([f"Cited {token('a')}."])
    del data["citation_style"]
    assert numbered(data)["background"]["paragraphs"] == [["Cited.", _sup("1", [1])]]
    from document_model.document_template import load_citation_style
    assert load_citation_style("niehs-5day-report") == "superscript"


def _tree_with(node_id, style):
    """The default tree, with one node declaring its citation style."""
    import copy

    from document_model.document_tree import DOCUMENT_TREE
    tree = copy.deepcopy(DOCUMENT_TREE)

    def find(nodes):
        for node in nodes:
            if node.id == node_id:
                return node
            found = find(node.children)
            if found:
                return found
    find(tree).citation_style = style
    return tree


def test_a_section_declares_its_own_style_and_the_sections_under_it_follow():
    data = _report([f"Background cites {token('a')}."], methods=[f"Methods cite {token('c')}."],
                   style="superscript")
    # The Background in brackets; the Methods follow the document.
    out = numbered(data, _tree_with("background", "bracket"))
    assert out["background"]["paragraphs"] == ["Background cites [1]."]
    assert out["methods"]["sections"][0]["paragraphs"] == [["Methods cite.", _sup("2", [2])]]
    # Declared on the Methods' top node: its subsections follow it.
    data["citation_style"] = "bracket"
    out = numbered(data, _tree_with("methods", "superscript"))
    assert out["background"]["paragraphs"] == ["Background cites [1]."]
    assert out["methods"]["sections"][0]["paragraphs"] == [["Methods cite.", _sup("2", [2])]]
    from rendering.citations import node_styles
    styles = node_styles(_tree_with("methods", "superscript"), "bracket")
    assert styles["methods"] == "superscript" and styles["background"] == "bracket"
    assert {styles[k] for k in styles if k.startswith("methods")} == {"superscript"}


def test_a_node_may_only_declare_a_known_style():
    from document_model.document_template import _validate_entry
    entry = {"id": "background", "type": "narrative", "title": "Background",
             "data_key": "background", "element": "book-part", "book_part_type": "section"}
    _validate_entry({**entry, "citation_style": "bracket"}, None)
    with pytest.raises(ValueError, match="citation_style must be one of"):
        _validate_entry({**entry, "citation_style": "footnote"}, None)


def test_a_paragraph_that_already_is_units_keeps_its_units():
    data = _report([["The gene ", {"type": "italic", "text": "Cyp1a1"},
                     f" rose {token('a')}."]], style="superscript")
    assert numbered(data)["background"]["paragraphs"] == [
        ["The gene ", {"type": "italic", "text": "Cyp1a1"}, " rose.", _sup("1", [1])]]


def test_where_no_markup_can_go_the_superscript_is_written_in_superscript_digits():
    data = _report([f"Printed {token('a')}."], style="superscript")
    data["abstract"] = {"sections": [{"label": "Background", "text": f"A solvent {token('a')}."}]}
    out = numbered(data)
    # The abstract's text is one string, not a list of paragraphs.
    assert out["abstract"]["sections"][0]["text"] == "A solvent.¹"
    assert "A solvent.¹" in generate_html(data)


def test_an_unknown_citation_stays_a_plain_pending_marker_in_the_superscript_style():
    data = _report([f"Known {token('a')}. Unknown {token('unknown-7')}."], style="superscript")
    assert numbered(data)["background"]["paragraphs"] == [
        ["Known.", _sup("1", [1]), f" Unknown {UNKNOWN_SOURCE}."]]


@pytest.mark.parametrize("style", ["bracket", "superscript"])
@pytest.mark.parametrize("surface", ["latex", "bits", "jats", "docx"])
def test_every_surface_prints_numbers_and_the_derived_list(surface, style):
    data = _report([f"First {token('b')}.", f"Then {token('a')}{token('b')}."], style=style)
    if surface == "latex":
        from rendering.latex_generator import generate_latex
        out = generate_latex(data)
        cited = "Then.\\textsuperscript{1,2}"
    elif surface == "bits":
        from rendering.bits_book import generate_bits
        out = generate_bits(data)
        cited = "Then.<sup>1,2</sup>"
    elif surface == "jats":
        from rendering.jats_generator import generate_jats
        out = generate_jats(data)
        cited = "Then.<sup>1,2</sup>"
    else:
        import io

        from docx import Document

        from rendering.docx_generator import generate_docx
        paragraphs = Document(io.BytesIO(generate_docx(data))).paragraphs
        then = next(p for p in paragraphs if p.text.startswith("Then"))
        runs = [(r.text, bool(r.font.superscript)) for r in then.runs if r.text]
        assert runs == ([("Then [2, 1].", False)] if style == "bracket"
                        else [("Then.", False), ("1,2", True)])
        out = "\n".join(p.text for p in paragraphs)
        cited = "Then [2, 1]." if style == "bracket" else "Then.1,2"
    out = out if isinstance(out, str) else str(out)
    assert "[[cite:" not in out and "cite:" not in out
    assert ("Then [2, 1]." if style == "bracket" else cited) in out
    assert "Gamma" not in out                      # recorded, never cited: not listed
    assert out.count("Beta site.") == 1


def test_a_paragraph_of_units_is_kept_where_paragraphs_with_text_are_selected():
    # A superscript paragraph is a list of units; the selections that keep
    # "the paragraphs that have text" must keep it (they once kept strings only,
    # which dropped an interpretation's paragraphs from a per-tissue section).
    from rendering.render_common import _paragraph_list
    units = ["Cyp1a1 rose.", _sup("3", [3])]
    assert _paragraph_list(["Plain.", units, "  ", [], ["", {"type": "sup", "text": ""}]]) == [
        "Plain.", units]
    assert _paragraph_list("One.") == ["One."] and _paragraph_list(None) == []
