"""
A report's document definition is an era base plus alterations (ADR-0029):
document_model.document_definition composes `extends` + `changes` on the raw
template entries, and the template loaders read the composed result.
"""

import textwrap

import pytest

from document_model import document_template as dt
from document_model.document_definition import load_definition


BASE = """
document:
- region: front
  children:
  - {id: foreword, type: front-matter, title: Foreword, data_key: foreword}
- region: body
  children:
  - id: methods
    type: heading-only
    title: Methods
    children:
    - {id: m-a, type: narrative, title: A, data_key: a, narrative_key: a}
    - {id: m-b, type: narrative, title: B, data_key: b}
book_meta:
  series: {title: Old Series, issn: 1111-1111}
  publisher: {name: Pub}
"""


@pytest.fixture()
def templates(tmp_path, monkeypatch):
    import document_model.document_config  # noqa: F401 — builds the shared tree first
    monkeypatch.setattr(dt, "TEMPLATES_DIR", tmp_path)

    def write(name: str, text: str) -> None:
        path = tmp_path / f"{name}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text), encoding="utf-8")
    write("base", BASE)
    return write


def _ids(entries) -> list[str]:
    out = []
    for e in entries:
        if "id" in e:
            out.append(e["id"])
        out += _ids(e.get("children") or [])
    return out


def test_a_full_template_is_its_own_definition(templates):
    assert _ids(load_definition("base")["document"]) == ["foreword", "methods", "m-a", "m-b"]
    assert dt.load_packaging("base") == "chunked"


def test_changes_alter_the_base_in_order(templates):
    templates("eras/e1", """
        extends: base
        packaging: single-file
        book_meta: {series: {title: New Series}}
        changes:
          - set: methods
            element: sec
          - set: m-a
            title: A prime
            narrative_key: null
          - remove: foreword
          - insert: [{id: m-c, type: narrative, title: C, data_key: c}]
            after: m-a
          - move: m-b
            into: methods
            at: first
          - insert: [{id: disc, type: narrative, title: Discussion, data_key: d,
                      element: sec}]
            into: body
    """)
    doc = dt.load_template("eras/e1")
    assert _ids(doc) == ["methods", "m-b", "m-a", "m-c", "disc"]
    m_a = doc[1]["children"][0]["children"][1]
    assert m_a["title"] == "A prime" and "narrative_key" not in m_a
    assert dt.load_book_meta("eras/e1") == {"series": {"title": "New Series", "issn": "1111-1111"},
                                            "publisher": {"name": "Pub"}}
    assert dt.load_packaging("eras/e1") == "single-file"
    dt.instantiate(doc)                       # the composed document validates


def test_a_study_extends_an_era_that_extends_a_base(templates):
    templates("eras/e1", "extends: base\nchanges:\n  - remove: m-b\n")
    templates("studies/DTXSID0000001/document", "extends: eras/e1\nchanges:\n  - remove: m-a\n")
    assert _ids(dt.load_template("studies/DTXSID0000001/document")) == ["foreword", "methods"]
    from document_model.document_definition import study_definition_name
    assert study_definition_name("DTXSID0000001") == "studies/DTXSID0000001/document"
    assert study_definition_name("DTXSID0000002") is None


@pytest.mark.parametrize("text, message", [
    ("extends: base\nchanges:\n  - remove: nope\n", "no node 'nope'"),
    ("extends: base\nchanges:\n  - set: m-a\n    id: x\n", "not its id"),
    ("extends: base\nchanges:\n  - insert: [{id: x}]\n", "exactly one of"),
    ("extends: base\npackaging: zip\n", "packaging"),
    ("extends: base\ndocument: []\n", "unknown key"),
    # A single-file book's chapters are <sec>s, not <book-part>s.
    ("extends: base\npackaging: single-file\n", "'methods' is a <book-part>"),
])
def test_bad_changes_fail_loudly(templates, text, message):
    templates("bad", text)
    with pytest.raises(ValueError, match=message):
        dt.load_template("bad")


def test_an_extends_cycle_fails(templates):
    templates("x", "extends: y\n")
    templates("y", "extends: x\n")
    with pytest.raises(ValueError, match="cycle"):
        dt.load_template("x")


def test_a_study_renders_from_its_own_definition(templates):
    """With no session view or session document, a study's tree, series facts,
    packaging and object placement come from templates/studies/<DTXSID>/."""
    from document_model.view_config import build_view_tree, study_document_facts

    templates("studies/DTXSID0000001/document", """
        extends: base
        packaging: single-file
        object_position: {back: float}
        changes:
          - remove: foreword
          - set: methods
            element: sec
    """)
    tree = build_view_tree("DTXSID0000001", "default")
    assert [n.id for n in tree] == ["methods"]
    facts = study_document_facts("DTXSID0000001")
    assert facts["packaging"] == "single-file"
    assert facts["object_position"] == {"back": "float"}
    assert facts["book_meta"]["series"]["title"] == "Old Series"


def test_find_node_resolves_in_the_tree_being_rendered():
    from document_model.document_node import DocNode
    from document_model.document_tree import find_node, rendering_tree

    mine = [DocNode(id="background", title="Mine", node_type="narrative", level=1)]
    assert find_node("background").title != "Mine"
    with rendering_tree(mine):
        assert find_node("background").title == "Mine"
    assert find_node("background").title != "Mine"


def test_an_empty_part_type_means_none(templates):
    """`book_part_type: ""` gives a part no type; absent, the element's default."""
    templates("e", """
        extends: base
        packaging: single-file
        changes:
          - set: foreword
            book_part_type: ""
          - set: methods
            element: sec
    """)
    nodes = {n.id: n for n in dt.instantiate(dt.load_template("e"))}
    assert nodes["foreword"].book_part_type is None
    assert nodes["methods"].element == "sec" and nodes["methods"].book_part_type is None


def test_a_title_names_the_study_chemical():
    """`${chemical_name}` in a title is the study's (study_tree, every surface);
    the shared tree keeps the placeholder, and a study without the fact keeps it
    as written."""
    from document_model.document_node import DocNode
    from document_model.document_tree import study_tree

    base = [DocNode(id="a", node_type="heading-only", title="Quantitation of ${chemical_name} in Plasma")]
    ours = study_tree(base, None, None, {"chemical_name": "PFHxSAm"})
    assert ours[0].title == "Quantitation of PFHxSAm in Plasma"
    assert base[0].title == "Quantitation of ${chemical_name} in Plasma"
    assert study_tree(base, None, None, {})[0].title == base[0].title
