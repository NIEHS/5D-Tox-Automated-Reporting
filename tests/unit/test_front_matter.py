"""
Unit tests for rendering.front_matter — the human-set report front-matter overlay
(authors / contributors / publication overrides). The persisted-shape → render-shape
transform must produce the LABELED `sections` form the front-matter resolver renders,
so the About This Report section fills instead of showing "Narrative pending".
"""

from rendering.front_matter import (
    build_about_report,
    apply_publication_overrides,
    overlay_front_matter,
    resolve_front_matter_status,
    FRONT_MATTER_STATUS_KEYS,
)


def test_authors_format_name_role_affiliation():
    fm = {"authors": [
        {"name": "Jane A. Smith", "role": "Study Scientist", "affiliation": "NIEHS DTT"},
        {"name": "Bob Jones", "role": "Statistician", "affiliation": ""},  # blank dropped
    ]}
    about = build_about_report(fm)
    labels = {s["label"]: s["text"] for s in about["sections"]}
    assert "Authors" in labels
    lines = labels["Authors"].split("\n")
    assert lines[0] == "Jane A. Smith, Study Scientist, NIEHS DTT"
    assert lines[1] == "Bob Jones, Statistician"  # empty affiliation omitted


def test_roster_order_is_author_order():
    fm = {"authors": [{"name": "First"}, {"name": "Second"}, {"name": "Third"}]}
    text = build_about_report(fm)["sections"][0]["text"]
    assert text.split("\n") == ["First", "Second", "Third"]


def test_contributors_name_dash_role():
    fm = {"contributors": [
        {"name": "Sam Lee", "role": "Peer Reviewer"},
        {"name": "No Role"},
    ]}
    about = build_about_report(fm)
    contrib = next(s for s in about["sections"] if s["label"] == "Contributors")
    assert contrib["text"].split("\n") == ["Sam Lee — Peer Reviewer", "No Role"]


def test_about_none_when_empty():
    assert build_about_report({}) is None
    assert build_about_report({"authors": [], "contributors": []}) is None
    assert build_about_report(None) is None


def test_publication_overrides_replace_scaffold_lines():
    scaffold = {"paragraphs": [
        "Publisher: NIEHS",
        "DOI: to be assigned upon publication",
        "Report Series Number: to be assigned upon publication",
    ]}
    fm = {"publication": {"report_number": "NIEHS-RR-14", "doi": "10.22427/RR-14"}}
    out = apply_publication_overrides(scaffold, fm)["paragraphs"]
    assert "DOI: 10.22427/RR-14" in out
    assert "Report Series Number: NIEHS-RR-14" in out
    assert "Publisher: NIEHS" in out           # untouched boilerplate stays
    assert "to be assigned" not in " ".join(out)


def test_publication_no_override_leaves_scaffold():
    scaffold = {"paragraphs": ["DOI: to be assigned upon publication"]}
    assert apply_publication_overrides(scaffold, {}) == scaffold


def test_overlay_sets_about_and_publication():
    data = {"about_report": {"authors": {"paragraphs": []}, "contributors": {"paragraphs": []}},
            "publication_details": {"paragraphs": ["DOI: to be assigned upon publication"]}}
    fm = {"authors": [{"name": "A", "role": "Scientist"}],
          "publication": {"doi": "10.1/x"}}
    overlay_front_matter(data, fm)
    # about_report replaced with the labeled shape the resolver renders
    assert data["about_report"]["sections"][0]["label"] == "Authors"
    assert "DOI: 10.1/x" in data["publication_details"]["paragraphs"]


def test_overlay_noop_when_empty():
    data = {"about_report": {"x": 1}}
    overlay_front_matter(data, {})
    assert data == {"about_report": {"x": 1}}  # untouched


# --- Front-matter workflow status (Sections screen) --------------------------


def test_status_about_pending_when_unauthored():
    # No front_matter.json + no processed abstract → About This Report and Abstract
    # are the only PENDING rows; boilerplate is always present.
    st = resolve_front_matter_status(None, abstract_filled=False)
    assert set(st) == set(FRONT_MATTER_STATUS_KEYS)
    assert st["about_report"]["has_content"] is False
    assert st["abstract"]["has_content"] is False
    for key in ("foreword", "peer_review", "publication_details", "acknowledgments"):
        assert st[key]["has_content"] is True, key


def test_status_about_filled_when_authored():
    fm = {"authors": [{"name": "Jane A. Smith", "role": "Study Scientist"}]}
    st = resolve_front_matter_status(fm, abstract_filled=True)
    assert st["about_report"]["has_content"] is True
    assert st["about_report"]["paragraphs"] >= 1
    assert st["abstract"]["has_content"] is True
