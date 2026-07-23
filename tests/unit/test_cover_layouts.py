"""
Unit tests for the cover-layout registry (cover_layouts.py).

Pins the contract the cover/title-page renderers depend on:
  1. The default subtype resolves; an unknown subtype raises.
  2. required_assets de-dups across subtypes (incl. None → default).
  3. The title / publisher builders produce the expected NIEHS lines from data.
  4. Every registered layout's assets exist on disk under assets/.
  5. validate_layout rejects a malformed layout.
"""

import pytest

import cover_layouts as cl


def test_default_subtype_resolves():
    layout = cl.get_cover_layout(None)
    assert layout.name == cl.DEFAULT_COVER_SUBTYPE
    assert layout.assets  # non-empty


def test_explicit_subtype_resolves():
    assert cl.get_cover_layout("niehs-5d-tox").name == "niehs-5d-tox"


def test_unknown_subtype_raises():
    with pytest.raises(ValueError, match="unknown cover subtype"):
        cl.get_cover_layout("does-not-exist")


def test_required_assets_dedups_and_includes_default():
    # None → default; passing the default name too must not duplicate.
    assets = cl.required_assets([None, "niehs-5d-tox"])
    assert assets == ["cover-bg.jpg", "nih-logo.png"]


def test_title_builder_includes_casrn_and_strain():
    lines = cl.get_cover_layout(None).title_builder(
        {"chemical_name": "Perfluorohexanesulfonamide", "casrn": "41997-13-1"}
    )
    # The header line stands alone; the rest is width-wrapped, so assert on the
    # JOINED title (the chemical, its CASRN, and the strain all appear).
    assert lines[0] == "NIEHS Report on the"
    joined = " ".join(lines)
    assert "Perfluorohexanesulfonamide (CASRN 41997-13-1)" in joined
    assert "Sprague Dawley" in joined and "®" in joined


def test_title_builder_wraps_to_width():
    """Width-aware wrapping: no line overflows _TITLE_MAX_CHARS, so Word never
    re-wraps a title line mid-phrase (the reported auto-wrap bug)."""
    lines = cl.get_cover_layout(None).title_builder(
        {"chemical_name": "Perfluorohexanesulfonamide", "casrn": "41997-13-1"}
    )
    assert all(len(ln) <= cl._TITLE_MAX_CHARS for ln in lines), lines


def test_title_builder_omits_casrn_when_absent():
    lines = cl.get_cover_layout(None).title_builder({"chemical_name": "Acme"})
    assert "Acme" in " ".join(lines)
    assert not any("CASRN" in ln for ln in lines)


def test_publisher_builder_includes_issn_only_when_present():
    with_issn = cl.get_cover_layout(None).publisher_builder({"issn": "2768-5632"})
    assert "ISSN: 2768-5632" in with_issn
    without = cl.get_cover_layout(None).publisher_builder({})
    assert not any(ln.startswith("ISSN:") for ln in without)
    # the static lines are always present
    assert "Public Health Service" in without
    assert "Research Triangle Park, North Carolina, USA" in without


def test_registered_assets_exist_on_disk():
    for name in cl.required_assets(cl._COVER_LAYOUTS):
        assert cl.asset_path(name).exists(), f"missing cover asset {name}"


def test_validate_layout_rejects_empty_assets():
    bad = cl.CoverLayout(
        name="bad", assets=(), palette={"x": "000000"},
        title_builder=lambda d: [], publisher_builder=lambda d: [],
    )
    with pytest.raises(ValueError, match="no assets"):
        cl.validate_layout(bad)


def test_metrics_carry_accent_bar_vertices():
    m = cl.get_cover_layout(None).metrics
    # the parallelogram vertices the LaTeX cover consumes
    assert m["bar_dark"][0] == (0.0, 102.2)
    assert m["bg_top"] == 119.0
