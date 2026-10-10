"""
The NTP report grammar (vocab/ntp-bits-grammar.yaml, document_model.ntp_grammar,
ADR-0029 §7): the NTP Word template's structural styles and the BITS construct
each becomes.  It is the template's — every style it names is one of the
template's — and it is the published books' — every part and roster paragraph
of all 12 books is one it produces, in that book's packaging.
"""

import json
import re
import zipfile
from pathlib import Path

import pytest

from document_model import ntp_grammar
from tooling.bits_structure import PUBLISHED

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures" / "reference"
TEMPLATE = REPO / "assets" / "templates" / "NIEHS-report-style-bordered.dotx"
BOOKSHELF = REPO / "assets" / "cebs" / "_bookshelf"


def test_every_style_is_the_ntp_template_s():
    styles = set(re.findall(r'<w:name w:val="([^"]+)"',
                            zipfile.ZipFile(TEMPLATE).read("word/styles.xml").decode("utf-8")))
    assert ntp_grammar.style_names() - styles == set()


def test_the_packagings_hold_the_part_elements_of_the_books():
    assert ntp_grammar.part_elements("chunked") == {
        "book-meta", "abstract", "foreword", "front-matter-part", "book-part", "book-app"}
    assert ntp_grammar.part_elements("single-file") == {
        "book-meta", "abstract", "foreword", "front-matter-part", "ack", "sec", "ref-list",
        "app"}


def _packaging(dtxsid: str) -> str:
    from document_model.document_definition import study_definition_name
    from document_model.document_template import load_packaging
    return load_packaging(study_definition_name(dtxsid))


@pytest.mark.parametrize("dtxsid, report", sorted(PUBLISHED.items(), key=lambda kv: kv[1]),
                         ids=lambda v: v)
def test_every_published_part_is_a_grammar_part(dtxsid, report):
    """Each top-level part of the published outline, in the packaging the
    report's definition declares."""
    constructs = ntp_grammar.part_constructs(_packaging(dtxsid))
    rows = json.loads((FIXTURES / report / "bookshelf-outline.json").read_text(encoding="utf-8"))
    parts = {("book-meta" if r["kind"] == "book-title" else r["kind"], r["part_type"] or None)
             for r in rows if r["depth"] == 0 and r["kind"] not in ("subtitle", "contrib-group")}
    assert parts - constructs == set()


@pytest.mark.parametrize("report", sorted(set(PUBLISHED.values())))
def test_every_roster_paragraph_is_a_grammar_paragraph(report):
    if not (BOOKSHELF / report / "TOC.nxml").exists():
        pytest.skip(f"published {report} bundle not downloaded (assets/cebs/_bookshelf)")
    from rendering.bits_bundle import read_bundle
    known = set(ntp_grammar.grammar()["paragraphs"].values())
    seen = {p.get("content-type") for p in read_bundle(BOOKSHELF / report).iter("p")
            if p.get("content-type")}
    assert seen - known == set()


def test_a_roster_names_its_paragraph_types():
    assert ntp_grammar.roster_content_types("collaborators") == {
        "person": "collaborator", "affiliation": "collab-affiliation",
        "contributions": "collab-contributions"}
    assert ntp_grammar.roster_content_types("section") is None


def test_a_definition_may_only_declare_grammar_parts(tmp_path, monkeypatch):
    import document_model.document_config  # noqa: F401 — builds the shared tree first
    from document_model import document_template as dt
    monkeypatch.setattr(dt, "TEMPLATES_DIR", tmp_path)
    (tmp_path / "t.yaml").write_text(
        "document:\n- region: front\n  children:\n"
        "  - {id: g, type: front-matter, title: Glossary, data_key: g,\n"
        "     element: front-matter-part, book_part_type: glossary}\n")
    with pytest.raises(ValueError, match="no NTP template heading makes"):
        dt.load_template("t")
