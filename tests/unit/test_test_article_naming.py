"""The test article's abbreviation is the study's, never the model's
(narrative.test_article): every prompt that names the chemical states it."""

from narrative.report_summary import build_report_summary
from narrative.test_article import abbreviation_of, naming_rule

_APICAL = [{"endpoint": "Liver Weight", "sex": "Male", "bmd": 10.0, "bmdl": 5.0}]


def test_rule_gives_the_recorded_abbreviation():
    rule = naming_rule("Perfluorohexanesulfonamide", "PFHxSAm")
    assert '"Perfluorohexanesulfonamide (PFHxSAm)"' in rule
    assert "no other abbreviation" in rule


def test_rule_forbids_coining_one_when_none_is_recorded():
    rule = naming_rule("Triclosan", "")
    assert "do not coin one" in rule
    assert "(" not in rule


def test_abbreviation_of_identity():
    assert abbreviation_of({"abbreviation": " PFHxSAm "}) == "PFHxSAm"
    assert abbreviation_of({"name": "Triclosan"}) == ""
    assert abbreviation_of(None) == ""


def test_summary_uses_the_abbreviation_the_background_introduced():
    first = build_report_summary(
        _APICAL, {}, chemical_name="Perfluorohexanesulfonamide", abbreviation="PFHxSAm",
        abstract_background="Perfluorohexanesulfonamide (PFHxSAm) is a PFAS.")[0]
    assert first.endswith("biological potency of PFHxSAm.")


def test_summary_introduces_the_abbreviation_itself_without_a_background():
    first = build_report_summary(
        _APICAL, {}, chemical_name="Perfluorohexanesulfonamide", abbreviation="PFHxSAm")[0]
    assert "potency of Perfluorohexanesulfonamide (PFHxSAm)." in first


def test_summary_names_the_chemical_when_no_abbreviation():
    first = build_report_summary(_APICAL, {}, chemical_name="Triclosan")[0]
    assert first.endswith("biological potency of Triclosan.")
