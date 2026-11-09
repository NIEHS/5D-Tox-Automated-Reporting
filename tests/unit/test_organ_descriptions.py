"""The appendix "Organ Weight Descriptions" (rendering.organ_descriptions):
the organs the study weighed or sequenced, in the definition's words and order."""

from rendering.organ_descriptions import (
    DATA_KEY, attach_organ_descriptions, described_organs, organ_description_paragraphs,
    weighed_organs,
)

TEXTS = {"Brain": "B.", "Liver": "L.", "Kidney": "K.", "Heart": "H.", "Lung": "Lu.",
         "Ovary": "O."}


def _integrated(endpoints):
    return {"doseResponseExperiments": [
        {"experimentDescription": {"platform": "Organ Weight"},
         "probeResponses": [{"probe": {"id": e}} for e in ["Terminal Body Weight", *endpoints]]},
        {"experimentDescription": {"platform": "Body Weight"},
         "probeResponses": [{"probe": {"id": "SD0"}}]}]}


def _data(organs=()):
    return {"genomics_sections": [{"organ": o, "type": "gene"} for o in organs]}


def _described(endpoints, organs=()):
    return described_organs(weighed_organs(_integrated(endpoints)), _data(organs))


def _organs(paragraphs):
    return [p[0]["text"] for p in paragraphs]


def test_only_the_organs_the_study_weighed():
    """BPAF weighed the kidneys and liver, no heart: the heart is not described."""
    assert _described(["Kidney-Left", "Kidney-Right", "Liver"],
                      ["kidney", "liver"]) == ["Kidney", "Liver"]


def test_every_published_books_list():
    """NIEHS-02 … 06 Brain, Liver; NIEHS-07 … 10 Liver, Kidney, Heart (the
    2023 order); NIEHS-12, 13 the five tissues alphabetically, the ovary
    sequenced but not weighed."""
    order = ["Brain", "Liver", "Kidney", "Heart"]
    def listed(organs, order):
        return _organs(organ_description_paragraphs(organs, TEXTS, order))
    assert listed(_described(["Brain", "Liver"], ["liver"]), order) == ["Brain:", "Liver:"]
    # NIEHS-10's organ-weight table shows the liver only; the heart and kidneys
    # it weighed are described all the same.
    assert listed(_described(["Heart", "Kidney-Left", "Kidney-Right", "Liver"],
                             ["liver", "kidney"]), order) == ["Liver:", "Kidney:", "Heart:"]
    assert listed(_described(["Heart", "Kidney-Left", "Kidney-Right", "Liver", "Lungs"],
                             ["heart", "kidney", "liver", "lung", "ovary"]), []) == [
        "Heart:", "Kidney:", "Liver:", "Lung:", "Ovary:"]


def test_an_organ_with_no_description_is_a_placeholder():
    (para,) = organ_description_paragraphs(["Thymus"], TEXTS, [])
    assert para[1].startswith(" [Placeholder: the document definition has no description")


def test_nothing_without_descriptions_or_organs():
    data = _data()
    attach_organ_descriptions(data, [], TEXTS, [])
    assert DATA_KEY not in data
    attach_organ_descriptions(data, ["Liver"], {}, [])
    assert DATA_KEY not in data
    attach_organ_descriptions(data, ["Liver"], TEXTS, [])
    assert _organs(data[DATA_KEY]["paragraphs"]) == ["Liver:"]


def test_the_organ_table_points_to_the_appendix_by_its_letter():
    """Every book with the appendix prints "Descriptions of organ weight
    endpoints and changes are provided in Appendix E." as the organ table's
    note (a), on its first-column header; a definition without it, none."""
    from document_model.document_node import DocNode
    from rendering.report_data_overlays import _add_organ_descriptions_note
    from tables.table_builder_common import finalize_footnotes, lettered_footnote

    appendix = DocNode(id="appendix-e", title="Organ Weight Descriptions", node_type="appendix",
                       cited_as="organ-weight-descriptions")
    appendix.appendix_letter = "F"
    footnotes = [{"kind": "definition", "text": "BMD ..."},
                 lettered_footnote("Data are displayed as mean ± SE.", "data_format", target="header")]
    _add_organ_descriptions_note(footnotes, [appendix])
    _add_organ_descriptions_note(footnotes, [appendix])           # once
    finalize_footnotes(footnotes, {})
    assert [(f.get("letter"), f["text"]) for f in footnotes[1:]] == [
        ("a", "Descriptions of organ weight endpoints and changes are provided in Appendix F."),
        ("b", "Data are displayed as mean ± SE.")]
    assert footnotes[1]["marker"]["target"] == "header"

    plain = [lettered_footnote("x", "data_format", target="header")]
    _add_organ_descriptions_note(plain, [DocNode(id="appendix-e", title="Other", node_type="appendix")])
    assert len(plain) == 1
