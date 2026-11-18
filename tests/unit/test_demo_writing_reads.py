"""ui_api.writing and ui_api.writing_references: the written parts of a
report, who wrote each, what the model was given, and the reference list (the
demo path, spec §4 S3 and S4).

Small fake sessions in a scratch SESSIONS_DIR: a report over one study, with
a Background, and the study with its Process results. No model and no network:
the knowledge base is a small database made here.
"""

import json
import os
import re

import pytest

REPORT = "DTXSID0000555"
STUDY = f"{REPORT}_rat"
PAPER_A, PAPER_B = "a" * 40, "b" * 40


def _write(folder, name, content="{}", mtime=None):
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content))
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def _pool():
    return [{"token": "P1", "paper_id": PAPER_A, "title": "Nrf2 in the liver", "year": 2021,
             "venue": "Tox Sci", "doi": "10.1000/a", "citation_count": 12, "genes": ["NFE2L2"]},
            {"token": "P2", "paper_id": PAPER_B, "title": "Heme oxygenase", "year": 2019,
             "venue": "Redox", "doi": "10.1000/b", "citation_count": 3, "genes": ["HMOX1"]}]


@pytest.fixture
def store(sessions_dir):
    report = sessions_dir / REPORT
    _write(report, "studies.json", {"rat": STUDY})
    _write(report, "identity.json", {"name": "Testane", "casrn": "50-00-0"})
    _write(report, "background.json", {
        "paragraphs": ["Testane is a solvent [1]. It is a liver toxicant [1, 2].",
                       "Its limit is 5 ppm [7]."],
        "references": ["[1] PubChem Compound 1 (database). https://pubchem.example/1",
                       "[2] ATSDR Profile for Testane (government report). https://atsdr.example/t"],
        "citation_report": {"inventory_size": 2, "cited": [1, 2], "unresolved_count": 1,
                            "issues": [{"where": "background", "token": "[7]",
                                        "issue": "unresolved_citation",
                                        "sentence": "Its limit is 5 ppm [7]."}]},
        "abstract_background": "Testane is a solvent.", "model_used": "model-x",
        "approved": False, "version": 1})

    study = sessions_dir / STUDY
    _write(study, "identity.json", {"name": "Testane", "casrn": "50-00-0", "abbreviation": "TST"})
    _write(study, "_cache_methods_h1.json", {
        "sections": [
            {"key": "study_design", "heading": "Study Design", "level": 2, "paragraphs": ["Built."]},
            {"key": "clinical_obs", "heading": "Clinical Observations", "level": 2,
             "paragraphs": ["Worded."]}],
        "context": {"chemical_name": "Testane", "species": "rat", "dose_unit": "ppm"},
        "model_used": "model-m"})
    _write(study, "_cache_apical_narrative_h1.json",
           {"paragraphs": ["The liver was the target."], "model_used": "model-a"})
    _write(study, "bm2_body-weight.json", {
        "title": "Body Weight", "caption": "Body weights", "narrative": ["Weights fell."],
        "approved": False, "source": "generated", "version": 1})
    _write(study, "summary.json", {"paragraphs": ["Facts by rule."], "source": "generated",
                                   "approved": False, "version": 1})
    _write(study, "_cache_genomics_h1.json", {"liver_male": {}})
    # An older interpretation of the same organ and sex: the newer one is current.
    _write(study, "_cache_interpretation_liver_male_zzz.json", {
        "context_text": "OLD", "reference_pool": _pool(), "gene_set_narrative": ["Old text."],
        "gene_narrative": [], "model_used": "model-old"}, mtime=1_000_000_000)
    _write(study, "_cache_interpretation_liver_male_aaa.json", {
        "context_text": "=== DOSE-RESPONSE SUMMARY ===\n12 responsive genes",
        "reference_pool": _pool(),
        "knowledge_base": {"name": "kb-test", "sha256": "f" * 64},
        "gene_set_narrative": ["Nrf2 was activated [P1]. Oxidative stress followed [P1, P2]. "
                               "An invented claim [P9]."],
        "gene_narrative": ["HMOX1 rose [P2]."],
        "model_used": "model-g",
        "unresolved_citations": [{"kind": "gene_set", "organ": "liver", "sex": "male",
                                  "issue": "unresolved_citation", "tokens": ["P9"],
                                  "sentences": ["An invented claim [P9]."]}]},
        mtime=2_000_000_000)
    _write(study, "knowledge_base.json", {"name": "kb-test", "sha256": "f" * 64})
    return sessions_dir


@pytest.fixture
def kb(tmp_path, monkeypatch):
    """A knowledge base with the statements extracted from one of the papers."""
    import duckdb
    from knowledge_base import registry

    path = tmp_path / "kb.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE paper_claims (paper_id VARCHAR, claim VARCHAR)")
    con.execute("INSERT INTO paper_claims VALUES (?, ?), (?, ?)",
                [PAPER_A, "Nrf2 protects the liver.", PAPER_A, "Nrf2 induces NQO1."])
    con.close()
    monkeypatch.setattr(registry, "kb_or_none", lambda dtxsid, needs=None: {
        "name": "kb-test", "path": path, "sha256": "f" * 64})
    return path


def _snapshot(root):
    return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*"))}


# ---------------------------------------------------------------------------
# The overview
# ---------------------------------------------------------------------------

def test_a_report_lists_its_background_and_each_studys_parts(store):
    from ui_api.writing import writing_overview

    before = _snapshot(store)
    out = writing_overview(REPORT)
    assert _snapshot(store) == before                       # reading changes nothing

    assert out["kind"] == "report"
    assert [(p["key"], p["written_by"], p["model"]) for p in out["parts"]] == [
        ("background", "model", "model-x")]
    [study] = out["studies"]
    assert (study["key"], study["id"], study["exists"]) == ("rat", STUDY, True)
    assert [(p["key"], p["written_by"]) for p in study["parts"]] == [
        ("methods", "mixed"), ("results", "data"), ("bmd_summary", "model"),
        ("genomics_liver_male", "model"), ("summary", "data")]
    methods = study["parts"][0]
    assert [(s["key"], s["written_by"]) for s in methods["subsections"]] == [
        ("study_design", "data"), ("clinical_obs", "model")]
    assert [g["title"] for g in out["api_page"]] == [
        "Written sections and their prompts", "Citations and the literature behind them"]
    assert all(g["href"].startswith("/docs#/") for g in out["api_page"])
    assert out["check_says"].startswith("The check establishes that a citation points at a source.")


def test_what_is_recorded_is_flagged_per_part(store):
    from ui_api.writing import writing_overview

    out = writing_overview(REPORT)
    parts = {p["key"]: p for p in out["studies"][0]["parts"]}
    assert out["parts"][0]["recorded"]["prompt"] == "not_recorded"       # no run kept
    assert parts["methods"]["recorded"] == {
        "prompt": "rebuilt", "inputs": "recorded", "say": parts["methods"]["recorded"]["say"]}
    assert parts["bmd_summary"]["recorded"]["prompt"] == "not_recorded"
    assert parts["bmd_summary"]["recorded"]["inputs"] == "not_recorded"
    assert parts["genomics_liver_male"]["recorded"]["inputs"] == "recorded"
    assert parts["results"]["recorded"] is None and parts["summary"]["recorded"] is None


def test_a_study_of_a_report_points_at_the_report_for_the_background(store):
    from ui_api.writing import writing_overview

    out = writing_overview(STUDY)
    assert out["kind"] == "member"
    assert "background" not in [p["key"] for p in out["parts"]]
    assert out["report"] == {"id": REPORT, "part": {"key": "background", "title": "Background"}}


def test_acts_are_offered_on_the_live_copy_only(store):
    from ui_api.writing import writing_overview

    acts = writing_overview(REPORT)["acts"]
    assert acts["background"]["allowed"] is False and acts["summary"]["allowed"] is False
    assert "live copy" in acts["background"]["say"]


# ---------------------------------------------------------------------------
# One part
# ---------------------------------------------------------------------------

def test_a_background_with_no_recorded_run_says_not_recorded(store):
    from ui_api.writing import writing_part

    part = writing_part(REPORT, "background")
    [prompt] = part["given"]
    assert (prompt["record"], prompt["text"]) == ("not_recorded", None)
    assert part["text"][0]["paragraphs"][0].startswith("Testane is a solvent")
    assert part["citation_check"]["untraced"] == 1 and part["citation_check"]["removed"] is False
    assert part["citation_check"]["items"][0]["token"] == "[7]"


def test_a_background_written_by_a_recorded_run_shows_the_prompt_as_sent(store):
    from ui_api.writing import writing_overview, writing_part

    section = json.loads((store / REPORT / "background.json").read_text())
    _write(store / REPORT, "narrative_runs/background/r20261118T120000-abc123.json", {
        "run_id": "r20261118T120000-abc123", "at": "2026-11-18T12:00:00Z",
        "prompt": {"system": "Be exact.", "user": "Write about Testane."},
        "paragraphs": section["paragraphs"], "section_version": 1})
    part = writing_part(REPORT, "background")
    [prompt] = part["given"]
    assert prompt["record"] == "as_sent"
    assert "Be exact." in prompt["text"] and "Write about Testane." in prompt["text"]
    assert part["run"]["run_id"] == "r20261118T120000-abc123"
    assert writing_overview(REPORT)["parts"][0]["recorded"]["prompt"] == "as_sent"
    # A run whose text is not the section's text is not its record.
    section["paragraphs"] = ["Edited since."]
    _write(store / REPORT, "background.json", section)
    assert writing_part(REPORT, "background")["given"][0]["record"] == "not_recorded"


def test_methods_show_the_facts_as_recorded_and_the_prompt_as_rebuilt(store, monkeypatch):
    import narrative.methods_prompt as methods_prompt
    from ui_api.writing import writing_part

    monkeypatch.setattr(methods_prompt, "build_methods_prompt", lambda ctx: ("SYS", f"USER {ctx.species}"))
    part = writing_part(STUDY, "methods")
    assert [(b["key"], b["written_by"]) for b in part["text"]] == [
        ("study_design", "data"), ("clinical_obs", "model")]
    facts, prompt = part["given"]
    assert facts["record"] == "recorded" and "species: rat" in facts["text"]
    assert prompt["record"] == "rebuilt" and "USER rat" in prompt["text"]
    assert "not recorded" in prompt["say"]

    def broken(ctx):
        raise RuntimeError("no profile")
    monkeypatch.setattr(methods_prompt, "build_methods_prompt", broken)
    prompt = writing_part(STUDY, "methods")["given"][1]
    assert (prompt["record"], prompt["text"]) == ("not_recorded", None)


def test_the_interpretation_served_is_the_current_one_with_its_inputs(store):
    from ui_api.writing import writing_part

    part = writing_part(STUDY, "genomics_liver_male")
    assert part["model"] == "model-g"                       # the newer file, not the older
    context, whole = part["given"]
    assert context["record"] == "as_sent" and context["text"].startswith("=== DOSE-RESPONSE")
    assert (whole["record"], whole["text"]) == ("not_recorded", None)
    assert part["knowledge_base"] == {"name": "kb-test", "sha256": "f" * 64}
    assert [(p["token"], p["cited"]) for p in part["papers_offered"]] == [("P1", True), ("P2", True)]
    assert part["text"][0]["paragraphs"][0].count("[P1") == 2   # as the model wrote it
    check = part["citation_check"]
    assert (check["untraced"], check["removed"]) == (1, True)
    assert check["items"][0] == {"token": "[P9]", "sentence": "An invented claim [P9].",
                                 "what": check["items"][0]["what"]}


def test_the_model_paragraphs_of_the_bmd_summary_have_no_recorded_prompt(store):
    from ui_api.writing import writing_part

    part = writing_part(STUDY, "bmd_summary")
    assert part["model"] == "model-a" and part["text"][0]["paragraphs"] == ["The liver was the target."]
    assert [(g["record"], g["text"]) for g in part["given"]] == [("not_recorded", None)]


def test_results_are_built_from_the_data(store):
    from ui_api.writing import writing_part

    part = writing_part(STUDY, "results")
    assert part["written_by"] == "data" and part["given"] == [] and part["model"] is None
    assert part["text"] == [{"key": "bm2_body-weight", "heading": "Body Weight",
                             "written_by": "data", "caption": "Body weights",
                             "paragraphs": ["Weights fell."]}]


def test_a_summary_built_by_rule_is_not_called_the_models(store):
    from ui_api.writing import writing_part

    part = writing_part(STUDY, "summary")
    assert part["written_by"] == "data" and part["runs"] == []
    assert part["given"][0]["record"] == "not_recorded"
    assert part["unmatched_numbers"] is None
    template = part["given"][-1]
    assert template["record"] == "recorded" and template["text"].startswith("---")
    assert part["template"]["version"] == 1


def test_a_summary_taken_from_a_run_shows_that_runs_prompt_and_numbers(store):
    from ui_api.writing import writing_part

    run = {"run_id": "r20261118T130000-def456", "at": "2026-11-18T13:00:00Z",
           "template_version": 1,
           "prompt": {"system": "S", "user": "U", "model": "model-s"},
           "paragraphs": ["Worded by the model, 12.5 ppm."], "unmatched_numbers": ["12.5"]}
    _write(store / STUDY, f"narrative_runs/summary/{run['run_id']}.json", run)
    _write(store / STUDY, "summary.json", {
        "paragraphs": run["paragraphs"], "source": "model", "approved": False, "version": 2,
        "run_id": run["run_id"], "template_version": 1, "model_used": "model-s"})
    part = writing_part(STUDY, "summary")
    assert part["written_by"] == "model" and part["recorded"]["prompt"] == "as_sent"
    assert part["given"][0]["record"] == "as_sent" and "U" in part["given"][0]["text"]
    assert part["unmatched_numbers"] == ["12.5"]
    [served] = part["runs"]
    assert served["in_use"] is True and served["model"] == "model-s"


def test_an_unknown_part_and_a_part_of_the_wrong_session_are_refused(store):
    from ui_api.refusals import explain
    from ui_api.studies import StudyRefusal
    from ui_api.writing import writing_part

    for session, part in ((STUDY, "background"), (REPORT, "methods"), (STUDY, "nothing")):
        with pytest.raises(StudyRefusal) as e:
            writing_part(session, part)
        assert explain(e.value)["error"]["code"] == "writing_part_not_found"
    with pytest.raises(StudyRefusal) as e:
        writing_part("DTXSID0000999", "background")
    assert e.value.code == "study_not_found"


# ---------------------------------------------------------------------------
# The reference list
# ---------------------------------------------------------------------------

def test_the_report_prints_one_list_and_says_what_cites_each_entry(store, kb):
    from ui_api.writing_references import CHECK_SAYS, references

    before = _snapshot(store)
    out = references(REPORT)
    assert _snapshot(store) == before

    assert out["check_says"] == CHECK_SAYS == (
        "The check establishes that a citation points at a source. It does not judge "
        "whether the source supports the sentence.")
    assert [(e["n"], e["kind"]) for e in out["entries"]] == [
        (1, "background_source"), (2, "background_source"), (3, "paper"), (4, "paper")]
    first = out["entries"][0]
    assert first["text"] == "PubChem Compound 1 (database)." and first["url"] == "https://pubchem.example/1"
    assert first["cited_in"][0]["sentences"] == [
        "Testane is a solvent [1].", "It is a liver toxicant [1, 2]."]
    # The study's papers are numbered on from the Background's sources, and
    # the sentences carry the printed numbers; the invented token is gone.
    paper = out["entries"][2]
    assert (paper["title"], paper["doi"], paper["genes"]) == ("Nrf2 in the liver", "10.1000/a", ["NFE2L2"])
    assert paper["url"] == "https://doi.org/10.1000/a"
    assert paper["statements"] == ["Nrf2 protects the liver.", "Nrf2 induces NQO1."]
    cited = paper["cited_in"][0]
    assert cited["part"] == "genomics_liver_male" and cited["study"] == "rat"
    assert cited["sentences"] == ["Nrf2 was activated [3].", "Oxidative stress followed [3, 4]."]
    assert out["entries"][3]["statements"] == []            # a paper with no statement extracted

    check = out["check"]
    assert (check["untraced"], check["removed"]) == (2, 1)
    by_where = {p["where"]: p for p in check["parts"]}
    assert by_where["background"]["removed"] is False and by_where["background"]["untraced"] == 1
    assert by_where["interpretations"]["items"][0]["token"] == "[P9]"
    assert out["knowledge_bases"] == [{"study": "rat", "study_id": STUDY, "name": "kb-test",
                                       "recorded_name": "kb-test", "same": True, "usable": True}]


def test_a_study_lists_its_own_papers_under_its_own_numbers(store, kb):
    from ui_api.writing_references import references

    out = references(STUDY)
    assert out["report"] == {"id": REPORT}
    assert [(e["n"], e["kind"]) for e in out["entries"]] == [(1, "paper"), (2, "paper")]
    assert out["entries"][0]["cited_in"][0]["sentences"][0] == "Nrf2 was activated [1]."


def test_without_a_knowledge_base_the_statements_are_absent_not_empty(store, monkeypatch):
    from knowledge_base import registry
    from ui_api.writing_references import references

    monkeypatch.setattr(registry, "kb_or_none", lambda dtxsid, needs=None: None)
    out = references(STUDY)
    assert out["entries"][0]["statements"] is None
    assert out["knowledge_bases"][0]["usable"] is False


# ---------------------------------------------------------------------------
# The routes, and the wording
# ---------------------------------------------------------------------------

def test_the_routes_answer_and_refuse_in_the_envelope(store, kb):
    from fastapi.testclient import TestClient
    from web_routes.background_server import app

    client = TestClient(app)
    assert client.get(f"/api/v2/studies/{REPORT}/writing").json()["kind"] == "report"
    assert client.get(f"/api/v2/studies/{STUDY}/writing/summary").json()["key"] == "summary"
    assert len(client.get(f"/api/v2/studies/{REPORT}/references").json()["entries"]) == 4
    missing = client.get(f"/api/v2/studies/{STUDY}/writing/nothing")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "writing_part_not_found"
    gone = client.get("/api/v2/studies/DTXSID0000999/references")
    assert gone.status_code == 404 and gone.json()["error"]["code"] == "study_not_found"


SECOND_PERSON = re.compile(r"\b(you|your|yours|yourself)\b", re.I)


def _says(node, found=None):
    """Every text the interface shows as its own words (not the report's)."""
    found = [] if found is None else found
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, str) and (key.endswith(("say", "says")) or key in ("title", "what")):
                found.append(value)
            else:
                _says(value, found)
    elif isinstance(node, list):
        for item in node:
            _says(item, found)
    return found


def test_the_wording_addresses_nobody(store, kb):
    from ui_api.refusals import STUDY_REFUSALS
    from ui_api.writing import writing_overview, writing_part
    from ui_api.writing_references import references

    served = [writing_overview(REPORT), writing_overview(STUDY), references(REPORT),
              writing_part(REPORT, "background")]
    served += [writing_part(STUDY, p) for p in
               ("methods", "results", "bmd_summary", "genomics_liver_male", "summary")]
    texts = _says(served)
    assert len(texts) > 40
    texts += [STUDY_REFUSALS[code].say for code in (
        "writing_part_not_found", "background_is_the_reports", "summary_is_a_studys",
        "summary_not_ready", "summary_run_not_found", "model_not_allowed", "writing_failed")]
    assert [t for t in texts if SECOND_PERSON.search(t) or "wizard" in t.lower()] == []
