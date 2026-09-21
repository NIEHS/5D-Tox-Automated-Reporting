"""
Citation verification for the two literature-grounded narratives.

Background: the model gets a numbered inventory (sources, then papers) and must
cite only those numbers. Genomics: the model gets a [Pn] catalogue and must
cite only those tokens. Before 2026-09-21 the Background path accepted any
reference line the model wrote and the genomics path silently deleted any
unknown [Pn]. These tests pin the new behavior: the reference list is rebuilt
from OUR inventory, and every citation that does not resolve is recorded and
surfaced (never trusted, never silently dropped).
"""

import json


import narrative.background_writer as bw
from narrative.citation_check import (
    find_unresolved_tokens,
    sentence_containing,
    summarize_issues,
)
from narrative.chem_resolver import ChemicalIdentity
from narrative.data_gatherer import BackgroundData
from narrative.references_builder import (
    _BRACKET_RE,
    _TOKEN_RE,
    build_session_references,
    find_unresolved_citations,
)


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------

def test_sentence_containing_picks_the_right_sentence():
    text = "First claim [P1]. Second claim [P9]. Third."
    assert sentence_containing(text, "[P9]") == "Second claim [P9]."
    assert sentence_containing(text, "[P7]") == text  # not found → whole text
    assert sentence_containing("", "[P1]") == ""


def test_find_unresolved_tokens_reports_only_unknown_tokens_with_sentences():
    paras = ["Ok [P1]. Bad [P9] here.", "Combined [P1, P8].", 42]
    issues = find_unresolved_tokens(paras, {"P1"}, _BRACKET_RE, _TOKEN_RE, "liver/male")
    assert [(i["token"], i["sentence"]) for i in issues] == [
        ("[P9]", "Bad [P9] here."),
        ("[P8]", "Combined [P1, P8]."),
    ]
    assert all(i["issue"] == "unresolved_citation" and i["where"] == "liver/male" for i in issues)
    assert summarize_issues(issues).startswith("2 unresolved citation(s)")
    assert summarize_issues([]) == ""


# ---------------------------------------------------------------------------
# Background
# ---------------------------------------------------------------------------

def _bg_data() -> BackgroundData:
    d = BackgroundData(identity=ChemicalIdentity(name="Testol"))
    d.references = [
        {"title": "ATSDR Toxicological Profile for Testol", "url": "https://atsdr.cdc.gov/tp/testol", "source_type": "government_report"},
        {"title": "EPA IRIS Assessment for Testol", "url": "https://iris.epa.gov/testol", "source_type": "government_report"},
    ]
    d.mechanism_papers = [
        {"authors": ["Smith J", "Lee K"], "year": 2019, "title": "Hepatic PPAR-alpha activation by Testol", "venue": "Tox Sci"},
    ]
    return d


def test_inventory_numbers_sources_then_papers_and_prompt_agrees():
    data = _bg_data()
    inv = bw.build_citation_inventory(data)
    assert [e["n"] for e in inv] == [1, 2, 3]
    assert inv[2]["kind"] == "paper" and "Smith J" in inv[2]["authors"]
    prompt = bw.build_prompt(data)
    # Papers are numbered in the prompt, continuing after the sources.
    assert "[3] Smith J, Lee K (2019). Hepatic PPAR-alpha activation by Testol. Tox Sci." in prompt
    assert "never cite a source that is not listed above" in prompt


def test_verify_all_citations_resolve_and_list_is_canonical():
    inv = bw.build_citation_inventory(_bg_data())
    paras = ["Testol is used widely [1]. It activates PPAR-alpha [3].", "Cancer class D [2-3]."]
    lines = [
        "[1] ATSDR. \"Toxicological Profile for Testol.\" https://atsdr.cdc.gov/tp/testol. 2018.",
        "[2] EPA IRIS Assessment for Testol. https://iris.epa.gov/testol",
        "[3] Smith J, Lee K. Hepatic PPAR-alpha activation by Testol. Tox Sci 2019.",
    ]
    refs, report = bw.verify_background_citations(paras, lines, inv)
    assert report["issues"] == [] and report["unresolved_count"] == 0
    assert report["cited"] == [1, 3, 2]          # first-appearance order, range expanded
    # The References list is rebuilt from OUR inventory, not the model's lines.
    assert refs == [
        "[1] ATSDR Toxicological Profile for Testol (government report). https://atsdr.cdc.gov/tp/testol",
        "[2] EPA IRIS Assessment for Testol (government report). https://iris.epa.gov/testol",
        "[3] Smith J, Lee K (2019). Hepatic PPAR-alpha activation by Testol. Tox Sci.",
    ]


def test_verify_flags_invented_inline_invented_line_and_renumbering():
    inv = bw.build_citation_inventory(_bg_data())
    paras = ["Known effect [1]. Invented support [7]."]
    lines = [
        "[1] ATSDR Toxicological Profile for Testol. https://atsdr.cdc.gov/tp/testol",
        "[2] Jones et al. Completely different paper on kidney. J Nephrol 2001.",  # renumbered
        "[7] Made-up Author. A paper that does not exist. 2020.",                  # invented
        "Doe A. Unnumbered line.",                                                # no number
    ]
    refs, report = bw.verify_background_citations(paras, lines, inv)
    kinds = [(i["issue"], i["token"]) for i in report["issues"]]
    assert ("unresolved_citation", "[7]") in kinds
    assert ("reference_line_mismatch", "[2]") in kinds
    assert ("unresolved_reference_line", "[7]") in kinds
    assert ("unresolved_reference_line", "[?]") in kinds
    inline = next(i for i in report["issues"] if i["issue"] == "unresolved_citation")
    assert inline["sentence"] == "Invented support [7]."
    # Prose is untouched; invented sources never reach the list; [2] keeps OUR text.
    assert paras == ["Known effect [1]. Invented support [7]."]
    assert [r[:3] for r in refs] == ["[1]", "[2]"]
    assert "Jones" not in " ".join(refs)


def test_generate_background_reconciles_and_reports(monkeypatch):
    """End to end through generate_background with the LLM stubbed: the reply
    cites an inventory number, an invented number, and lists a garbled line."""
    canned = (
        "Para one [1].\n\nPara two cites nothing real [9].\n\n"
        "References\n[1] ATSDR profile https://atsdr.cdc.gov/tp/testol\n[9] Fake ref.\n"
    )
    monkeypatch.setattr(bw.AnthropicEndpoint, "generate", lambda self, prompt, system=None: canned)
    monkeypatch.setattr(bw, "distill_abstract_background", lambda **kw: "")
    out = bw.generate_background(_bg_data())
    assert out["paragraphs"] == ["Para one [1].", "Para two cites nothing real [9]."]
    assert out["references"] == [
        "[1] ATSDR Toxicological Profile for Testol (government report). https://atsdr.cdc.gov/tp/testol",
    ]
    issues = out["citation_report"]["issues"]
    assert {i["token"] for i in issues} == {"[9]"}
    assert {i["issue"] for i in issues} == {"unresolved_citation", "unresolved_reference_line"}


# ---------------------------------------------------------------------------
# Genomics
# ---------------------------------------------------------------------------

def _stratum(gs, gn):
    return {
        "organ": "liver", "sex": "male",
        "reference_pool": [
            {"token": "P1", "paper_id": "pa", "title": "A", "year": 2020,
             "venue": "V", "doi": "10.1/a", "citation_count": 1, "genes": []},
        ],
        "gene_set_narrative": gs, "gene_narrative": gn,
    }


def test_find_unresolved_citations_reports_per_kind_with_sentences():
    w = find_unresolved_citations([_stratum(["Valid [P1]. Invented [P9] token."], ["Gene claim [P4]."])])
    assert [(x["kind"], x["tokens"], x["sentences"]) for x in w] == [
        ("gene_set", ["P9"], ["Invented [P9] token."]),
        ("gene", ["P4"], ["Gene claim [P4]."]),
    ]
    assert all(x["issue"] == "unresolved_citation" and x["organ"] == "liver" for x in w)
    assert find_unresolved_citations([_stratum(["Only [P1]."], [])]) == []


def test_build_session_references_surfaces_unresolved_in_warnings(tmp_path):
    """The session-level assembly: the invented token is still dropped from the
    rewritten prose (no raw [P9] ships) but now appears in `warnings`."""
    from genomics.genomics_narratives import interpretation_cache_prefix
    prefix = interpretation_cache_prefix("liver", "male")
    (tmp_path / f"{prefix}abc.json").write_text(json.dumps(_stratum(
        ["Valid [P1] but invented [P9]."], [])))
    out = build_session_references(tmp_path, {"liver_male": {}}, dtxsid="DTXSID_T")
    assert out["rewritten"][("liver", "male")]["gene_set_narrative"] == ["Valid [1] but invented."]
    assert [w["tokens"] for w in out["warnings"]] == [["P9"]]
    assert out["warnings"][0]["sentences"] == ["Valid [P1] but invented [P9]."]


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

def test_citation_warnings_route_merges_both_sources(client, sessions_dir):
    d = sessions_dir / "DTXSID_CW"
    d.mkdir()
    (d / "background.json").write_text(json.dumps({
        "paragraphs": ["p"], "references": [],
        "citation_report": {"issues": [
            {"where": "background", "token": "[9]", "issue": "unresolved_citation", "sentence": "x [9]."},
        ]},
    }))
    (d / "references.json").write_text(json.dumps({
        "references": [], "paragraphs": [],
        "warnings": [{"kind": "gene_set", "organ": "liver", "sex": "male",
                      "issue": "unresolved_citation", "tokens": ["P9"], "sentences": ["s"]}],
    }))
    resp = client.get("/api/session/DTXSID_CW/citation-warnings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert body["background"][0]["token"] == "[9]"
    assert body["genomics"][0]["tokens"] == ["P9"]


def test_citation_warnings_route_empty_when_nothing_persisted(client, sessions_dir):
    (sessions_dir / "DTXSID_NONE").mkdir()
    resp = client.get("/api/session/DTXSID_NONE/citation-warnings")
    assert resp.status_code == 200 and resp.json() == {"count": 0, "background": [], "genomics": []}
