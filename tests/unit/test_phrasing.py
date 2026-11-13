"""A definition's ``phrasing:`` block (document_model.phrasing, ADR-0029 §11):
the words of the prose the report writes from its data, checked against a
closed schema and inherited through ``extends``."""

import re

import pytest

from document_model.phrasing import Phrasing, PhrasingError, validate


def test_the_2026_era_s_phrasing_is_valid_and_inherited():
    from document_model.document_template import load_phrasing
    era = load_phrasing("eras/niehs-2026")
    assert era["gene_sets"]["none"].startswith("In {animals}, there were no active GO terms")
    assert load_phrasing("studies/DTXSID1020431/document") == era
    assert load_phrasing("eras/niehs-2023") == {}


@pytest.mark.parametrize("block, message", [
    ({"gene_sets": {"one": "was {term} at {dose}"}}, "field(s) ['dose'] are not the rule's"),
    ({"gene_sets": {"won": "x"}}, "unknown key(s) ['won']"),
    ({"words": {"direction": {"up": "upregulated"}}}, "missing ['down']"),
    ({"words": {"numbers": ["no", "one"]}}, "at least 11 entries"),
    ({"efdr": {"bound_pct": "one"}}, "expected a number"),
    ({"term": "{go_term!r}"}, "a field is a bare {name}"),
])
def test_a_mis_stated_phrasing_fails_at_load(block, message):
    with pytest.raises(PhrasingError, match=re.escape(message)):
        validate(block)


def test_a_study_rewords_one_sentence_by_stating_only_it(tmp_path, monkeypatch):
    from document_model import document_template
    from document_model.document_template import load_phrasing
    (tmp_path / "eras").mkdir()
    (tmp_path / "eras" / "base.yaml").write_text(
        "document: []\nphrasing:\n  term: '{go_term} ({go_id})'\n"
        "  gene: '*{symbol}* ({name})'\n", encoding="utf-8")
    (tmp_path / "study.yaml").write_text(
        "extends: eras/base\nphrasing:\n  term: '{go_term} [{go_id}]'\n", encoding="utf-8")
    monkeypatch.setattr(document_template, "TEMPLATES_DIR", tmp_path)
    p = Phrasing(load_phrasing("study"))
    assert p.say("term", go_term="cell cycle", go_id="GO:1") == "cell cycle [GO:1]"
    assert p.say("gene", symbol="Spp1", name="x") == "*Spp1* (x)"


def test_words():
    p = Phrasing({"words": {"numbers": ["no", "one", "two"], "all_of": {2: "both"},
                            "gene": ["gene", "genes"]}})
    assert (p.number(2), p.number(12)) == ("two", "12")
    assert (p.word("all_of", 2), p.has_word("all_of", 3)) == ("both", False)
    assert (p.noun("gene", 1), p.noun("gene", 3)) == ("gene", "genes")
    assert p.word("statistic", "median", default="median") == "median"
