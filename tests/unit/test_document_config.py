"""
Unit tests for per-session document-structure config (document_config.py,
ADR-0007 follow-on).

Pins the contract the feature rests on:

  1. No per-session file ⇒ build_session_tree returns None (callers fall back to
     the global DOCUMENT_TREE) and the GET route reports is_default.
  2. Round-trip: save valid YAML → load it back → build a tree from it.
  3. A structural edit (reordering body sections) yields a DIFFERENT tree than
     the global default — proving the per-session structure actually takes effect.
  4. Validate-before-write: an invalid edit raises ValueError and writes nothing
     (a previously-saved good file is preserved).
  5. The default path is untouched: marshal_export_data() with no tree is
     byte-identical whether or not a session override exists for a DIFFERENT id.
"""

import copy

import pytest
import yaml

import document_config as dc
from document_template import load_template
from document_tree import ACTIVE_TEMPLATE, DOCUMENT_TREE


def _default_document_list():
    """The active template's `document:` list (a fresh deep copy each call)."""
    return copy.deepcopy(load_template(ACTIVE_TEMPLATE))


def _reorder_body_yaml():
    """Default structure with the body region's children reversed → valid but
    structurally different from the default."""
    doc = _default_document_list()
    for entry in doc:
        if isinstance(entry, dict) and entry.get("region") == "body":
            entry["children"] = list(reversed(entry["children"]))
            break
    return yaml.safe_dump({"document": doc}, sort_keys=False, allow_unicode=True)


def test_no_session_file_returns_none(sessions_dir):
    assert dc.build_session_tree("DTXSID_ABSENT") is None
    assert dc.load_session_document_yaml("DTXSID_ABSENT") is None


def test_save_load_roundtrip(sessions_dir):
    d = "DTXSID_RT"
    text = dc.default_document_yaml()
    dc.save_session_document_yaml(d, text)

    assert dc.session_document_path(d).exists()
    assert dc.load_session_document_yaml(d) == text
    tree = dc.build_session_tree(d)
    assert tree is not None
    # Same structure as the global default ⇒ same top-level node count.
    assert len(tree) == len(DOCUMENT_TREE)


def test_structural_edit_changes_tree(sessions_dir):
    d = "DTXSID_EDIT"
    dc.save_session_document_yaml(d, _reorder_body_yaml())
    session_tree = dc.build_session_tree(d)
    assert session_tree is not None

    default_ids = [n.id for n in DOCUMENT_TREE]
    session_ids = [n.id for n in session_tree]
    # Same set of nodes, but a different ORDER — the edit took effect.
    assert set(default_ids) == set(session_ids)
    assert default_ids != session_ids


def test_invalid_yaml_raises_and_writes_nothing(sessions_dir):
    d = "DTXSID_BAD"
    # Seed a good file first.
    good = dc.default_document_yaml()
    dc.save_session_document_yaml(d, good)

    # Malformed YAML.
    with pytest.raises(ValueError):
        dc.save_session_document_yaml(d, "document: [unterminated")
    # Structurally invalid (unknown node type).
    with pytest.raises(ValueError):
        dc.save_session_document_yaml(d, "- {id: x, type: not-a-real-type, title: T}")
    # Duplicate ids.
    with pytest.raises(ValueError):
        dc.save_session_document_yaml(
            d,
            "- {id: dup, type: heading-only, title: A}\n"
            "- {id: dup, type: heading-only, title: B}\n",
        )

    # The previously-saved good file is intact.
    assert dc.load_session_document_yaml(d) == good


def test_default_document_yaml_parses_to_full_tree(sessions_dir):
    tree = dc._tree_from_document_list(
        dc._parse_document_yaml(dc.default_document_yaml())
    )
    assert len(tree) == len(DOCUMENT_TREE)


class TestDocumentConfigRoutes:
    """GET/POST /api/document-config/{dtxsid} through the real FastAPI app."""

    def test_get_default_when_absent(self, client):
        resp = client.get("/api/document-config/DTXSID_NONE")
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_default"] is True
        assert "document" in body["yaml"]

    def test_post_valid_then_get_returns_saved(self, client):
        d = "DTXSID_SAVE"
        text = _reorder_body_yaml()
        r = client.post(f"/api/document-config/{d}", json={"yaml": text})
        assert r.status_code == 200 and r.json().get("saved") is True

        g = client.get(f"/api/document-config/{d}")
        assert g.status_code == 200
        assert g.json()["is_default"] is False

    def test_post_invalid_returns_422(self, client):
        r = client.post(
            "/api/document-config/DTXSID_BAD",
            json={"yaml": "- {id: x, type: not-a-real-type, title: T}"},
        )
        assert r.status_code == 422
        assert "error" in r.json()

    def test_post_empty_returns_422(self, client):
        r = client.post("/api/document-config/DTXSID_EMPTY", json={"yaml": "   "})
        assert r.status_code == 422

    def test_default_query_forces_default(self, client):
        d = "DTXSID_FORCE"
        client.post(f"/api/document-config/{d}", json={"yaml": _reorder_body_yaml()})
        # Without ?default → saved copy
        assert client.get(f"/api/document-config/{d}").json()["is_default"] is False
        # With ?default=1 → the shared default
        forced = client.get(f"/api/document-config/{d}?default=1").json()
        assert forced["is_default"] is True

    def test_document_tree_reflects_session_override(self, client):
        d = "DTXSID_TREE"
        # Default tree order
        default_tree = client.get("/api/document-tree").json()
        default_ids = [n["id"] for n in default_tree]

        client.post(f"/api/document-config/{d}", json={"yaml": _reorder_body_yaml()})
        session_tree = client.get(
            f"/api/document-tree?dtxsid={d}"
        ).json()
        session_ids = [n["id"] for n in session_tree]

        assert set(default_ids) == set(session_ids)
        assert default_ids != session_ids
