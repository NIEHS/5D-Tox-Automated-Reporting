"""refresh_caption_compound — re-interpolate the compound name in an apical caption.

The apical table captions bake the compound name at Process time; this helper lets
the render path re-interpolate the "Administered <compound> for Five Days" segment
with the currently-resolved name, so a session integrated before its name resolved
does not render the DTXSID in every caption.
"""

from tables.table_builder_common import refresh_caption_compound


def test_replaces_baked_dtxsid_with_resolved_name():
    cap = ("Summary of Body Weights of Male and Female Rats "
           "Administered DTXSID50469320 for Five Days")
    out = refresh_caption_compound(cap, "Perfluorohexanesulfonamide")
    assert out == ("Summary of Body Weights of Male and Female Rats "
                   "Administered Perfluorohexanesulfonamide for Five Days")
    assert "DTXSID" not in out


def test_works_across_platform_caption_forms():
    for prefix in (
        "Summary of Select Clinical Chemistry Data for Male and Female Rats ",
        "Summary of Select Hematology Data for Male and Female Rats ",
        "Summary of Liver Weights of Male Rats ",
        "Summary of Plasma Concentration Data for Male and Female Rats ",
    ):
        cap = prefix + "Administered DTXSID50469320 for Five Days"
        out = refresh_caption_compound(cap, "PFHxSAm")
        assert out == prefix + "Administered PFHxSAm for Five Days"


def test_noop_when_no_administered_segment():
    cap = "Top Gene Sets — Liver"           # a caption of another form
    assert refresh_caption_compound(cap, "PFHxSAm") == cap


def test_noop_on_empty_inputs():
    assert refresh_caption_compound("", "PFHxSAm") == ""
    cap = "Administered DTXSID50469320 for Five Days"
    assert refresh_caption_compound(cap, "") == cap   # no name → leave as-is
