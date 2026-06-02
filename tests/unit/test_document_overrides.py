r"""
test_document_overrides.py — the per-region user-owned override store + the
renderer's "override wins" overlay (ADR-0005 round-trip, step: override store).

What this proves
----------------
  - The store round-trips: set / get / load / clear, persisted to
    sessions/<dtxsid>/_document_overrides.json (here, a tmp dir).
  - With no overrides, generate_latex output is byte-identical (the default).
  - When an override exists for an anchor id, the generator emits the user's
    latex_region verbatim in place of the freshly generated region.
  - Stale detection: a base_hash that no longer matches the generated region
    records the anchor under data["_override_stale"] (override still wins).

These exercise the store + overlay WITHOUT any transport — exactly how the
reconciler will write overrides regardless of whether edits came from a
working-tree diff, the local Overleaf stand-in, or the real git-bridge.
"""

import re

import pytest

import document_overrides as do
from latex_generator import generate_latex
from report_data import scaffold_report_data


# A node region as the generator emits it: everything between the begin/end
# sentinels for one node id (\1 backreference ties end to begin; re.S so the
# body can span lines).
_NODE_REGION_RE = re.compile(
    r"^%% rlm:begin node (\S+)\n(.*?)\n%% rlm:end node \1$",
    re.M | re.S,
)


def _node_regions(tex: str) -> "dict[str, str]":
    """Map node id -> the LaTeX that sits between its begin/end sentinels."""
    return {m.group(1): m.group(2) for m in _NODE_REGION_RE.finditer(tex)}


@pytest.fixture(scope="module")
def scaffold() -> dict:
    """Self-contained report data (no session/disk dependency)."""
    return scaffold_report_data(
        chemical_name="Perfluorohexanesulfonamide",
        casrn="41997-13-1",
        dtxsid="DTXSID50469320",
    )


@pytest.fixture(scope="module")
def first_node(scaffold) -> tuple:
    """A real (node_id, generated_region) pair to override in the tests."""
    regions = _node_regions(generate_latex(scaffold))
    node_id, gen = next((k, v) for k, v in regions.items() if v.strip())
    return node_id, gen


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

def test_store_set_get_clear(tmp_path):
    dtxsid = "DTXSIDTEST"
    assert do.load_overrides(dtxsid, sessions_dir=tmp_path) == {}

    rec = do.set_override(
        dtxsid, "summary", "EDITED PROSE", "basehash0",
        source="manual", sessions_dir=tmp_path,
    )
    assert rec["latex_region"] == "EDITED PROSE"
    assert rec["source"] == "manual"
    assert rec["edited_at"]  # auto-stamped

    got = do.get_override(dtxsid, "summary", sessions_dir=tmp_path)
    assert got["latex_region"] == "EDITED PROSE"
    assert got["base_hash"] == "basehash0"

    # File actually persisted under the session dir.
    assert (tmp_path / dtxsid / "_document_overrides.json").exists()

    assert do.clear_override(dtxsid, "summary", sessions_dir=tmp_path) is True
    assert do.get_override(dtxsid, "summary", sessions_dir=tmp_path) is None
    # Clearing a missing override is a no-op False (not an error).
    assert do.clear_override(dtxsid, "summary", sessions_dir=tmp_path) is False


def test_corrupt_store_is_treated_as_empty(tmp_path):
    dtxsid = "DTXSIDBAD"
    store = tmp_path / dtxsid / "_document_overrides.json"
    store.parent.mkdir(parents=True)
    store.write_text("{ not valid json")
    assert do.load_overrides(dtxsid, sessions_dir=tmp_path) == {}


# ---------------------------------------------------------------------------
# Renderer overlay
# ---------------------------------------------------------------------------

def test_no_overrides_is_byte_identical(scaffold):
    # An absent overrides map and an explicit empty one both mean "regenerate".
    assert generate_latex(scaffold) == generate_latex({**scaffold, "overrides": {}})


def test_override_replaces_region(scaffold, first_node):
    node_id, gen = first_node
    override_body = "%% OVERRIDE-MARKER\nhand-edited content"
    data = {
        **scaffold,
        "overrides": {
            node_id: {"latex_region": override_body, "base_hash": do.region_hash(gen)},
        },
    }
    out = generate_latex(data)
    regions = _node_regions(out)
    # The user's region replaced the generated one, exactly.
    assert regions[node_id] == override_body
    # base_hash matched the generated region -> not flagged stale.
    assert node_id not in (data.get("_override_stale") or [])


def test_stale_flag_when_base_drifts(scaffold, first_node):
    node_id, _gen = first_node
    data = {
        **scaffold,
        "overrides": {
            node_id: {"latex_region": "x", "base_hash": "deadbeef-does-not-match"},
        },
    }
    generate_latex(data)
    # Override still applied, but the drift is recorded for human review.
    assert node_id in (data.get("_override_stale") or [])
