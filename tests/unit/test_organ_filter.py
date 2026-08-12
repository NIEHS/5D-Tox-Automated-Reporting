"""
Unit tests for the per-area report-level organ allowlist (limiting factor).

Pins the layers of the feature:
  1. organ_allowed (table_builder_common) — the shared, case-insensitive,
     COMPONENT-AWARE matcher (so one token covers split-laterality apical
     labels like "Kidney-Left" as well as the clean genomics "kidney");
  2. load_report_organs (document_template) — the per-area `organs:` MAPPING
     loader, with loud rejection of the old flat-list shape / unknown areas;
  3. the genomics post-filter — drop genomics_sections entries by organ;
  4. the apical organ-weight narrative filter + the clinical-chemistry scope
     guard (endpoints _parse_organ_label also names must NOT be dropped);
  5. _hash_sections sensitivity — the organ-weight allowlist changes the cache
     key (its output is cached prose), and an unfiltered key is unchanged.

An EMPTY/absent allowlist means NO filtering everywhere (backward compatible).
"""

import textwrap

import pytest

from bmdx_pipe import TableRow
from tables.table_builder_common import organ_allowed


# ---------------------------------------------------------------------------
# 1. organ_allowed — the component-aware matcher
# ---------------------------------------------------------------------------

def test_empty_allowlist_allows_everything():
    assert organ_allowed("Liver", []) is True
    assert organ_allowed("Liver", None) is True
    assert organ_allowed("", []) is True


def test_whole_token_match_case_insensitive():
    assert organ_allowed("kidney", ["kidney"]) is True
    assert organ_allowed("KIDNEY", ["kidney"]) is True
    assert organ_allowed("  Kidney ", ["kidney"]) is True
    assert organ_allowed("liver", ["kidney"]) is False


def test_component_match_covers_laterality_labels():
    # The real apical organ-weight labels split laterality; one token must cover
    # all of them (and the genomics clean token), while dropping other organs.
    assert organ_allowed("Kidney-Left", ["kidney"]) is True
    assert organ_allowed("Kidney-Right", ["kidney"]) is True
    assert organ_allowed("R. Kidney", ["kidney"]) is True
    assert organ_allowed("Liver", ["kidney"]) is False
    assert organ_allowed("Heart", ["kidney"]) is False


def test_empty_candidate_against_nonempty_allowlist_is_rejected():
    assert organ_allowed("", ["kidney"]) is False
    assert organ_allowed(None, ["kidney"]) is False


def test_multi_token_allowlist():
    assert organ_allowed("Liver", ["liver", "kidney"]) is True
    assert organ_allowed("Kidney-Left", ["liver", "kidney"]) is True
    assert organ_allowed("Heart", ["liver", "kidney"]) is False


# ---------------------------------------------------------------------------
# 2. load_report_organs — the per-area MAPPING loader
# ---------------------------------------------------------------------------

@pytest.fixture
def template_dir(tmp_path, monkeypatch):
    import document_template as dt
    monkeypatch.setattr(dt, "TEMPLATES_DIR", tmp_path)
    return tmp_path


def _write(template_dir, body: str) -> str:
    name = "organ_test_template"
    (template_dir / f"{name}.yaml").write_text(textwrap.dedent(body), encoding="utf-8")
    return name


def test_missing_organs_key_returns_empty(template_dir):
    import document_template as dt
    name = _write(template_dir, """
        document:
          - id: x
            type: narrative
            title: X
            data_key: d
    """)
    assert dt.load_report_organs(name) == {}


def test_bare_list_template_returns_empty(template_dir):
    import document_template as dt
    name = _write(template_dir, """
        - id: x
          type: narrative
          title: X
          data_key: d
    """)
    assert dt.load_report_organs(name) == {}


def test_per_area_block_lowercased_and_stripped(template_dir):
    import document_template as dt
    name = _write(template_dir, """
        document: []
        organs:
          genomics: [Kidney]
          organ-weight: ["  LIVER  ", Kidney]
    """)
    assert dt.load_report_organs(name) == {
        "genomics": ["kidney"],
        "organ-weight": ["liver", "kidney"],
    }


def test_flat_list_organs_block_is_rejected(template_dir):
    # The old flat-list shape is no longer valid — must be a per-area mapping.
    import document_template as dt
    name = _write(template_dir, """
        document: []
        organs:
          - kidney
    """)
    with pytest.raises(ValueError, match="must be a mapping"):
        dt.load_report_organs(name)


def test_unknown_area_key_is_rejected(template_dir):
    import document_template as dt
    name = _write(template_dir, """
        document: []
        organs:
          genomic: [kidney]
    """)
    with pytest.raises(ValueError, match="unknown organ area"):
        dt.load_report_organs(name)


def test_area_value_must_be_a_list(template_dir):
    import document_template as dt
    name = _write(template_dir, """
        document: []
        organs:
          genomics:
            kidney: true
    """)
    with pytest.raises(ValueError, match="must be a list"):
        dt.load_report_organs(name)


def test_area_entries_must_be_strings(template_dir):
    import document_template as dt
    name = _write(template_dir, """
        document: []
        organs:
          genomics: [42]
    """)
    with pytest.raises(ValueError, match="must be a string"):
        dt.load_report_organs(name)


# ---------------------------------------------------------------------------
# 3. Genomics post-filter — the dict comprehension from _get_genomics
# ---------------------------------------------------------------------------

def _filter_genomics(sections: dict, allow) -> dict:
    if allow and sections:
        return {
            k: v for k, v in sections.items()
            if organ_allowed(v.get("organ", ""), allow)
        }
    return sections


def test_genomics_post_filter_drops_unlisted_organs():
    sections = {
        "liver_male":    {"organ": "liver", "sex": "male"},
        "kidney_male":   {"organ": "kidney", "sex": "male"},
        "kidney_female": {"organ": "kidney", "sex": "female"},
    }
    out = _filter_genomics(sections, ["kidney"])
    assert set(out) == {"kidney_male", "kidney_female"}


def test_genomics_post_filter_noop_when_allowlist_empty():
    sections = {"liver_male": {"organ": "liver"}}
    assert _filter_genomics(sections, []) == sections
    assert _filter_genomics(sections, None) == sections


# ---------------------------------------------------------------------------
# 4. Apical organ-weight narrative filter + clinical-chem scope guard
# ---------------------------------------------------------------------------

def _row(label: str, responsive: bool = True) -> TableRow:
    return TableRow(
        label=label,
        values_by_dose={0.0: "100.0 ± 5.0", 10.0: "130.0 ± 6.0**"},
        n_by_dose={0.0: 10, 10.0: 10},
        bmd_str="5.0",
        bmdl_str="3.0",
        trend_marker="**",
        responsive=responsive,
        loel=10.0,
    )


def test_organ_weight_narrative_honors_allowlist():
    from unified_narrative import _build_organ_weight_paragraphs

    platform_tables = {
        "Organ Weight": {
            "Male": [
                _row("Liver Absolute"),
                _row("Liver Relative"),
                _row("Kidney Absolute"),
            ],
        }
    }
    text = " ".join(_build_organ_weight_paragraphs(
        platform_tables, "TestChem", "mg/kg", organ_allowlist=["kidney"]
    )).lower()
    assert "kidney" in text
    assert "liver" not in text


def test_organ_weight_narrative_component_match_laterality():
    from unified_narrative import _build_organ_weight_paragraphs

    platform_tables = {
        "Organ Weight": {
            "Male": [_row("Kidney-Left Absolute"), _row("Kidney-Right Absolute"),
                     _row("Liver Absolute")],
        }
    }
    text = " ".join(_build_organ_weight_paragraphs(
        platform_tables, "TestChem", "mg/kg", organ_allowlist=["kidney"]
    )).lower()
    assert "kidney" in text
    assert "liver" not in text


def test_organ_weight_narrative_unfiltered_when_no_allowlist():
    from unified_narrative import _build_organ_weight_paragraphs

    platform_tables = {
        "Organ Weight": {
            "Male": [_row("Liver Absolute"), _row("Kidney Absolute")],
        }
    }
    text = " ".join(_build_organ_weight_paragraphs(
        platform_tables, "TestChem", "mg/kg"
    )).lower()
    assert "kidney" in text and "liver" in text


def test_clinical_chem_endpoints_not_dropped_by_organ_filter():
    """Scope guard: the clinical-pathology narrative takes NO organ allowlist, so
    a clinical-chemistry endpoint (which _parse_organ_label also names) survives
    regardless of any organ-weight filter."""
    from unified_narrative import generate_clinical_pathology_narrative

    platform_tables = {
        "Clinical Chemistry": {
            "Male": [_row("Alanine aminotransferase")],
        }
    }
    paras = generate_clinical_pathology_narrative(platform_tables, "TestChem", "mg/kg")
    assert paras  # the endpoint was not filtered away


# ---------------------------------------------------------------------------
# 5. _hash_sections — organ-weight allowlist sensitivity + backward compat
# ---------------------------------------------------------------------------

def test_hash_sections_unfiltered_is_backward_compatible():
    from cache_plumbing import _hash_sections
    legacy = _hash_sections("nt", "C", "mg/kg", sidecar_hash="s", imputed_cells=None)
    none_ = _hash_sections("nt", "C", "mg/kg", sidecar_hash="s",
                           imputed_cells=None, organ_allowlist=None)
    empty = _hash_sections("nt", "C", "mg/kg", sidecar_hash="s",
                           imputed_cells=None, organ_allowlist=[])
    assert legacy == none_ == empty


def test_hash_sections_changes_with_allowlist_and_is_order_independent():
    from cache_plumbing import _hash_sections
    base = _hash_sections("nt", "C", "mg/kg", sidecar_hash="s", imputed_cells=None)
    filt = _hash_sections("nt", "C", "mg/kg", sidecar_hash="s",
                          imputed_cells=None, organ_allowlist=["kidney"])
    assert filt != base
    a = _hash_sections("nt", "C", "mg/kg", sidecar_hash="s",
                       imputed_cells=None, organ_allowlist=["liver", "kidney"])
    b = _hash_sections("nt", "C", "mg/kg", sidecar_hash="s",
                       imputed_cells=None, organ_allowlist=["kidney", "liver"])
    assert a == b
