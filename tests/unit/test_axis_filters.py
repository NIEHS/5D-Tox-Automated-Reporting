"""
Unit tests for the four sibling report-level allowlists — the axes generalized
from the organ filter (see test_organ_filter.py for the organ original):

    sex        — per-area {apical, genomics}, EXACT match
    assays     — per-area {clinical-chemistry, hematology}, component-aware
    genes      — flat list, component-aware (single-token in practice)
    gene_sets  — flat list, go_id == OR go_term-component

Pins the same layers the organ feature pins:
  1. the matchers (table_builder_common): sex_allowed / assay_allowed /
     gene_allowed / gene_set_allowed, plus the shared filter_genomics_sections
     aggregator and the apply_apical_filters apical aggregator;
  2. the loaders (document_template): the per-area MAPPING loaders
     (load_report_sex / load_report_assays) and the FLAT-list loaders
     (load_report_genes / load_report_gene_sets), with loud rejection of the
     wrong shape / unknown areas / non-strings;
  3. _hash_sections sensitivity — the apical sex + assay allowlists change the
     cache key (their output is cached), and an unfiltered key is unchanged.

An EMPTY/absent allowlist means NO filtering everywhere (backward compatible).
"""

import textwrap

import pytest

from bmdx_pipe import TableRow
from table_builder_common import (
    sex_allowed,
    assay_allowed,
    gene_allowed,
    gene_set_allowed,
    filter_genomics_sections,
)
from processing_helpers import apply_apical_filters, prune_card_sexes


# ---------------------------------------------------------------------------
# 1a. sex_allowed — EXACT, case-insensitive (NOT component-wise)
# ---------------------------------------------------------------------------

def test_sex_empty_allowlist_allows_everything():
    assert sex_allowed("Male", []) is True
    assert sex_allowed("Female", None) is True


def test_sex_exact_case_insensitive():
    assert sex_allowed("Male", ["male"]) is True
    assert sex_allowed("MALE", ["male"]) is True
    assert sex_allowed("  female ", ["female"]) is True
    assert sex_allowed("Female", ["male"]) is False


def test_sex_empty_candidate_rejected_against_nonempty():
    assert sex_allowed("", ["male"]) is False
    assert sex_allowed(None, ["male"]) is False


def test_sex_does_not_substring_match():
    # A component/substring matcher could wrongly cross between the two; sex is
    # exact, so a token that merely appears inside another value must not match.
    assert sex_allowed("Female", ["male"]) is False


# ---------------------------------------------------------------------------
# 1b. assay_allowed / gene_allowed — component-aware
# ---------------------------------------------------------------------------

def test_assay_component_match_covers_family():
    assert assay_allowed("Basophil count", ["count"]) is True
    assert assay_allowed("Leukocyte Count", ["count"]) is True
    assert assay_allowed("Hemoglobin", ["count"]) is False


def test_assay_whole_label_match():
    assert assay_allowed("Alanine aminotransferase",
                         ["alanine aminotransferase"]) is True
    assert assay_allowed("Albumin", ["albumin"]) is True
    assert assay_allowed("Albumin", ["albumin", "hemoglobin"]) is True


def test_assay_empty_allowlist_allows_everything():
    assert assay_allowed("Anything", []) is True
    assert assay_allowed("Anything", None) is True


def test_gene_exact_single_token():
    assert gene_allowed("EGR1", ["egr1"]) is True
    assert gene_allowed("egr1", ["egr1"]) is True
    assert gene_allowed("TNNI1", ["egr1"]) is False
    assert gene_allowed("DDIT4", ["egr1", "ddit4"]) is True


# ---------------------------------------------------------------------------
# 1c. gene_set_allowed — go_id == OR go_term-component
# ---------------------------------------------------------------------------

def test_gene_set_match_by_accession():
    assert gene_set_allowed("GO:0051301", "cell division", ["go:0051301"]) is True
    # accession compare is case-insensitive
    assert gene_set_allowed("GO:0051301", "cell division", ["GO:0051301".lower()]) is True


def test_gene_set_match_by_term_component():
    assert gene_set_allowed("GO:0051301", "cell division", ["division"]) is True
    assert gene_set_allowed("GO:0051301", "cell division", ["cell division"]) is True


def test_gene_set_miss():
    assert gene_set_allowed("GO:0051301", "cell division", ["apoptosis"]) is False


def test_gene_set_empty_allowlist_allows_everything():
    assert gene_set_allowed("GO:1", "whatever", []) is True
    assert gene_set_allowed("GO:1", "whatever", None) is True


# ---------------------------------------------------------------------------
# 2. filter_genomics_sections — the shared genomics aggregator
# ---------------------------------------------------------------------------

def _sections() -> dict:
    return {
        "liver_male": {
            "organ": "liver", "sex": "male",
            "top_genes": [{"gene_symbol": "EGR1"}, {"gene_symbol": "TNNI1"}],
            "all_genes": [{"gene_symbol": "EGR1"}, {"gene_symbol": "TNNI1"}],
            "gene_sets_by_stat": {"median": [
                {"rank": 1, "go_id": "GO:1", "go_term": "cell division"},
                {"rank": 2, "go_id": "GO:2", "go_term": "apoptosis"},
            ]},
            "gene_sets_chart_by_stat": {"median": [
                {"go_id": "GO:1", "go_term": "cell division"},
                {"go_id": "GO:2", "go_term": "apoptosis"},
            ]},
        },
        "liver_female": {"organ": "liver", "sex": "female",
                         "top_genes": [], "gene_sets_by_stat": {}},
        "kidney_male": {"organ": "kidney", "sex": "male",
                        "top_genes": [], "gene_sets_by_stat": {}},
    }


def test_genomics_filter_drops_by_organ_and_sex():
    out = filter_genomics_sections(_sections(), organ=["liver"], sex=["male"])
    assert set(out) == {"liver_male"}


def test_genomics_filter_prunes_genes():
    out = filter_genomics_sections(_sections(), genes=["egr1"])
    assert [g["gene_symbol"] for g in out["liver_male"]["top_genes"]] == ["EGR1"]
    assert [g["gene_symbol"] for g in out["liver_male"]["all_genes"]] == ["EGR1"]


def test_genomics_filter_prunes_gene_sets_and_reranks():
    out = filter_genomics_sections(_sections(), gene_sets=["division"])
    rows = out["liver_male"]["gene_sets_by_stat"]["median"]
    assert [(r["rank"], r["go_term"]) for r in rows] == [(1, "cell division")]
    # chart list pruned too (no rank to re-number)
    chart = out["liver_male"]["gene_sets_chart_by_stat"]["median"]
    assert [r["go_term"] for r in chart] == ["cell division"]


def test_genomics_filter_unfiltered_is_noop():
    sections = _sections()
    assert filter_genomics_sections(sections) == sections
    assert filter_genomics_sections(sections, organ=[], sex=[],
                                    genes=[], gene_sets=[]) == sections


def test_genomics_filter_does_not_mutate_input():
    sections = _sections()
    filter_genomics_sections(sections, genes=["egr1"])
    # original liver_male still has both genes
    assert len(sections["liver_male"]["top_genes"]) == 2


# ---------------------------------------------------------------------------
# 3. apply_apical_filters — the apical platform_tables aggregator
# ---------------------------------------------------------------------------

def _row(label: str) -> TableRow:
    return TableRow(
        label=label,
        values_by_dose={0.0: "1.0", 10.0: "2.0"},
        n_by_dose={0.0: 5, 10.0: 5},
        bmd_str="ND", bmdl_str="ND", trend_marker="", responsive=False,
    )


def _platform_tables() -> dict:
    return {
        "Body Weight": {"Male": [_row("Day 1")], "Female": [_row("Day 1")]},
        "Clinical Chemistry": {
            "Male": [_row("Albumin"), _row("Hemoglobin")],
            "Female": [_row("Albumin")],
        },
        "Hematology": {"Male": [_row("Basophil count"), _row("Hematocrit")]},
        "Hormones": {"Male": [_row("Total Thyroxine")]},
    }


def test_apical_filter_drops_sex_everywhere():
    out = apply_apical_filters(_platform_tables(), sex_allow=["male"])
    assert sorted(out["Body Weight"]) == ["Male"]
    assert sorted(out["Clinical Chemistry"]) == ["Male"]


def test_apical_filter_drops_assay_rows_in_scope_platforms():
    out = apply_apical_filters(
        _platform_tables(),
        assay_filters={"clinical-chemistry": ["albumin"], "hematology": ["count"]},
    )
    assert [r.label for r in out["Clinical Chemistry"]["Male"]] == ["Albumin"]
    # hematology component match keeps "Basophil count", drops "Hematocrit"
    assert [r.label for r in out["Hematology"]["Male"]] == ["Basophil count"]


def test_apical_filter_does_not_touch_hormones_or_body_weight_rows():
    # Assay filter is scoped to clin-chem + hematology; Hormones + Body Weight
    # rows pass through untouched even with an assay filter set.
    out = apply_apical_filters(
        _platform_tables(),
        assay_filters={"clinical-chemistry": ["albumin"]},
    )
    assert [r.label for r in out["Hormones"]["Male"]] == ["Total Thyroxine"]
    assert [r.label for r in out["Body Weight"]["Male"]] == ["Day 1"]


def test_apical_filter_unfiltered_is_noop_identity():
    pt = _platform_tables()
    assert apply_apical_filters(pt) is pt


def test_prune_card_sexes_drops_disallowed_sex():
    card = {"platform": "Tissue Concentration",
            "tables_json": {"Male": [1], "Female": [2]}}
    out = prune_card_sexes(card, ["male"])
    assert set(out["tables_json"]) == {"Male"}


def test_prune_card_sexes_noop_without_allowlist():
    card = {"tables_json": {"Male": [1], "Female": [2]}}
    out = prune_card_sexes(card, None)
    assert set(out["tables_json"]) == {"Male", "Female"}


# ---------------------------------------------------------------------------
# 4. Loaders — per-area MAPPING (sex, assays) + FLAT list (genes, gene_sets)
# ---------------------------------------------------------------------------

@pytest.fixture
def template_dir(tmp_path, monkeypatch):
    import document_template as dt
    monkeypatch.setattr(dt, "TEMPLATES_DIR", tmp_path)
    return tmp_path


def _write(template_dir, body: str) -> str:
    name = "axis_test_template"
    (template_dir / f"{name}.yaml").write_text(textwrap.dedent(body), encoding="utf-8")
    return name


def test_load_sex_per_area_lowercased(template_dir):
    import document_template as dt
    name = _write(template_dir, """
        document: []
        sex:
          apical: [Male]
          genomics: ["  MALE  "]
    """)
    assert dt.load_report_sex(name) == {"apical": ["male"], "genomics": ["male"]}


def test_load_sex_missing_returns_empty(template_dir):
    import document_template as dt
    name = _write(template_dir, "document: []\n")
    assert dt.load_report_sex(name) == {}


def test_load_sex_unknown_area_rejected(template_dir):
    import document_template as dt
    name = _write(template_dir, """
        document: []
        sex:
          apicall: [male]
    """)
    with pytest.raises(ValueError, match="unknown sex area"):
        dt.load_report_sex(name)


def test_load_sex_flat_list_rejected(template_dir):
    import document_template as dt
    name = _write(template_dir, """
        document: []
        sex: [male]
    """)
    with pytest.raises(ValueError, match="must be a mapping"):
        dt.load_report_sex(name)


def test_load_assays_per_area(template_dir):
    import document_template as dt
    name = _write(template_dir, """
        document: []
        assays:
          clinical-chemistry: [Albumin, "Alanine Aminotransferase"]
          hematology: [Hemoglobin]
    """)
    assert dt.load_report_assays(name) == {
        "clinical-chemistry": ["albumin", "alanine aminotransferase"],
        "hematology": ["hemoglobin"],
    }


def test_load_assays_unknown_area_rejected(template_dir):
    import document_template as dt
    name = _write(template_dir, """
        document: []
        assays:
          hormones: [thyroxine]
    """)
    with pytest.raises(ValueError, match="unknown assays area"):
        dt.load_report_assays(name)


def test_load_genes_flat_list_lowercased(template_dir):
    import document_template as dt
    name = _write(template_dir, """
        document: []
        genes: [EGR1, "  Ddit4 "]
    """)
    assert dt.load_report_genes(name) == ["egr1", "ddit4"]


def test_load_genes_missing_returns_empty(template_dir):
    import document_template as dt
    name = _write(template_dir, "document: []\n")
    assert dt.load_report_genes(name) == []


def test_load_genes_mapping_rejected(template_dir):
    import document_template as dt
    name = _write(template_dir, """
        document: []
        genes:
          liver: [egr1]
    """)
    with pytest.raises(ValueError, match="must be a list"):
        dt.load_report_genes(name)


def test_load_gene_sets_flat_list(template_dir):
    import document_template as dt
    name = _write(template_dir, """
        document: []
        gene_sets: ["GO:1902893", "cell division"]
    """)
    assert dt.load_report_gene_sets(name) == ["go:1902893", "cell division"]


def test_load_genes_non_string_rejected(template_dir):
    import document_template as dt
    name = _write(template_dir, """
        document: []
        genes: [42]
    """)
    with pytest.raises(ValueError, match="must be a string"):
        dt.load_report_genes(name)


# --- charts allowlist: presence is the switch (absent=None, []=none) ---------

def test_load_charts_absent_returns_none(template_dir):
    # Distinct from the token allowlists: absence means "no filtering" (None),
    # so every chart type renders.
    import document_template as dt
    name = _write(template_dir, "document: []\n")
    assert dt.load_report_charts(name) is None


def test_load_charts_empty_list_is_render_none(template_dir):
    # An explicit empty list is NOT "no filtering" — it renders zero charts.
    import document_template as dt
    name = _write(template_dir, """
        document: []
        charts: []
    """)
    assert dt.load_report_charts(name) == []


def test_load_charts_lowercased_list(template_dir):
    import document_template as dt
    name = _write(template_dir, """
        document: []
        charts: [UMAP, "  Cluster  "]
    """)
    assert dt.load_report_charts(name) == ["umap", "cluster"]


def test_load_charts_mapping_rejected(template_dir):
    import document_template as dt
    name = _write(template_dir, """
        document: []
        charts: { umap: true }
    """)
    with pytest.raises(ValueError, match="must be a list"):
        dt.load_report_charts(name)


def test_load_charts_non_string_rejected(template_dir):
    import document_template as dt
    name = _write(template_dir, """
        document: []
        charts: [42]
    """)
    with pytest.raises(ValueError, match="must be a string"):
        dt.load_report_charts(name)


# ---------------------------------------------------------------------------
# 5. _hash_sections — apical sex + assay sensitivity + backward compat
# ---------------------------------------------------------------------------

def test_hash_sections_unfiltered_is_backward_compatible():
    from cache_plumbing import _hash_sections
    legacy = _hash_sections("nt", "C", "mg/kg", sidecar_hash="s", imputed_cells=None)
    none_ = _hash_sections("nt", "C", "mg/kg", sidecar_hash="s",
                           imputed_cells=None, sex_allowlist=None, assay_filters=None)
    empty = _hash_sections("nt", "C", "mg/kg", sidecar_hash="s",
                           imputed_cells=None, sex_allowlist=[], assay_filters={})
    empty_inner = _hash_sections("nt", "C", "mg/kg", sidecar_hash="s",
                                 imputed_cells=None,
                                 assay_filters={"clinical-chemistry": []})
    assert legacy == none_ == empty == empty_inner


def test_hash_sections_changes_with_sex_allowlist():
    from cache_plumbing import _hash_sections
    base = _hash_sections("nt", "C", "mg/kg", sidecar_hash="s", imputed_cells=None)
    filt = _hash_sections("nt", "C", "mg/kg", sidecar_hash="s",
                          imputed_cells=None, sex_allowlist=["male"])
    assert filt != base


def test_hash_sections_changes_with_assay_filters_order_independent():
    from cache_plumbing import _hash_sections
    base = _hash_sections("nt", "C", "mg/kg", sidecar_hash="s", imputed_cells=None)
    filt = _hash_sections("nt", "C", "mg/kg", sidecar_hash="s", imputed_cells=None,
                          assay_filters={"clinical-chemistry": ["albumin"]})
    assert filt != base
    a = _hash_sections("nt", "C", "mg/kg", sidecar_hash="s", imputed_cells=None,
                       assay_filters={"clinical-chemistry": ["albumin", "alt"]})
    b = _hash_sections("nt", "C", "mg/kg", sidecar_hash="s", imputed_cells=None,
                       assay_filters={"clinical-chemistry": ["alt", "albumin"]})
    assert a == b
