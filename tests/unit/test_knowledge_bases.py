"""Named crawl queries → named knowledge bases (ADR-0034).

The query is text, checked only for shape and archived when replaced; a named
crawl runs it, stage by stage, into a knowledge base whose capabilities are
read off its tables; a report reads the knowledge base its definition names,
else the default; a knowledge base that cannot ground the genomics
interpretation is refused; the query agent proposes and saves nothing; a
change of knowledge base stales the genomics sections.
"""

from __future__ import annotations

import json
import shutil
import textwrap
from pathlib import Path

import duckdb
import pytest

from knowledge_base import crawl_queries, registry

REPO = Path(__file__).resolve().parents[2]

GENERIC_QUERY = textwrap.dedent("""\
    format: 1
    description: A query about something other than genes.
    relevance:
      keywords: [river, sediment]
    tags:
      place: {delta: [delta], estuary: [estuary]}
    crawls:
      - name: rivers
        seeds: ['DOI:10.1/river']
    extract:
      system: You read papers about rivers.
      fields:
        - {name: claims, type: list, describe: the paper's findings}
        - {name: rivers, type: list, describe: rivers named, normalize: {case: lower}}
        - {name: summary, type: text, describe: one sentence}
    """)


@pytest.fixture()
def stores(tmp_path, monkeypatch):
    """Empty query and knowledge-base stores."""
    queries, kbs = tmp_path / "crawl_queries", tmp_path / "knowledge_bases"
    queries.mkdir()
    kbs.mkdir()
    monkeypatch.setattr(crawl_queries, "QUERIES_DIR", queries)
    monkeypatch.setattr(registry, "KB_ROOT", kbs)
    return queries, kbs


def _toy_kb(name: str, tables: dict[str, int], complete: bool = True) -> None:
    """A registered knowledge base whose database holds ``tables`` (rows each)."""
    d = registry.kb_dir(name)
    d.mkdir(parents=True)
    con = duckdb.connect(str(d / registry.DB_FILE))
    for table, rows in tables.items():
        con.execute(f'CREATE TABLE "{table}" (x INTEGER)')
        for i in range(rows):
            con.execute(f'INSERT INTO "{table}" VALUES ({i})')
    con.close()
    registry.write_manifest(name, {"query": {"name": "q", "text": ""}, "complete": complete,
                                   "stages": []})


GENOMICS_TABLES = {"papers": 1, "paper_claims": 1, "genes": 1, "paper_genes": 1,
                   "paper_organs": 1, "go_terms": 1, "gene_go_terms": 1, "pathways": 1}


# ---------------------------------------------------------------------------
# The query store
# ---------------------------------------------------------------------------

def test_baseline_query_is_a_valid_query():
    query = crawl_queries.parse((REPO / "crawl_queries" / "baseline.yaml").read_text())
    assert [c["name"] for c in query["crawls"]][0] == "toxicogenomics"
    assert query["consensus"] == {"field": "genes", "by": "organs", "strong": 3, "moderate": 2}


def test_save_archives_the_text_it_replaces(stores):
    queries, _ = stores
    first = crawl_queries.save("rivers", GENERIC_QUERY)
    assert first["archived"] is None
    edited = GENERIC_QUERY.replace("[river, sediment]", "[river, sediment, delta]")
    second = crawl_queries.save("rivers", edited)
    assert second["archived"]
    assert crawl_queries.read("rivers") == edited
    [entry] = crawl_queries.history("rivers")
    assert (queries / ".history" / "rivers" / entry).read_text() == GENERIC_QUERY
    assert "+relevance" not in crawl_queries.diff(GENERIC_QUERY, edited)
    assert "delta]" in crawl_queries.diff(GENERIC_QUERY, edited)


@pytest.mark.parametrize("text, problem", [
    ("format: 1\ncrawls: [", "not valid YAML"),
    ("format: 2\ncrawls: [{name: a, seeds: [x]}]", "format must be 1"),
    ("format: 1\ncrawls: []", "at least one crawl"),
    ("format: 1\ncrawls: [{name: a}]", "no seeds and no searches"),
    ("format: 1\nsurprise: 1\ncrawls: [{name: a, seeds: [x]}]", "unknown section"),
    ("format: 1\ncrawls: [{name: a, seeds: [x]}]\nconsensus: {field: genes}",
     "extracts nothing"),
])
def test_a_malformed_query_is_refused_and_nothing_saved(stores, text, problem):
    queries, _ = stores
    with pytest.raises(crawl_queries.QueryError, match=problem):
        crawl_queries.save("bad", text)
    assert not (queries / "bad.yaml").exists()


def test_the_check_never_judges_the_topic():
    """Any topic is a query: the check reads shapes only."""
    crawl_queries.parse(GENERIC_QUERY)


# ---------------------------------------------------------------------------
# A named crawl, stage by stage (stub crawler and model)
# ---------------------------------------------------------------------------

class _StubModel:
    """An extraction endpoint answering from the paper's title."""
    name, model, url, weight = "stub", "stub", "stub://", 1

    def is_available(self):
        return True

    def generate(self, prompt, system=""):
        river = "Nile" if "Nile" in prompt else "Rhine"
        return json.dumps({"claims": [f"{river} sediment rises"], "rivers": [river.upper()],
                           "summary": "s"})


def _stub_pipeline(monkeypatch):
    import knowledge_base.citegraph as citegraph
    from knowledge_base import run_crawl
    from knowledge_base.extract import ParallelExtractionEngine

    def crawl(query, crawl, out_dir, api_key, known):
        out_dir.mkdir(parents=True, exist_ok=True)
        papers = [{"paper_id": f"p{i}", "title": f"The {r} delta", "year": 2020,
                   "abstract": f"A study of the {r} river and its sediment, " * 3,
                   "relevance_score": 0.9, "is_seed": i == 0, "is_review": False}
                  for i, r in enumerate(["Nile", "Rhine", "Nile"])]
        (out_dir / "papers.json").write_text(json.dumps(papers))
        (out_dir / "edges.json").write_text(json.dumps([{"source": "p0", "target": "p1"}]))
        return {}

    monkeypatch.setattr(citegraph, "run_crawl", crawl)
    monkeypatch.setattr(run_crawl, "s2_reachable", lambda: None)
    monkeypatch.setattr(run_crawl, "fetch_fulltext", lambda papers: {})
    monkeypatch.setattr(run_crawl, "extraction_engine",
                        lambda spec: ParallelExtractionEngine(spec, [_StubModel()]))


def test_a_query_about_anything_builds_the_generic_tables_only(stores, monkeypatch):
    from knowledge_base import run_crawl
    _stub_pipeline(monkeypatch)
    crawl_queries.save("rivers", GENERIC_QUERY)
    m = run_crawl.run("rivers", "rivers-1")
    assert m["complete"] is True
    assert {s["stage"]: s["status"] for s in m["stages"]} == {
        "crawl": "ran", "extract": "ran", "consensus": "skipped", "follow_on": "skipped",
        "annotate": "skipped", "build": "ran"}
    assert m["capabilities"] == ["claims", "papers"]
    assert set(m["tables"]) == {"papers", "citation_edges", "paper_claims", "paper_entities"}
    con = duckdb.connect(str(registry.kb_dir("rivers-1") / registry.DB_FILE), read_only=True)
    try:
        rows = con.execute("SELECT value, COUNT(*) FROM paper_entities WHERE field = 'rivers' "
                           "GROUP BY value ORDER BY value").fetchall()
    finally:
        con.close()
    assert rows == [("nile", 2), ("rhine", 1)]      # the query's normalize: lower
    assert m["query"]["text"] == GENERIC_QUERY
    # A finished knowledge base's name is never reused.
    with pytest.raises(registry.KnowledgeBaseError, match="never reused"):
        run_crawl.run("rivers", "rivers-1")


def test_a_stage_that_cannot_run_leaves_the_knowledge_base_unfinished(stores, monkeypatch):
    from knowledge_base import run_crawl
    _stub_pipeline(monkeypatch)
    monkeypatch.setattr(run_crawl, "s2_reachable", lambda: "Semantic Scholar unreachable")
    crawl_queries.save("rivers", GENERIC_QUERY)
    m = run_crawl.run("rivers", "rivers-2")
    assert m["complete"] is False
    assert m["stages"][0] == {"stage": "crawl", "status": "could_not_run",
                              "detail": "Semantic Scholar unreachable"}
    with pytest.raises(registry.KnowledgeBaseError, match="unfinished"):
        registry.usable("rivers-2")


def test_a_paper_the_model_did_not_answer_for_stops_the_extract_stage(stores, monkeypatch):
    from knowledge_base import run_crawl
    from knowledge_base.extract import ParallelExtractionEngine
    _stub_pipeline(monkeypatch)

    class Silent(_StubModel):
        def generate(self, prompt, system=""):
            return "" if "Rhine" in prompt else super().generate(prompt, system)

    monkeypatch.setattr(run_crawl, "extraction_engine",
                        lambda spec: ParallelExtractionEngine(spec, [Silent()]))
    crawl_queries.save("rivers", GENERIC_QUERY)
    m = run_crawl.run("rivers", "rivers-3")
    assert m["complete"] is False
    extract = next(s for s in m["stages"] if s["stage"] == "extract")
    assert extract["status"] == "could_not_run" and "1 of 3 papers" in extract["detail"]
    assert not (registry.kb_dir("rivers-3") / "crawl" / "rivers" / "extractions.json").exists()


# ---------------------------------------------------------------------------
# Which knowledge base a report reads
# ---------------------------------------------------------------------------

@pytest.fixture()
def templates(tmp_path, monkeypatch, sessions_dir):
    import document_model.document_config  # noqa: F401 — builds the shared tree first
    from document_model import document_definition
    from document_model import document_template as dt
    root = tmp_path / "templates"
    (root / "eras").mkdir(parents=True)
    (root / "eras" / "new.yaml").write_text(textwrap.dedent("""\
        document:
        - region: body
          children:
          - {id: methods, type: heading-only, title: Methods}
        """), encoding="utf-8")
    monkeypatch.setattr(dt, "TEMPLATES_DIR", root)
    monkeypatch.setattr(document_definition, "DEFAULT_DEFINITION", "eras/new")
    (sessions_dir / "DTXSIDX").mkdir()
    return root


def test_the_default_serves_a_report_whose_definition_names_none(stores, templates):
    _toy_kb("tox", GENOMICS_TABLES)
    registry.set_default("tox")
    kb = registry.kb_for("DTXSIDX")
    assert (kb["name"], kb["source"]) == ("tox", "default")


def test_the_definition_names_it_through_extends(stores, templates):
    _toy_kb("tox", GENOMICS_TABLES)
    _toy_kb("tox-2", GENOMICS_TABLES)
    registry.set_default("tox")
    (templates / "eras" / "kb.yaml").write_text("extends: eras/new\nknowledge_base: tox-2\n")
    study = templates / "studies" / "DTXSIDX"
    study.mkdir(parents=True)
    (study / "document.yaml").write_text("# its own\nextends: eras/kb\n")
    kb = registry.kb_for("DTXSIDX")
    assert (kb["name"], kb["source"]) == ("tox-2", "definition")


def test_assigning_writes_the_definition_and_keeps_its_comments(stores, templates):
    from safeguards.guarded import assign_knowledge_base
    _toy_kb("tox", GENOMICS_TABLES)
    _toy_kb("tox-2", GENOMICS_TABLES)
    registry.set_default("tox")
    out = assign_knowledge_base("DTXSIDX", "tox-2")
    assert out["created"] is True
    path = templates / "studies" / "DTXSIDX" / "document.yaml"
    assert "extends: eras/new\n" in path.read_text()
    assert registry.kb_for("DTXSIDX")["name"] == "tox-2"
    path.write_text("# a comment kept\n" + path.read_text())
    assign_knowledge_base("DTXSIDX", "tox")
    assert path.read_text().count("knowledge_base:") == 1
    assert path.read_text().startswith("# a comment kept\n")
    assign_knowledge_base("DTXSIDX", None)
    assert "knowledge_base:" not in path.read_text()
    assert registry.kb_for("DTXSIDX")["source"] == "default"


def test_a_knowledge_base_that_cannot_ground_genomics_is_refused(stores, templates):
    from safeguards.guarded import assign_knowledge_base, set_default_knowledge_base
    from safeguards.refusals import Refused, explain
    _toy_kb("rivers", {"papers": 2, "paper_claims": 2})
    _toy_kb("half", GENOMICS_TABLES, complete=False)
    for act in (lambda n: assign_knowledge_base("DTXSIDX", n), set_default_knowledge_base):
        with pytest.raises(Refused) as e:
            act("rivers")
        said = explain(e.value)["error"]
        assert said["code"] == "knowledge_base_cannot_serve"
        assert "genes, go, pathways" in said["say"]
        with pytest.raises(Refused) as e:
            act("half")
        assert explain(e.value)["error"]["code"] == "knowledge_base_unfinished"
        with pytest.raises(Refused) as e:
            act("nowhere")
        assert explain(e.value)["error"]["code"] == "knowledge_base_unknown"
    assert not (templates / "studies").exists()
    assert registry.default_name() is None


def test_a_fixed_definition_refuses_an_assignment(stores, templates):
    from document_model.definition_pin import pin_definition
    from safeguards.guarded import assign_knowledge_base
    from safeguards.refusals import Refused
    _toy_kb("tox", GENOMICS_TABLES)
    pin_definition("DTXSIDX", "fixed")
    with pytest.raises(Refused) as e:
        assign_knowledge_base("DTXSIDX", "tox")
    assert e.value.code == "knowledge_base_definition_fixed"


# ---------------------------------------------------------------------------
# The query agent
# ---------------------------------------------------------------------------

class _ScriptedAgent:
    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    def generate(self, prompt, system=""):
        self.prompts.append((prompt, system))
        return self.replies.pop(0)


def test_the_agent_proposes_a_diff_and_saves_nothing(stores):
    from knowledge_base.query_agent import propose
    queries, _ = stores
    crawl_queries.save("rivers", GENERIC_QUERY)
    before = sorted(p.name for p in queries.rglob("*"))
    revised = GENERIC_QUERY.replace("[river, sediment]", "[river, sediment, estuary]")
    agent = _ScriptedAgent(f"<explanation>Added estuary.</explanation>\n<query>\n{revised}</query>")
    out = propose(GENERIC_QUERY, "also estuaries", endpoint=agent)
    assert out["valid"] and out["changed"] and out["explanation"] == "Added estuary."
    assert "+  keywords: [river, sediment, estuary]" in out["diff"]
    assert out["text"] == revised
    assert sorted(p.name for p in queries.rglob("*")) == before
    assert crawl_queries.read("rivers") == GENERIC_QUERY
    prompt, system = agent.prompts[0]
    assert "also estuaries" in prompt and "Format 1" in system


def test_an_unusable_proposal_is_sent_back_once_then_returned_as_invalid():
    from knowledge_base.query_agent import propose
    agent = _ScriptedAgent("<explanation>x</explanation><query>\nformat: 2\n</query>",
                           "no blocks at all")
    out = propose(GENERIC_QUERY, "break it", endpoint=agent)
    assert len(agent.prompts) == 2 and "could not be used" in agent.prompts[1][0]
    assert out["valid"] is False and out["problem"] == "the reply held no <query> block"
    assert out["text"] == GENERIC_QUERY and out["changed"] is False


# ---------------------------------------------------------------------------
# A change of knowledge base stales the genomics interpretation
# ---------------------------------------------------------------------------

def test_a_changed_knowledge_base_stales_the_genomics_sections(stores, templates, sessions_dir):
    from pipeline.kb_currency import RECORD_FILE, reconcile
    _toy_kb("tox", GENOMICS_TABLES)
    _toy_kb("tox-2", GENOMICS_TABLES)
    registry.set_default("tox")
    session = sessions_dir / "DTXSIDX"
    cache = session / "_cache_interpretation_liver_male_abc.json"
    cache.write_text("{}")
    (session / "genomics_liver_male.json").write_text(json.dumps(
        {"paragraphs": ["text"], "approved": True, "model_used": "m"}))
    (session / "bm2_body_weight.json").write_text(json.dumps({"paragraphs": ["x"]}))

    first = reconcile("DTXSIDX")          # no record: the caches predate named KBs
    assert first["changed"] is False      # (no knowledge base replaces bmdx.duckdb here)
    assert json.loads((session / RECORD_FILE).read_text())["name"] == "tox"
    assert cache.exists()

    registry.set_default("tox-2")
    out = reconcile("DTXSIDX")
    assert out["changed"] is True and out["deleted"] == [cache.name]
    assert out["marked_stale"] == ["genomics_liver_male.json"]
    section = json.loads((session / "genomics_liver_male.json").read_text())
    assert section["stale"] is True
    assert section["regenerated"] == {"reason": "knowledge_base_changed"}
    assert "stale" not in json.loads((session / "bm2_body_weight.json").read_text())
    assert reconcile("DTXSIDX")["changed"] is False


def test_a_session_processed_before_named_knowledge_bases_read_the_legacy_one(
        stores, templates, sessions_dir):
    from pipeline.kb_currency import reconcile
    _toy_kb("legacy", GENOMICS_TABLES)
    m = registry.manifest("legacy")
    m["replaces"] = "bmdx.duckdb"
    (registry.kb_dir("legacy") / registry.MANIFEST_FILE).write_text(json.dumps(m))
    _toy_kb("newer", GENOMICS_TABLES)
    registry.set_default("newer")
    (sessions_dir / "DTXSIDX" / "_cache_interpretation_liver_male_abc.json").write_text("{}")
    out = reconcile("DTXSIDX")
    assert out["previous"]["name"] == "legacy" and out["changed"] is True


# ---------------------------------------------------------------------------
# The query-driven build gives back the May 2026 database
# ---------------------------------------------------------------------------

BASELINE = REPO / "knowledge_bases" / "baseline-2026-05"


@pytest.mark.skipif(not (BASELINE / "crawl" / "sources.json").exists(),
                    reason="the baseline crawl outputs are not present (untracked data)")
def test_the_baseline_rebuilds_row_for_row(tmp_path):
    from knowledge_base.build_db import build
    query = crawl_queries.parse((REPO / "crawl_queries" / "baseline.yaml").read_text())
    rebuilt = tmp_path / "kb.duckdb"
    build(rebuilt, BASELINE / "crawl", query)
    old = duckdb.connect(str(BASELINE / "kb.duckdb"), read_only=True)
    new = duckdb.connect(str(rebuilt), read_only=True)
    try:
        tables = sorted(t for (t,) in old.execute("SHOW TABLES").fetchall())
        assert tables == sorted(t for (t,) in new.execute("SHOW TABLES").fetchall()
                                if t != "paper_entities")
        for t in tables:
            cols = [c for (c, *_rest) in old.execute(f'DESCRIBE "{t}"').fetchall()]
            order = ", ".join(f'"{c}"' for c in cols)
            sql = f'SELECT {order} FROM "{t}" ORDER BY ALL'
            assert old.execute(sql).fetchall() == new.execute(sql).fetchall(), t
    finally:
        old.close()
        new.close()


# ---------------------------------------------------------------------------
# The routes
# ---------------------------------------------------------------------------

def test_the_routes_save_list_and_refuse(client, stores, templates):
    _toy_kb("tox", GENOMICS_TABLES)
    _toy_kb("rivers", {"papers": 1, "paper_claims": 1})
    registry.set_default("tox")

    r = client.post("/api/crawl-queries/rivers", json={"text": GENERIC_QUERY})
    assert r.status_code == 200 and r.json()["saved"] is True
    r = client.post("/api/crawl-queries/rivers", json={"text": "format: 3"})
    assert r.status_code == 422 and r.json()["code"] == "crawl_query_invalid"
    assert client.get("/api/crawl-queries/rivers").json()["text"] == GENERIC_QUERY
    assert [q["name"] for q in client.get("/api/crawl-queries").json()["queries"]] == ["rivers"]

    listed = client.get("/api/knowledge-bases").json()
    assert listed["default"] == "tox"
    assert {k["name"] for k in listed["knowledge_bases"]} == {"tox", "rivers"}

    r = client.post("/api/session/DTXSIDX/knowledge-base", json={"name": "rivers"})
    assert r.status_code == 409 and r.json()["code"] == "knowledge_base_cannot_serve"
    r = client.post("/api/knowledge-bases/default", json={"name": "rivers"})
    assert r.status_code == 409
    got = client.get("/api/session/DTXSIDX/knowledge-base").json()
    assert (got["name"], got["source"], got["usable"]) == ("tox", "default", True)

    r = client.post("/api/knowledge-bases/run", json={"query": "rivers", "name": "tox"})
    assert r.status_code == 409 and r.json()["code"] == "knowledge_base_name_taken"
