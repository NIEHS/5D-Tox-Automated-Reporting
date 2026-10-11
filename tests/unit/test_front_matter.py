"""
Unit tests for rendering.front_matter — the human-set report front-matter overlay
(authors / contributors / publication overrides). The persisted-shape → render-shape
transform must produce the paragraph lists the front-matter resolver renders, so the
Authors and Contributors parts (ADR-0028) fill instead of showing "Narrative pending".
"""

from rendering.front_matter import (
    build_authors,
    build_contributors,
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
    lines = build_authors(fm)["paragraphs"]
    assert lines[0] == "Jane A. Smith, Study Scientist, NIEHS DTT"
    assert lines[1] == "Bob Jones, Statistician"  # empty affiliation omitted


def test_roster_order_is_author_order():
    fm = {"authors": [{"name": "First"}, {"name": "Second"}, {"name": "Third"}]}
    assert build_authors(fm)["paragraphs"] == ["First", "Second", "Third"]


def test_contributors_name_dash_role():
    fm = {"contributors": [
        {"name": "Sam Lee", "role": "Peer Reviewer"},
        {"name": "No Role"},
    ]}
    assert build_contributors(fm)["paragraphs"] == ["Sam Lee — Peer Reviewer", "No Role"]


def test_rosters_none_when_empty():
    for build in (build_authors, build_contributors):
        assert build({}) is None
        assert build({"authors": [], "contributors": []}) is None
        assert build(None) is None


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


def test_overlay_sets_authors_and_publication():
    data = {"authors": {"paragraphs": []}, "contributors": {"paragraphs": []},
            "publication_details": {"paragraphs": ["DOI: to be assigned upon publication"]}}
    fm = {"authors": [{"name": "A", "role": "Scientist"}],
          "publication": {"doi": "10.1/x"}}
    overlay_front_matter(data, fm)
    assert data["authors"] == {"paragraphs": ["A, Scientist"]}
    assert data["contributors"] == {"paragraphs": []}      # none supplied: untouched
    assert "DOI: 10.1/x" in data["publication_details"]["paragraphs"]
    # The structured roster rides along for the BITS projection.
    assert data["front_matter"]["authors"] == [
        {"name": "A", "affiliation": "", "contribution": "", "role": "Scientist"}]


def test_overlay_noop_when_empty():
    data = {"authors": {"x": 1}}
    overlay_front_matter(data, {})
    assert data == {"authors": {"x": 1}}  # untouched


# --- Front-matter workflow status (Sections screen) --------------------------


def test_status_rosters_pending_when_unauthored():
    # No front_matter.json + no processed abstract → Authors, Contributors and
    # Abstract are the only PENDING rows; boilerplate is always present.
    st = resolve_front_matter_status(None, abstract_filled=False)
    assert set(st) == set(FRONT_MATTER_STATUS_KEYS)
    assert st["authors"]["has_content"] is False
    assert st["contributors"]["has_content"] is False
    assert st["abstract"]["has_content"] is False
    for key in ("foreword", "peer_review", "publication_details", "acknowledgments"):
        assert st[key]["has_content"] is True, key


def test_status_authors_filled_when_authored():
    fm = {"authors": [{"name": "Jane A. Smith", "role": "Study Scientist"}]}
    st = resolve_front_matter_status(fm, abstract_filled=True)
    assert st["authors"]["has_content"] is True
    assert st["authors"]["paragraphs"] == 1
    assert st["contributors"]["has_content"] is False
    assert st["abstract"]["has_content"] is True


def test_strain_designation_reaches_the_title_data():
    from rendering.front_matter import clean_front_matter

    fm = clean_front_matter({"strain_designation": " (Hsd:Sprague Dawley® SD®) ",
                             "publication": {"doi": " ", "bogus": "x"}, "junk": 1})
    assert fm == {"authors": [], "contributors": [], "publication": {},
                  "strain_designation": "(Hsd:Sprague Dawley® SD®)"}
    data = {"strain": ""}
    overlay_front_matter(data, fm)
    assert data["strain"] == "(Hsd:Sprague Dawley® SD®)"


def test_a_roster_keeps_contribution_affiliation_and_collaborators():
    from rendering.front_matter import clean_front_matter
    fm = clean_front_matter({
        "contributors": [{"name": "B", "affiliation": "NIEHS", "contribution": "Reviewed"}],
        "collaborators": [{"name": "C", "affiliation": "Alion", "junk": 1}]})
    assert fm["contributors"] == [
        {"name": "B", "affiliation": "NIEHS", "contribution": "Reviewed", "role": ""}]
    assert fm["collaborators"] == [
        {"name": "C", "affiliation": "Alion", "contribution": "", "role": ""}]
    assert "collaborators" not in clean_front_matter({})
