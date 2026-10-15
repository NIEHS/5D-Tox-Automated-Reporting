"""
C2 step 7: the command line's Background (§4.10) and the genomics narrative
overrides (§4.12) never lose a person's text. I1 for the CLI path, with the
LLM and the data gatherers replaced by stubs.
"""

import json

import pytest

ID = "DTXSID_C2CLI"


@pytest.fixture
def gen(monkeypatch):
    """tooling.generate_report.background with the gatherer and the LLM stubbed."""
    import narrative.background_writer as bw
    import narrative.data_gatherer as dg
    from tooling import generate_report

    class _Data:
        unreachable_sources = []

    calls = []
    monkeypatch.setattr(dg, "gather_all", lambda ident, log: _Data())

    def _generate(data, model):
        calls.append(model)
        return {"paragraphs": ["machine background"], "references": [{"n": 1}],
                "model_used": "m"}
    monkeypatch.setattr(bw, "generate_background", _generate)
    monkeypatch.setattr(bw, "DEFAULT_CLAUDE_MODEL", "m", raising=False)
    import narrative.chem_resolver as cr
    monkeypatch.setattr(cr.ChemicalIdentity, "from_dict", staticmethod(lambda d: d))
    generate_report.background_calls = calls
    return generate_report


def _bg(d):
    return json.loads((d / "background.json").read_text())


def test_cli_background_writes_a_draft_and_archives_the_prior(gen, sessions_dir):
    from workflow.store import DiskPoolStore
    d = sessions_dir / ID
    d.mkdir(parents=True)
    (d / "background.json").write_text(json.dumps({"paragraphs": ["old"], "version": 1}))
    gen.background(ID, {"pubchem_cid": 1}, "m", DiskPoolStore())
    assert _bg(d)["paragraphs"] == ["machine background"] and _bg(d)["version"] == 2
    archived = [json.loads(p.read_text()) for p in (d / "history" / "background").glob("*.json")]
    assert [a["paragraphs"] for a in archived] == [["old"]]


def test_cli_background_never_replaces_an_approved_background(gen, sessions_dir, capsys):
    from workflow.store import DiskPoolStore
    d = sessions_dir / ID
    d.mkdir(parents=True)
    mine = {"paragraphs": ["mine"], "approved": True, "facts": ["final", "protected"], "version": 1}
    (d / "background.json").write_text(json.dumps(mine))
    gen.background(ID, {"pubchem_cid": 1}, "m", DiskPoolStore())
    assert _bg(d) == mine
    assert gen.background_calls == []                     # the LLM was not even asked
    assert "REFUSED" in capsys.readouterr().out

    gen.background(ID, {"pubchem_cid": 1}, "m", DiskPoolStore(), force=True)   # no reason
    assert _bg(d) == mine
    assert "reason_required" in capsys.readouterr().out

    gen.background(ID, {"pubchem_cid": 1}, "m", DiskPoolStore(), force=True,
                   reason="new IRIS assessment")
    assert _bg(d)["paragraphs"] == ["machine background"] and _bg(d)["approved"] is False
    from pipeline.session_store import read_version_history
    e = read_version_history(ID, "background")[-1]
    assert e["forced"] is True and e["reason"] == "new IRIS assessment" and e["act"] == "background"


def test_cli_force_and_reason_flags_parse(gen):
    args = gen._parse_args([ID, "--background", "--force", "--reason", "why"])
    assert args.force is True and args.reason == "why"


# --- the genomics overrides -------------------------------------------------------

def test_an_override_write_archives_the_text_it_replaces(client, sessions_dir):
    d = sessions_dir / ID
    d.mkdir(parents=True)
    url = f"/api/session/{ID}/genomics-narrative-override"
    client.post(url, json={"kind": "gene_set", "organ": "liver", "paragraphs": ["first"]})
    assert not (d / "history").exists()                     # nothing to archive yet
    client.post(url, json={"kind": "gene_set", "organ": "liver", "paragraphs": ["second"]})
    (archive,) = list((d / "history" / "genomics_liver").glob("*.json"))   # no cache: by organ
    assert json.loads(archive.read_text())["genomics_narrative_override"] == {
        "gene_set": ["first"]}
    # With the Process cache, by organ and sex, like the sections.
    (d / "_cache_genomics_x.json").write_text(json.dumps({"liver_male": {}, "kidney_male": {}}))
    client.post(url, json={"kind": "gene_bmd", "organ": "liver", "paragraphs": ["third"]})
    (archive,) = list((d / "history" / "genomics_liver_male").glob("*.json"))
    assert json.loads(archive.read_text())["genomics_narrative_override"] == {
        "gene_set": ["second"]}
    from pipeline.session_store import read_version_history
    (e,) = read_version_history(ID, "genomics_liver_male")
    assert (e["cause"], e["act"], e["author"]) == ("discard", "save", "person")


def test_regenerate_archives_the_person_s_text_before_clearing_it(client, sessions_dir,
                                                                 monkeypatch):
    import web_routes.llm_routes as llm
    d = sessions_dir / ID
    d.mkdir(parents=True)
    (d / "_cache_genomics_x.json").write_text(json.dumps({
        "liver_male": {"organ": "liver", "sex": "male", "gene_sets_by_stat": {"median": []}},
        "liver_female": {"organ": "liver", "sex": "female", "gene_sets_by_stat": {"median": []}},
    }))
    (d / "genomics_narrative_overrides.json").write_text(json.dumps(
        {"gene_set": {"Liver": ["person text"]}, "gene_bmd": {}}))

    async def _gen(**kw):
        return {"gene_set_narrative": ["new"], "gene_narrative": []}
    monkeypatch.setattr(llm, "generate_genomics_narrative_async", _gen)

    url = f"/api/session/{ID}/regenerate-genomics-narrative"
    r = client.post(url, json={"organ": "liver"})
    assert r.status_code == 400 and r.json()["code"] == "reason_required"
    assert json.loads((d / "genomics_narrative_overrides.json").read_text())["gene_set"] == {
        "Liver": ["person text"]}

    r = client.post(url, json={"organ": "liver", "reason": "the gene sets changed"})
    assert r.status_code == 200, r.text
    assert json.loads((d / "genomics_narrative_overrides.json").read_text())["gene_set"] == {}
    from pipeline.session_store import read_version_history
    for sex in ("female", "male"):
        key = f"genomics_liver_{sex}"
        (archive,) = list((d / "history" / key).glob("*.json"))
        assert json.loads(archive.read_text())["genomics_narrative_override"] == {
            "gene_set": ["person text"]}
        (e,) = read_version_history(ID, key)
        assert (e["act"], e["actor"], e["reason"], e["cause"]) == (
            "regenerate", "person", "the gene sets changed", "discard")


def test_forcing_a_genomics_narrative_needs_a_reason(client, sessions_dir):
    r = client.post("/api/generate-genomics-narrative", json={
        "dtxsid": ID, "organ": "liver", "sex": "male", "force": True})
    assert r.status_code == 400 and r.json()["code"] == "reason_required"
