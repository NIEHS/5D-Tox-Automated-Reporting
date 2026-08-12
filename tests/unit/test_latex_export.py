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
from document_model.cover_layouts import asset_path
from latex_generator import generate_main_tex, generate_report_body
from report_data import scaffold_report_data


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
    """All required entries must be present at the zip root (Option B split:
    main.tex is the entry, report.tex the body)."""
    with zipfile.ZipFile(bundle_path) as zf:
        names = set(zf.namelist())
    assert "main.tex" in names
    assert "report.tex" in names
    assert "niehs.cls" in names
    assert "cover-bg.jpg" in names  # branded-cover background (cover node \includegraphics)
    assert "nih-logo.png" in names  # NIH badge for the cover header band
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

def test_split_tex_matches_generator_output(bundle_path, scaffold):
    """
    The .tex files inside the zip must be exactly what the generator produces
    for the same data — the bundler is a thin wrapper, not a second renderer.
    Option B: report.tex is the body, main.tex is the preamble that \\inputs it.
    """
    with zipfile.ZipFile(bundle_path) as zf:
        report_in_zip = zf.read("report.tex").decode("utf-8")
        main_in_zip = zf.read("main.tex").decode("utf-8")
    assert report_in_zip == generate_report_body(scaffold)
    assert main_in_zip == generate_main_tex(scaffold)
    # main.tex is the entry that pulls in the body; report.tex is body-only
    # (no preamble of its own).
    assert "\\input{report}" in main_in_zip
    assert "\\documentclass" not in report_in_zip


def test_class_file_matches_source(bundle_path):
    """niehs.cls in the zip must be byte-identical to the source-tree class."""
    with zipfile.ZipFile(bundle_path) as zf:
        cls_in_zip = zf.read("niehs.cls").decode("utf-8")
    assert cls_in_zip == CLASS_FILE.read_text()


def test_cover_image_matches_source(bundle_path):
    """cover-bg.jpg in the zip must be byte-identical to the assets/ source image
    (the cover node's \\includegraphics{cover-bg.jpg} resolves it at the root)."""
    with zipfile.ZipFile(bundle_path) as zf:
        img_in_zip = zf.read("cover-bg.jpg")
    assert img_in_zip == asset_path("cover-bg.jpg").read_bytes()


def test_cover_logo_matches_source(bundle_path):
    """nih-logo.png in the zip must be byte-identical to the assets/ source badge."""
    with zipfile.ZipFile(bundle_path) as zf:
        logo_in_zip = zf.read("nih-logo.png")
    assert logo_in_zip == asset_path("nih-logo.png").read_bytes()


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


def test_convert_genomics_cache_produces_two_entries_per_organ():
    """One gene_set entry and one gene entry PER ORGAN (both sexes stacked in a
    `sexes` list — reference Tables 9–12), not per (organ, sex)."""
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
        "liver_female": {
            "organ": "liver", "sex": "female",
            "gene_sets_by_stat": {"median": [{"rank": 1, "go_id": "GO:2"}]},
            "top_genes": [{"rank": 1, "gene_symbol": "BAR"}],
        },
    }
    out = _convert_genomics_cache(cache)
    # Two organ×sex inputs for the SAME organ collapse to 2 entries total.
    assert len(out) == 2
    types = {e["type"] for e in out}
    assert types == {"gene_set", "gene"}
    gene_entry = next(e for e in out if e["type"] == "gene")
    # Both sexes present as ordered blocks (Male before Female).
    assert [b["sex"] for b in gene_entry["sexes"]] == ["male", "female"]
    # gene_symbol → gene rename for generator compatibility, inside each block.
    assert gene_entry["sexes"][0]["top_genes"][0]["gene"] == "FOXP1"
    # No interpretations arg ⇒ no narrative attached (pre-feature behavior).
    assert "narrative" not in gene_entry
    gene_set_entry = next(e for e in out if e["type"] == "gene_set")
    assert "narrative" not in gene_set_entry


def test_convert_genomics_cache_attaches_interpretation_narrative():
    """
    With an interpretations map, the gene_set entry gets gene_set_narrative
    and the gene entry gets gene_narrative for the matching (organ, sex).
    """
    cache = {
        "liver_male": {
            "organ": "liver", "sex": "male",
            "gene_sets_by_stat": {"median": [{"rank": 1, "go_id": "GO:1"}]},
            "top_genes": [{"rank": 1, "gene_symbol": "FOXP1"}],
        },
    }
    interpretations = {
        ("liver", "male"): {
            "gene_set_narrative": ["Hepatic gene sets were dose-responsive."],
            "gene_narrative": ["Foxp1 showed a low BMD."],
        },
    }
    out = _convert_genomics_cache(cache, interpretations)
    gene_set_entry = next(e for e in out if e["type"] == "gene_set")
    gene_entry = next(e for e in out if e["type"] == "gene")
    assert gene_set_entry["narrative"] == ["Hepatic gene sets were dose-responsive."]
    assert gene_entry["narrative"] == ["Foxp1 showed a low BMD."]
    # An organ×sex with no interpretation leaves narrative unset.
    cache["kidney_female"] = {
        "organ": "kidney", "sex": "female",
        "gene_sets_by_stat": {"median": []}, "top_genes": [],
    }
    out2 = _convert_genomics_cache(cache, interpretations)
    kidney_entries = [e for e in out2 if e.get("organ") == "kidney"]
    assert kidney_entries and all("narrative" not in e for e in kidney_entries)


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
    # Phase 5 overlays: references list and the Appendix B animal roster.
    # (Genomics charts are NOT asserted here — the active template ships
    # `charts: []`, suppressing every genomics figure to match the reference,
    # which has no main-body charts.  The enabled/disabled attach contract is
    # unit-tested directly in test_genomics_charts.py.)
    assert data.get("references", {}).get("paragraphs"), \
        "References should be surfaced from background.json"
    assert data.get("appendix_animals"), \
        "Appendix B animal roster should be loaded"
    # Methods prose: the LLM Methods cache must be overlaid so the M&M
    # subsections render real text instead of "[Section pending]".  The
    # template's `study_design` methods_key is a stable anchor.
    methods_sections = data.get("methods", {}).get("sections", [])
    assert methods_sections, "Methods cache should be overlaid"
    by_key = {s.get("key"): s for s in methods_sections if isinstance(s, dict)}
    assert by_key.get("study_design", {}).get("paragraphs"), \
        "Study Design M&M subsection should carry real paragraphs"
    # Genomics LLM interpretation: at least one converted entry must now carry
    # the per-organ×sex interpretation narrative (was dropped pre-fix).
    assert any(e.get("narrative") for e in gs), \
        "Genomics entries should carry the LLM interpretation narrative"
    # Abstract assembled from caches (Background + Results + Summary).
    abstract_sections = {
        s.get("label"): s.get("text")
        for s in data.get("abstract", {}).get("sections", [])
    }
    assert abstract_sections.get("Results"), \
        "Abstract Results should be assembled from the BMD summary + genomics"


# ---------------------------------------------------------------------------
# Tests — chart-figure closure + decode guard (ADR-0003 Phase 5)
# ---------------------------------------------------------------------------

# A valid 1x1 PNG (base64) used to drive the figure-writing path deterministically.
_TINY_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAA"
    "C0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def test_every_includegraphics_resolves_to_a_written_figure(scaffold, tmp_path):
    r"""
    The renderer<->bundler closure: every figures/<name> the .tex references via
    \includegraphics must be a file the bundle actually wrote — otherwise the
    Overleaf compile fails on a missing figure.  This is the integration test
    the deliverable path previously lacked (only the manual /tmp baseline diff
    covered it).
    """
    import copy
    import re
    data = copy.deepcopy(scaffold)
    data["genomics_sections"] = [{
        "type": "gene_set", "organ": "liver", "sex": "male", "gene_sets": [],
        "charts": [{
            "key": "umap",
            "filename": "genomics-liver-male-umap.png",
            "png_b64": _TINY_PNG,
            "caption": "UMAP",
        }],
    }]
    out = build_overleaf_bundle(data, tmp_path / "charted.zip")
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        tex = zf.read("report.tex").decode("utf-8")
    refs = re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{(figures/[^}]+)\}", tex)
    assert refs, "expected at least one \\includegraphics in the charted bundle"
    missing = [r for r in refs if r not in names]
    assert not missing, f"\\includegraphics targets missing from the bundle: {missing}"


def test_decode_png_rejects_garbage_accepts_valid():
    from latex_export import _decode_png
    assert _decode_png(None) is None
    assert _decode_png("") is None
    assert _decode_png("AAAAA") is None        # invalid base64 length
    assert _decode_png(_TINY_PNG) is not None


def test_attach_genomics_charts_drops_undecodable():
    """A chart whose base64 won't decode is dropped at attach time, so it can
    never reach the renderer as a figure with no backing file."""
    from latex_export import _attach_genomics_charts
    sections = [{"type": "gene_set", "organ": "liver", "sex": "male"}]
    _attach_genomics_charts(sections, [{
        "organ": "liver", "sex": "male",
        "umap_png": "AAAAA",          # undecodable → dropped
        "cluster_png": _TINY_PNG,     # valid → kept
    }])
    keys = [c["key"] for c in sections[0].get("charts", [])]
    assert keys == ["cluster"], f"undecodable umap should be dropped, got {keys}"


def test_attach_genomics_charts_attaches_valid_with_filename():
    from latex_export import _attach_genomics_charts
    sections = [{"type": "gene_set", "organ": "Liver", "sex": "Male"}]
    _attach_genomics_charts(sections, [{
        "organ": "liver", "sex": "male", "umap_png": _TINY_PNG, "umap_caption": "U",
    }])
    charts = sections[0].get("charts", [])
    assert len(charts) == 1
    assert charts[0]["filename"] == "genomics-liver-male-umap.png"
    assert charts[0]["figure_number"] == 1  # ADR-0004 amendment (e)


def test_attach_genomics_charts_numbers_figures_sequentially_across_entries():
    """Figure numbers are positional across ALL attached charts — sequential in
    render order (entries iterate in genomics_sections order, charts within an
    entry iterate umap → cluster).  ADR-0004 amendment (e)."""
    from latex_export import _attach_genomics_charts
    sections = [
        {"type": "gene_set", "organ": "kidney", "sex": "female"},
        {"type": "gene_set", "organ": "liver",  "sex": "male"},
    ]
    cache = [
        {"organ": "kidney", "sex": "female",
         "umap_png": _TINY_PNG, "cluster_png": _TINY_PNG},
        {"organ": "liver", "sex": "male",
         "umap_png": _TINY_PNG, "cluster_png": _TINY_PNG},
    ]
    _attach_genomics_charts(sections, cache)
    nums = [(c["key"], c["figure_number"])
            for s in sections for c in s.get("charts", [])]
    assert nums == [("umap", 1), ("cluster", 2), ("umap", 3), ("cluster", 4)]
