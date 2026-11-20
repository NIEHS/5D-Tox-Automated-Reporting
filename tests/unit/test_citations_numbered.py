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


def _report(background, sources=None, methods=None):
    data = scaffold_report_data()
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
    plain["background"] = {"paragraphs": ["As given [3]."]}
    plain["references"] = {"paragraphs": ["[3] A reference as given."]}
    assert numbered(plain) is plain


@pytest.mark.parametrize("surface", ["latex", "bits", "jats"])
def test_every_surface_prints_numbers_and_the_derived_list(surface):
    data = _report([f"First {token('b')}.", f"Then {token('a')}{token('b')}."])
    if surface == "latex":
        from rendering.latex_generator import generate_latex
        out = generate_latex(data)
    elif surface == "bits":
        from rendering.bits_book import generate_bits
        out = generate_bits(data)
    else:
        from rendering.jats_generator import generate_jats
        out = generate_jats(data)
    out = out if isinstance(out, str) else str(out)
    assert "[[cite:" not in out and "cite:" not in out
    assert "Then [2, 1]." in out
    assert "Gamma" not in out                      # recorded, never cited: not listed
    assert out.count("Beta site.") == 1
