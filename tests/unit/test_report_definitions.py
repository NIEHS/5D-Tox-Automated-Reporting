"""
Each published report's document definition (ADR-0029: its era base plus
alterations, templates/studies/<DTXSID>/document.yaml) produces the published
book's structure: its parts, part types, labels and section headings, compared
with the committed outline of the published Bookshelf book
(tests/fixtures/reference/<REPORT>/bookshelf-outline.json).

The book is built from scaffold data plus the study's own authored content, so
what depends on the study's data (which tables and figures, how many) is left
out here: objects, the title and the author count.  `tooling.bits_structure`
compares a generated report in full.  What the definition cannot supply —
content the study has not been given yet — is listed in KNOWN_CONTENT_GAPS.

The built book must also be valid BITS (the vendored DTD) and carry the
published series ISSN, a per-book fact of the definition's book_meta.
"""

import difflib
import json
from pathlib import Path

import pytest

from document_model.document_config import _tree_from_document_list
from document_model.document_definition import study_definition_name
from document_model.document_template import (
    load_book_meta, load_object_position, load_packaging, load_template,
)
from rendering.bits_bundle import OutlineEntry, outline, parse_book, structure_keys
from rendering.jats_generator import generate_bits
from rendering.jats_stylecheck import dtd_validate
from rendering.report_data import scaffold_report_data
from styling_export.freeform_content import load_study_authored
from tooling.bits_structure import BOOKSHELF, PUBLISHED
from tooling.build_published_reports import STUDIES

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "reference"

# report → (chemical name, CASRN) for the scaffold.
_IDENTITY = {r: (v[1], v[2]) for r, v in STUDIES.items()}
_IDENTITY["NIEHS-13"] = ("1,4-Dichlorobenzene", "106-46-7")

# What depends on the study's data, not on its structure.
_DATA_KINDS = {"table-wrap", "fig", "media", "supplementary-material", "disp-formula",
               "contrib-group", "book-title", "subtitle"}

# The series ISSN each published book carries (its <collection-meta
# collection-type="book-series">): the NIEHS Report series' first ISSN, then from
# NIEHS-05 (and NIEHS-09 on) its second.
PUBLISHED_ISSN = {
    "RR-8": "2473-4756", "NIEHS-02": "2473-4756", "NIEHS-03": "2473-4756",
    "NIEHS-04": "2473-4756", "NIEHS-05": "2768-5632", "NIEHS-06": "2768-5632",
    "NIEHS-07": "2473-4756", "NIEHS-08": "2473-4756", "NIEHS-09": "2768-5632",
    "NIEHS-10": "2768-5632", "NIEHS-12": "2768-5632", "NIEHS-13": "2768-5632",
}

# Published lines our build lacks (or has) for want of CONTENT, not structure.
KNOWN_CONTENT_GAPS = {
    # A.1 is the study's plasma analytical method, a heading inside its authored
    # appendix-a content; supplied for NIEHS-10 only.
    "NIEHS-07": ["-  sec <A.1> Quantitation of 6:1 Fluorotelomer Alcohol in Plasma"],
    "NIEHS-08": ["-  sec <A.1> Quantitation of 1,1,2,2-Tetrahydroperfluoro-1-dodecanol in Plasma"],
    "NIEHS-09": ["-  sec <A.1> Quantitation of 2,3-Benzofluorene in Plasma"],
}


def _keys(entries) -> list[str]:
    return structure_keys([e for e in entries if e.kind not in _DATA_KINDS])


def _built_bits(dtxsid: str, report: str, name: str) -> str:
    chemical, casrn = _IDENTITY[report]
    data = scaffold_report_data(chemical_name=chemical, casrn=casrn, dtxsid=dtxsid)
    data["authored"] = load_study_authored(dtxsid)
    data.update(book_meta=load_book_meta(name), packaging=load_packaging(name),
                object_position=load_object_position(name))
    return generate_bits(data, _tree_from_document_list(load_template(name)))


@pytest.mark.parametrize("dtxsid, report", sorted(PUBLISHED.items(), key=lambda kv: kv[1]),
                         ids=lambda v: v)
def test_a_report_definition_produces_the_published_structure(dtxsid, report):
    name = study_definition_name(dtxsid)
    if name is None:
        pytest.skip(f"{report} has no document definition yet")
    published = [OutlineEntry(**r) for r in json.loads(
        (FIXTURES / report / "bookshelf-outline.json").read_text(encoding="utf-8"))]
    xml = _built_bits(dtxsid, report, name)
    book = parse_book(xml)
    diff = [ln for ln in difflib.unified_diff(_keys(published), _keys(outline(book)),
                                              lineterm="", n=0)
            if ln[:1] in "+-" and ln[:3] not in ("+++", "---")]
    assert diff == KNOWN_CONTENT_GAPS.get(report, [])
    assert dtd_validate(xml, "book") == ()
    assert book.findtext("collection-meta[@collection-type='book-series']/issn") \
        == PUBLISHED_ISSN[report]


@pytest.mark.parametrize("report", sorted(PUBLISHED_ISSN))
def test_the_issn_list_is_the_published_books(report):
    toc = BOOKSHELF / report / "TOC.nxml"
    if not toc.exists():
        pytest.skip(f"published {report} bundle not downloaded (assets/cebs/_bookshelf)")
    book = parse_book(toc.read_bytes())
    assert book.findtext("collection-meta[@collection-type='book-series']/issn") \
        == PUBLISHED_ISSN[report]
