"""
The roster parts (Authors, Contributors, Collaborators) as the published books
list them: affiliation by affiliation, contribution by contribution, with the
NTP report grammar's paragraph content-types.  Each published book's roster is
read back into front-matter records and rebuilt by rendering.bits_book; the
list must come out the same, paragraph for paragraph.
"""

from pathlib import Path

import pytest

from document_model.document_node import DocNode
from rendering.bits_book import _roster_blocks
from rendering.bits_bundle import _text, read_bundle

BOOKSHELF = Path(__file__).resolve().parents[2] / "assets" / "cebs" / "_bookshelf"
REPORTS = ["RR-8"] + [f"NIEHS-{n:02d}" for n in (2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13)]


def _items(lst) -> list[list[tuple[str, str]]]:
    return [[(p.get("content-type"), _text(p)) for p in item.findall("p")]
            for item in lst.findall("list-item")]


def _records(lst) -> list[dict]:
    """The roster a published list states, as front-matter records."""
    people, aff = [], ""
    for item in lst.findall("list-item"):
        contribution = ""
        for p in item.findall("p"):
            ct, text = p.get("content-type") or "", _text(p)
            if ct.endswith("affiliation"):
                aff = text
            elif ct.endswith("contributions"):
                contribution = text
            else:
                people.append({"name": text, "affiliation": aff, "contribution": contribution})
    return people


@pytest.mark.parametrize("report", REPORTS)
def test_a_published_roster_is_rebuilt_as_published(report):
    if not (BOOKSHELF / report / "TOC.nxml").exists():
        pytest.skip(f"published {report} bundle not downloaded (assets/cebs/_bookshelf)")
    book = read_bundle(BOOKSHELF / report)
    checked = 0
    for part in book.iter("front-matter-part"):
        kind = part.get("book-part-type")
        lst = part.find("named-book-part-body/list")
        if kind not in ("authors", "contributors", "collaborators") or lst is None:
            continue
        node = DocNode(id=kind, title=kind, book_part_type=kind)
        ours = _roster_blocks(node, {"front_matter": {kind: _records(lst)}})
        assert _items(ours[0]) == _items(lst), kind
        checked += 1
    assert checked
