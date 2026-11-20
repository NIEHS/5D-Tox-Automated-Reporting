"""rendering/citations_validate.py — the citation check and its record
(ADR-0038)."""

import json

import pytest

from narrative.sources import token
from rendering import citations_validate as cv
from rendering.report_data import scaffold_report_data

A = {"slug": "a", "identity": "doi:10.1/a", "kind": "paper", "authors": ["Able B"],
     "title": "Alpha", "container": "J", "year": 2001, "doi": "10.1/a",
     "origin": {"from": "person"}}
B = {"slug": "b", "identity": "url:https://b.example", "kind": "website",
     "text": "Beta site.", "url": "https://b.example", "origin": {"from": "background"}}
K = {"slug": "k", "identity": "doi:10.1/k", "kind": "paper", "authors": ["Kay L"],
     "title": "Kappa", "container": "J", "year": 2010, "doi": "10.1/k",
     "origin": {"from": "knowledge_base", "knowledge_base": "kb"}}


def _report(background, sources=(A, B, K)):
    data = scaffold_report_data()
    data["background"] = {"paragraphs": list(background)}
    data["sources"] = {s["slug"]: dict(s) for s in sources}
    return data


def _examine(data, doi=None, url=None, known=None):
    return cv.examine(
        data,
        doi_state=lambda d: (doi or {}).get(d, "registered"),
        url_state=lambda u: (url or {}).get(u, "answers"),
        known_doi_state=lambda d: (known or {}).get(d, "registered"))


def _codes(result, severity=None):
    return [f["code"] for f in result["findings"] if severity in (None, f["severity"])]


def test_a_clean_report_passes_and_lists_what_it_cites():
    result = _examine(_report([f"First {token('b')}. Then {token('a')}{token('b')}."]))
    assert result["passed"] and result["tracked"]
    assert result["counts"] == {"citations": 2, "cited_sources": 2, "listed": 2,
                                "recorded_sources": 3, "errors": 0, "warnings": 0, "notes": 1}
    assert [(r["number"], r["slug"], r["cited"]) for r in result["references"]] == [
        (1, "b", 2), (2, "a", 1)]
    assert result["references"][0]["address_state"] == "answers"
    assert result["references"][0]["sentences"] == ["First.", "Then."]
    assert result["references"][1]["entry"] == "Able B. Alpha. J. 2001. https://doi.org/10.1/a"
    assert result["not_listed"] == [{
        "slug": "k", "kind": "paper", "origin": "knowledge_base", "knowledge_base": "kb",
        "entry": "Kay L. Kappa. J. 2010. https://doi.org/10.1/k", "title": "Kappa",
        "container": "J", "year": 2010, "doi": "10.1/k", "reason": "not_cited"}]
    assert result["references"][1]["doi_state"] == "registered"
    # The paper nothing cites is said, as a note: it is not listed.
    assert _codes(result) == ["recorded_not_cited"]
    assert result["not_judged"]


def test_a_citation_of_no_source_is_an_error_with_its_sentence():
    result = _examine(_report([f"Liver weight rose {token('unknown-9')}. Fine {token('a')}."]))
    assert not result["passed"]
    finding = next(f for f in result["findings"] if f["code"] == "no_source")
    assert finding["severity"] == "error" and "number 9" in finding["message"]
    assert finding["sentences"] == ["Liver weight rose."]


def test_a_typed_number_is_an_error_and_a_chemical_name_is_not_a_citation():
    result = _examine(_report([
        f"Tracked {token('a')}. Typed by hand [7]. In dibenzo[b,e][1,4]dioxin nothing is cited."]))
    typed = [f for f in result["findings"] if f["code"] == "typed_number"]
    assert len(typed) == 1 and typed[0]["severity"] == "error"
    assert "[7]" in typed[0]["message"] and "[1,4]" not in typed[0]["message"]


def test_an_incomplete_entry_is_an_error():
    result = _examine(_report([f"Cited {token('a')}."], sources=({**A, "authors": []},)))
    finding = next(f for f in result["findings"] if f["code"] == "entry_incomplete")
    assert finding["severity"] == "error" and "authors" in finding["message"]
    assert result["references"][0]["missing"] == ["authors"]


def test_an_unregistered_doi_is_an_error_and_an_unasked_one_a_warning():
    data = _report([f"Cited {token('a')}."])
    bad = _examine(data, doi={"10.1/a": "not_registered"})
    assert _codes(bad, "error") == ["doi_not_registered"] and not bad["passed"]
    unasked = _examine(data, doi={"10.1/a": "not_checked"})
    assert _codes(unasked, "warning") == ["doi_not_checked"] and unasked["passed"]


def test_a_knowledge_base_paper_is_answered_from_what_is_on_file_only():
    asked = []
    result = cv.examine(
        _report([f"Cited {token('k')}."]),
        doi_state=lambda d: asked.append(d) or "registered",
        url_state=lambda u: "answers",
        known_doi_state=lambda d: "not_checked")
    assert asked == []                       # the DOI system is not asked per study
    finding = next(f for f in result["findings"] if f["code"] == "doi_not_checked")
    assert "knowledge base as a whole" in finding["message"]


def test_an_address_that_is_gone_is_an_error_and_one_out_of_reach_a_warning():
    data = _report([f"Cited {token('b')}."])
    assert _codes(_examine(data, url={"https://b.example": "not_found"}), "error") == \
        ["address_not_found"]
    out_of_reach = _examine(data, url={"https://b.example": "not_reached"})
    assert _codes(out_of_reach, "warning") == ["address_not_checked"] and out_of_reach["passed"]
    assert _codes(_examine(data, url={"https://b.example": "refuses"}), "note")[0] == \
        "address_refuses"


def test_a_source_cited_only_by_text_the_report_does_not_print_is_told_apart():
    data = _report([f"Printed {token('a')}."])
    data["an_unprinted_interpretation"] = f"Not printed {token('k')}."
    result = _examine(data)
    notes = {f["code"]: f for f in result["findings"] if f["severity"] == "note"}
    assert notes["cited_by_unprinted_text"]["slugs"] == ["k"]
    assert {n["slug"]: n["reason"] for n in result["not_listed"]} == {
        "b": "not_cited", "k": "unprinted_text"}
    assert "papers of the knowledge base, 1" in notes["cited_by_unprinted_text"]["message"]
    assert notes["recorded_not_cited"]["slugs"] == ["b"]


def test_what_a_writer_cited_outside_its_sources_is_a_warning():
    data = _report([f"Printed {token('a')}."])
    data["citation_warnings"] = [
        {"where": "Background", "token": "[12]", "issue": "unresolved_citation",
         "sentence": "It is toxic."},
        {"kind": "gene", "organ": "liver", "sex": "female", "issue": "unresolved_citation",
         "tokens": ["P9"], "sentences": ["Cyp1a1 rose."], "study": "rat"}]
    found = [f for f in _examine(data)["findings"] if f["code"] == "writer_citation_dropped"]
    assert [f["severity"] for f in found] == ["warning", "warning"]
    assert "[12]" in found[0]["message"] and "(Background)" in found[0]["message"]
    assert "[P9]" in found[1]["message"] and "(rat, liver, female, genes)" in found[1]["message"]
    assert found[1]["sentences"] == ["Cyp1a1 rose."]


def test_without_the_network_every_outside_check_is_reported_as_not_made():
    result = cv.examine(_report([f"First {token('b')}. Then {token('a')}."]))
    assert sorted(_codes(result, "warning")) == ["address_not_checked", "doi_not_checked"]
    assert result["passed"]


def _as_given(body, references):
    data = scaffold_report_data()
    data["background"] = {"paragraphs": list(body)}
    data["references"] = {"paragraphs": list(references)}
    return data


def test_a_report_numbered_as_given_is_compared_as_printed():
    result = cv.examine(_as_given(
        ["It is a solvent [1]. It is toxic [2, 9]."],
        ["[1] One. https://one.example", "[2] Two. https://doi.org/10.1/two",
         "[3] Three, cited nowhere.", "[4] Two again. https://doi.org/10.1/TWO"]))
    assert not result["tracked"] and not result["passed"]
    errors = {f["code"]: f["message"] for f in result["findings"] if f["severity"] == "error"}
    assert "9" in errors["number_without_entry"]
    assert "3–4" in errors["entry_not_cited"] and "The list has 4; the text cites 2." in \
        errors["entry_not_cited"]
    assert "[2] and [4]" in errors["listed_twice"]
    assert "not_tracked" in _codes(result, "note")


def test_a_list_whose_text_cites_in_another_way_is_not_compared():
    # A book as given: its entries may be inline content (text and links).
    result = cv.examine(_as_given(["It is a solvent (Smith 2001)."], [
        "Smith. 2001. A book.",
        ["[2] NISO. CRediT. ", {"type": "ext-link", "text": "https://credit.niso.org/",
                                "href": "https://credit.niso.org/"}]]))
    assert result["passed"] and result["counts"]["cited_sources"] == 2
    assert result["references"][1]["entry"] == "NISO. CRediT. https://credit.niso.org/"
    assert _codes(result, "warning") == ["citations_not_recognized"]


# ── the act, its record, and where the check stands ───────────────────────

ID = "DTXSID7000001"


@pytest.fixture
def store(tmp_path, monkeypatch):
    import common.paths
    import pipeline.session_store
    monkeypatch.setattr(common.paths, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(pipeline.session_store, "SESSIONS_DIR", tmp_path)
    (tmp_path / ID).mkdir()
    return tmp_path


def test_the_check_is_recorded_and_holds_until_the_report_changes(store):
    assert cv.status(ID) == {"state": "not_checked"}
    data = _report([f"First {token('b')}. Then {token('a')}."])
    record = cv.validate(ID, network=False, checked_by="A. Person", inputs=(data, None))
    kept = json.loads((store / ID / cv.RECORD_FILE).read_text())
    assert kept == record and kept["checked_by"] == "A. Person" and kept["network"] is False
    assert kept["passed"] and kept["content_fingerprint"] and kept["print_fingerprint"]
    assert cv.status(ID)["state"] == "passed"
    # The record itself is not part of the report: writing it changed nothing.
    assert cv.status(ID)["counts"]["cited_sources"] == 2
    # Anything written to the study after the check shows it out of date.
    (store / ID / "background.json").write_text("{}")
    assert cv.status(ID)["state"] == "out_of_date"


def test_a_check_that_found_errors_stands_as_failed(store):
    data = _report([f"Typed by hand [7]. Tracked {token('a')}."])
    record = cv.validate(ID, network=False, inputs=(data, None))
    assert not record["passed"]
    assert cv.status(ID)["state"] == "failed"
    assert cv.status(ID, None) == {"state": "not_checked"}


def test_a_check_not_saved_leaves_no_record(store):
    cv.validate(ID, network=False, save=False, inputs=(_report([f"x {token('a')}."]), None))
    assert not (store / ID / cv.RECORD_FILE).exists()
