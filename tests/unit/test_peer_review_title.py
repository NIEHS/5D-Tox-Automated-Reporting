"""The peer-review paragraph names the report by its full book title, as the
published books do (NIEHS-02, 07, 10, 12), not by the short running title."""

from rendering.report_data import name_report_in_peer_review, scaffold_report_data


def test_peer_review_names_the_full_book_title():
    data = scaffold_report_data(chemical_name="Triclosan", casrn="3380-34-5",
                                dtxsid="DTXSID5032498")
    data["study_design"] = {"species": "rat", "strain": "Sprague-Dawley", "route": "gavage",
                            "duration_days": 5, "sexes": ["male"]}
    data["strain"] = "(Hsd:Sprague Dawley® SD®)"
    data["title"] = "In Vivo Repeat Dose Biological Potency Study of Triclosan in Rats"
    data["peer_review"]["paragraphs"] = [
        f"…; therefore, following internal review, the NIEHS Report on the {data['title']} "
        "was not subjected to further external peer review."]
    name_report_in_peer_review(data)
    name_report_in_peer_review(data)                      # idempotent
    assert data["peer_review"]["paragraphs"][0] == (
        "…; therefore, following internal review, the NIEHS Report on the In Vivo Repeat Dose "
        "Biological Potency Study of Triclosan (CASRN 3380-34-5) in Male Sprague Dawley "
        "(Hsd:Sprague Dawley® SD®) Rats (Gavage Studies) was not subjected to further "
        "external peer review.")
