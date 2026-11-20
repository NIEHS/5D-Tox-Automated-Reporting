"""narrative/sources.py — source records, how text cites them, the entry a
list prints, and the boilerplate citations of the Materials and Methods
(ADR-0038)."""

import json

import pytest

from narrative.sources import (
    add_session_source, background_sources, cite_boilerplate, cited_slugs, format_entry,
    identity_of, load_library, load_session_sources, merge, missing_fields, paper_source,
    register, slug_for, token, tokens_for_numbers, tokens_for_pool,
)


def test_identity_is_the_doi_then_the_address_then_the_words():
    assert identity_of({"doi": "https://doi.org/10.1000/ABC", "url": "https://x"}) == "doi:10.1000/abc"
    assert identity_of({"url": "https://example.org/page/"}) == "url:https://example.org/page"
    assert identity_of({"text": "  Some   Report  "}) == "text:some report"


def test_two_records_of_one_identity_are_one_source():
    sources: dict = {}
    first = register(sources, {"kind": "paper", "doi": "10.1/x", "title": "T",
                               "origin": {"from": "knowledge_base"}})
    again = register(sources, {"kind": "paper", "doi": "DOI: 10.1/X", "authors": ["A B"],
                               "origin": {"from": "person"}})
    assert first == again == slug_for("doi:10.1/x") and len(sources) == 1
    # The later record fills what the earlier lacks; the earlier origin stays.
    assert sources[first]["authors"] == ["A B"]
    assert sources[first]["origin"] == {"from": "knowledge_base"}


def test_merge_says_which_slug_each_record_has_in_the_target():
    target: dict = {}
    mine = register(target, {"slug": "mine", "kind": "paper", "doi": "10.1/x", "title": "T"})
    theirs = {"other": {"slug": "other", "kind": "paper", "doi": "10.1/x", "title": "T"},
              "new": {"slug": "new", "kind": "website", "url": "https://n.example", "text": "N"}}
    assert merge(target, theirs) == {"other": mine, "new": "new"}
    assert set(target) == {"mine", "new"}


def test_a_numbered_citation_becomes_tokens_and_an_unknown_number_is_kept_as_unknown():
    sources, by_number = background_sources([
        "[1] PubChem Compound 7239 (database). https://pubchem.ncbi.nlm.nih.gov/compound/7239",
        "[2] ATSDR Toxicological Profile (government report). https://atsdr.example/p",
    ])
    assert len(sources) == 2 and sources[by_number[1]]["kind"] == "website"
    assert sources[by_number[1]]["text"] == "PubChem Compound 7239 (database)."
    text = tokens_for_numbers("It is a solvent [1, 2]. It is also cited [7].", by_number)
    assert text == (f"It is a solvent {token(by_number[1])}{token(by_number[2])}. "
                    f"It is also cited {token('unknown-7')}.")
    assert tokens_for_numbers("A range [1-2].", by_number) == \
        f"A range {token(by_number[1])}{token(by_number[2])}."


def test_a_pool_token_becomes_a_token_and_one_that_names_no_paper_is_dropped():
    assert tokens_for_pool("Induced in liver [P1, P9].", {"P1": "sa"}) == \
        f"Induced in liver {token('sa')}."
    assert tokens_for_pool("Nothing known [P9].", {"P1": "sa"}) == "Nothing known."
    assert cited_slugs(f"x {token('sa')} y {token('sb')} z {token('sa')}") == ["sa", "sb"]


def test_a_paper_of_a_knowledge_base_is_a_record_with_its_origin():
    record = paper_source({"paper_id": "p1", "title": "T ", "venue": "J", "year": 2020,
                           "doi": "10.1/X", "authors": ["A B", "C D"]}, "baseline-2026-05")
    assert record["origin"] == {"from": "knowledge_base", "knowledge_base": "baseline-2026-05",
                                "paper_id": "p1"}
    assert record["doi"] == "10.1/x" and record["url"] == "https://doi.org/10.1/x"
    assert missing_fields(record) == []
    assert missing_fields({**record, "authors": []}) == ["authors"]


def test_an_entry_prints_the_parts_the_record_has():
    assert format_entry({"kind": "paper", "authors": ["Williams DA"], "title": "A test",
                         "container": "Biometrics", "year": 1971, "volume": 27, "issue": 1,
                         "pages": "103–117", "doi": "10.2307/2528930"}) == \
        "Williams DA. A test. Biometrics. 1971; 27(1):103–117. https://doi.org/10.2307/2528930"
    many = format_entry({"authors": [f"A{i}" for i in range(8)], "title": "T", "year": 2000})
    assert many.startswith("A0, A1, A2, A3, A4, A5, et al. T. 2000.")
    assert format_entry({"kind": "website", "text": "PubChem Compound 7239 (database).",
                         "url": "https://p.example/7239"}) == \
        "PubChem Compound 7239 (database). https://p.example/7239"


def test_a_website_without_an_address_lacks_it():
    assert missing_fields({"kind": "website", "text": "A page"}) == ["address"]
    assert missing_fields({"kind": "website", "text": "A page", "url": "https://x"}) == []
    assert missing_fields({"kind": "paper", "title": "T"}) == [
        "authors", "container", "year", "DOI or address"]


def test_a_person_adds_a_source_to_a_study_once(tmp_path):
    slug = add_session_source(tmp_path, {"kind": "paper", "doi": "10.1/x", "title": "T"},
                              added_by="A. Person", added_at="2026-11-20T00:00:00Z")
    again = add_session_source(tmp_path, {"kind": "paper", "doi": "10.1/X", "title": "T"},
                               added_by="B. Person", added_at="2026-11-21T00:00:00Z")
    assert slug == again
    stored = load_session_sources(tmp_path)
    assert list(stored) == [slug]
    assert stored[slug]["origin"] == {"from": "person", "added_by": "A. Person",
                                      "added_at": "2026-11-20T00:00:00Z"}
    with pytest.raises(ValueError):
        add_session_source(tmp_path, {"kind": "rumor", "title": "T"}, added_by="x", added_at="y")


def test_the_library_is_read_as_records_keyed_by_what_text_cites(tmp_path):
    path = tmp_path / "sources.yaml"
    path.write_text(json.dumps({"sources": {"dunnett1955": {
        "authors": ["Dunnett CW"], "title": "T", "container": "J", "year": 1955,
        "doi": "10.1080/01621459.1955.10501294"}}}), encoding="utf-8")
    library = load_library(path)
    record = library["dunnett1955"]
    assert record["slug"] == "dunnett1955" and record["kind"] == "paper"
    assert record["origin"] == {"from": "library", "key": "dunnett1955"}
    assert record["url"] == "https://doi.org/10.1080/01621459.1955.10501294"
    path.write_text(json.dumps({"sources": {"Bad Key": {}}}), encoding="utf-8")
    import os
    os.utime(path, (1, 1))
    with pytest.raises(ValueError):
        load_library(path)


def test_the_shipped_library_is_complete():
    library = load_library()
    assert {"williams1971", "williams1972", "dunnett1955", "shirley1977", "dunn1964",
            "jonckheere1954", "yang2007"} <= set(library)
    for key, record in library.items():
        assert missing_fields(record) == [], key
        assert record.get("doi"), key


_LIBRARY = {
    "williams1971": {"cited_at": [{"methods": "stat_analysis", "after": "Williams"}]},
    "williams1972": {"cited_at": [{"methods": "stat_analysis", "after": "Williams"}]},
    "dunnett1955": {"cited_at": [{"methods": "stat_analysis", "after": "Dunnett"}]},
    "jonckheere1954": {"cited_at": [{"methods": "stat_analysis",
                                    "after": ["Jonckheere test", "Jonckheere"]}]},
}


def test_boilerplate_is_cited_at_the_first_mention_by_rule():
    paragraphs = ["Organ weights used the procedures of Williams and Dunnett.",
                  "The Jonckheere test selected Williams or Dunnett."]
    cited = cite_boilerplate("stat_analysis", paragraphs, _LIBRARY)
    assert cited == [
        "Organ weights used the procedures of Williams [[cite:williams1971]][[cite:williams1972]]"
        " and Dunnett [[cite:dunnett1955]].",
        "The Jonckheere test [[cite:jonckheere1954]] selected Williams or Dunnett."]
    # The rule runs again over its own result and changes nothing.
    assert cite_boilerplate("stat_analysis", cited, _LIBRARY) == cited
    # Another subsection, and a subsection that does not use the words, cite nothing.
    assert cite_boilerplate("study_design", paragraphs, _LIBRARY) == paragraphs
    assert cite_boilerplate("stat_analysis", ["Means were compared."], _LIBRARY) == \
        ["Means were compared."]


def test_boilerplate_words_are_whole_words_and_alternatives_fall_back():
    assert cite_boilerplate("stat_analysis", ["Williamson wrote it."], _LIBRARY) == \
        ["Williamson wrote it."]
    assert cite_boilerplate("stat_analysis", ["Trend by Jonckheere."], _LIBRARY) == \
        ["Trend by Jonckheere [[cite:jonckheere1954]]."]
