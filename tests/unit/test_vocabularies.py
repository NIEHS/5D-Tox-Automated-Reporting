"""
Unit tests for ui_api.vocabularies — what a form field is bound to
(MODULES.md §4.5, GET /api/v2/vocabularies).
"""

import re

from ui_api.vocabularies import id_patterns, vocabularies, vocabularies_payload


def test_the_vocabularies_are_bmdx_pipes_with_strain_by_species():
    from bmdx_pipe import VOCABULARIES

    served = vocabularies()["vocabularies"]
    assert set(served) == set(VOCABULARIES)
    assert served["species"] == {"label": "Species", "values": list(VOCABULARIES["species"])}
    assert served["strain"] == {"label": "Strain", "depends_on": "species",
                                "by": {k: list(v) for k, v in VOCABULARIES["strain"].items()}}


def test_only_the_dependency_the_vocabulary_declares_is_served():
    served = vocabularies()["vocabularies"]
    assert {k: v["depends_on"] for k, v in served.items() if "depends_on" in v} == {"strain": "species"}
    # No invented rule: the vehicle and the means of administration are flat lists.
    for key in ("articleVehicle", "administrationMeans"):
        assert "values" in served[key] and "depends_on" not in served[key]


def test_every_vocabulary_has_a_label_from_the_bmdexpress_header_names():
    from ui_api.vocabularies import LABELS
    served = vocabularies()["vocabularies"]
    assert set(LABELS) == set(served)          # a new vocabulary needs its name added
    assert served["articleRoute"]["label"] == "Article Route"


def _matches(kind, value):
    return re.fullmatch(id_patterns()[kind]["pattern"], value) is not None


def test_a_person_names_a_study_by_its_bare_dtxsid():
    assert _matches("study_id", "DTXSID50469320")
    for system_made in ("DTXSID1020431_rat", "DTXSID50469320_published", "DTXSIDabc"):
        assert not _matches("study_id", system_made)
        assert _matches("session_id", system_made)


def test_the_session_id_pattern_is_the_backends_gate():
    from common.dtxsid import DTXSID_RE
    assert id_patterns()["session_id"]["pattern"] == DTXSID_RE.pattern


def test_casrn_and_doi():
    assert _matches("casrn", "41997-13-1") and _matches("casrn", "106-46-7")
    assert not _matches("casrn", "41997131") and not _matches("casrn", "4-13-1")
    assert _matches("doi", "10.22427/NIEHS-DATA-NIEHS-10")
    assert not _matches("doi", "https://doi.org/10.22427/NIEHS-DATA-NIEHS-10")
    assert not _matches("doi", "not-a-doi")


def test_every_pattern_has_an_example_it_accepts_and_words_for_a_person():
    for kind, p in id_patterns().items():
        assert re.fullmatch(p["pattern"], p["example"]), kind
        assert p["say"], kind


def test_the_payload_is_json_ready():
    import json
    payload = vocabularies_payload()
    assert set(payload) == {"vocabularies", "patterns"}
    json.dumps(payload)
