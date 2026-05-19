r"""
test_latex_export.py — Smoke test for the Overleaf bundle builder.

Verifies that build_overleaf_bundle produces a valid zip containing the
files Overleaf expects: report.tex at the root, niehs.cls alongside it,
an empty figures/ directory, and a customer-facing README.md.

What this proves
----------------
  - The zip writes cleanly and is a real PKZIP archive.
  - All four expected entries are present.
  - report.tex is the same content generate_latex would produce
    (no accidental truncation or re-rendering inside the bundler).
  - niehs.cls in the zip is byte-identical to the source-tree class.
  - README.md mentions "Overleaf" so authors can search for instructions.

What this does NOT prove
------------------------
  - That the bundle actually compiles on Overleaf — that's a manual
    verification step.  Overleaf compatibility is asserted at the
    zip-format and file-layout level only.
"""

import zipfile
from pathlib import Path

import pytest

from latex_export import (
    CLASS_FILE,
    build_overleaf_bundle,
)
from latex_generator import generate_latex
from report_pdf import scaffold_report_data


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def scaffold() -> dict:
    """
    Same scaffold the production demo uses — Perfluorohexanesulfonamide.

    Module-scoped because building the scaffold is cheap but not free,
    and every test in this file just reads from the resulting bundle.
    """
    return scaffold_report_data(
        chemical_name="Perfluorohexanesulfonamide",
        casrn="41997-13-1",
        dtxsid="DTXSID50469320",
    )


@pytest.fixture
def bundle_path(scaffold, tmp_path) -> Path:
    """Build a bundle into a tmp dir; return the resulting zip path."""
    out = tmp_path / "bundle.zip"
    return build_overleaf_bundle(scaffold, out)


# ---------------------------------------------------------------------------
# Tests — zip structure
# ---------------------------------------------------------------------------

def test_bundle_is_a_valid_zip(bundle_path):
    """The bundle must be a real PKZIP archive Overleaf can extract."""
    assert zipfile.is_zipfile(bundle_path), (
        f"Bundle at {bundle_path} is not a valid zip"
    )


def test_bundle_contains_required_files(bundle_path):
    """All four required entries must be present at the zip root."""
    with zipfile.ZipFile(bundle_path) as zf:
        names = set(zf.namelist())
    assert "report.tex" in names
    assert "niehs.cls" in names
    assert "figures/.gitkeep" in names
    assert "README.md" in names


def test_bundle_has_no_top_level_directory(bundle_path):
    r"""
    Overleaf's "Upload Project" expects report.tex at the archive root,
    not inside a top-level folder.  Reject any entry whose first path
    component would put the .tex inside a subdirectory.
    """
    with zipfile.ZipFile(bundle_path) as zf:
        names = zf.namelist()
    # report.tex must be at root, not "myproject/report.tex"
    assert "report.tex" in names, (
        f"report.tex must be at the zip root; got {names}"
    )


# ---------------------------------------------------------------------------
# Tests — content fidelity
# ---------------------------------------------------------------------------

def test_report_tex_matches_generator_output(bundle_path, scaffold):
    """
    The .tex inside the zip must be exactly what generate_latex would
    produce for the same data — the bundler is a thin wrapper, not a
    second renderer.
    """
    with zipfile.ZipFile(bundle_path) as zf:
        tex_in_zip = zf.read("report.tex").decode("utf-8")
    expected = generate_latex(scaffold)
    assert tex_in_zip == expected


def test_class_file_matches_source(bundle_path):
    """niehs.cls in the zip must be byte-identical to the source-tree class."""
    with zipfile.ZipFile(bundle_path) as zf:
        cls_in_zip = zf.read("niehs.cls").decode("utf-8")
    assert cls_in_zip == CLASS_FILE.read_text()


def test_readme_mentions_overleaf(bundle_path):
    """Authors should be able to grep the bundle for 'Overleaf' and find help."""
    with zipfile.ZipFile(bundle_path) as zf:
        readme = zf.read("README.md").decode("utf-8")
    assert "Overleaf" in readme
    assert "Recompile" in readme


# ---------------------------------------------------------------------------
# Tests — include_readme toggle
# ---------------------------------------------------------------------------

def test_bundle_without_readme(scaffold, tmp_path):
    """
    The include_readme=False path is intended for production exports
    where authors already know the workflow.  The README should be
    absent but every other file present.
    """
    out = tmp_path / "lean.zip"
    build_overleaf_bundle(scaffold, out, include_readme=False)
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
    assert "report.tex" in names
    assert "niehs.cls" in names
    assert "README.md" not in names


# ---------------------------------------------------------------------------
# Tests — load_session_data and its conversion helpers
# ---------------------------------------------------------------------------

from latex_export import (
    _convert_genomics_cache,
    _normalize_apical_section,
    load_session_data,
)


def test_normalize_apical_section_flattens_values_dict():
    """
    The cache stores row values as a dict keyed by dose-as-string; the
    generator wants a list parallel to the row's doses.  Verify the
    translation.
    """
    raw = {
        "platform": "Body Weight",
        "tables_json": {
            "Male": [
                {
                    "label": "n",
                    "doses": [0.0, 0.15, 1.0],
                    "values": {"0": "10", "0.15": "5", "1": "5"},
                    "bmd": "NA", "bmdl": "NA",
                    "is_n_row": True,
                },
                {
                    "label": "Day 5",
                    "doses": [0.0, 0.15, 1.0],
                    "values": {"0": "245.3", "0.15": "244.8", "1": "240.1"},
                    "bmd": "8.5", "bmdl": "3.6",
                },
            ],
        },
    }
    out = _normalize_apical_section(raw)
    assert "table_data" in out
    male_rows = out["table_data"]["Male"]
    assert len(male_rows) == 2
    assert male_rows[0]["values"] == ["10", "5", "5"]
    assert male_rows[0]["is_n_row"] is True
    assert male_rows[1]["values"] == ["245.3", "244.8", "240.1"]
    assert male_rows[1]["endpoint"] == "Day 5"
    assert male_rows[1]["bmd"] == "8.5"


def test_normalize_apical_section_handles_missing_dose():
    """A dose without a values entry must fall back to '—', not KeyError."""
    raw = {
        "platform": "Hormones",
        "tables_json": {
            "Female": [
                {
                    "label": "T4",
                    "doses": [0.0, 1.0, 10.0],
                    "values": {"0": "5.5", "10": "3.2"},  # 1.0 missing
                    "bmd": "—", "bmdl": "—",
                },
            ],
        },
    }
    out = _normalize_apical_section(raw)
    assert out["table_data"]["Female"][0]["values"] == ["5.5", "—", "3.2"]


def test_convert_genomics_cache_produces_two_entries_per_organ_sex():
    """One gene_set entry and one gene entry per (organ, sex) tuple."""
    cache = {
        "liver_male": {
            "organ": "liver", "sex": "male",
            "gene_sets_by_stat": {
                "median": [{"rank": 1, "go_id": "GO:1", "go_term": "x",
                            "bmd": 1.0, "bmdl": 0.5, "n_genes": 10, "direction": "up"}],
            },
            "top_genes": [{"rank": 1, "gene_symbol": "FOXP1",
                           "bmd": 0.1, "bmdl": 0.05, "direction": "down",
                           "fold_change": -2.5}],
        },
    }
    out = _convert_genomics_cache(cache)
    assert len(out) == 2
    types = {e["type"] for e in out}
    assert types == {"gene_set", "gene"}
    gene_entry = next(e for e in out if e["type"] == "gene")
    # gene_symbol → gene rename for generator compatibility
    assert gene_entry["top_genes"][0]["gene"] == "FOXP1"


def test_load_session_data_returns_scaffold_for_missing_session(tmp_path, monkeypatch):
    """An unknown dtxsid yields the scaffold unchanged — no crash."""
    # Point _SESSIONS_DIR at an empty tmp directory so the lookup misses.
    import latex_export
    monkeypatch.setattr(latex_export, "_SESSIONS_DIR", tmp_path)
    data = load_session_data(
        dtxsid="DTXSID00000000",
        chemical_name="Test",
        casrn="00-00-0",
    )
    # Scaffold guarantees these keys exist
    assert "background" in data
    assert "methods" in data
    assert "abstract" in data


def test_load_session_data_overlays_real_session_when_present():
    """
    DTXSID50469320 is the golden session shipped in this repo.  Loading
    it must overlay real content — verify a few high-signal markers.
    """
    data = load_session_data(
        dtxsid="DTXSID50469320",
        chemical_name="Perfluorohexanesulfonamide",
        casrn="41997-13-1",
    )
    # Background prose should be real, not the scaffold's empty list
    assert data.get("background", {}).get("paragraphs"), \
        "Real background paragraphs should be loaded"
    # BMD summary should carry real apical endpoints
    endpoints = data.get("bmd_summary", {}).get("endpoints", [])
    assert len(endpoints) > 1, "Real session has many endpoints"
    # Genomics should be the converted list shape, not the original dict
    gs = data.get("genomics_sections", [])
    assert isinstance(gs, list)
    assert any(e.get("type") == "gene_set" for e in gs)
    assert any(e.get("type") == "gene" for e in gs)
