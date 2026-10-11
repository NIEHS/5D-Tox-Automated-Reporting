"""
Session interpretation chat (ADR-0022): tools, agent loop, store, routes.

The model is never called for real: a scripted fake client returns tool_use
blocks and then a final answer, so these tests pin the mechanics that make an
answer grounded — read-only SQL over the session DB, [Sn] tokens issued only
for papers a tool returned, citation verification of the final answer, and
transcript persistence — without network or credentials.
"""

import json
import types

import duckdb
import pytest

import narrative.chat_agent as agent
from narrative.chat_tools import ChatToolbox, SourceRegistry
from pipeline import chat_store
from pipeline.session_schema import schema_statements
from query.session_query import session_db_path


# ---------------------------------------------------------------------------
# Fixtures: a tiny session DB + a tiny knowledge graph
# ---------------------------------------------------------------------------

@pytest.fixture
def session_with_db(sessions_dir):
    dtxsid = "DTXSID_CHAT"
    (sessions_dir / dtxsid).mkdir()
    (sessions_dir / dtxsid / "identity.json").write_text(json.dumps({"name": "Testol", "casrn": "1-1-1"}))
    con = duckdb.connect(str(session_db_path(dtxsid)))
    for stmt in schema_statements():
        con.execute(stmt)
    con.execute(
        "INSERT INTO apical_result (dtxsid, platform, sex, endpoint, bmd_str, bmdl_str, "
        "bmd_num, bmdl_num, bmd_status, loel, noel, direction, model_name, responsive, trend_marker) "
        "VALUES (?, 'Clinical Chemistry', 'male', 'ALT', '12.5', '8.1', 12.5, 8.1, 'ok', 30, 10, 'up', 'Hill', TRUE, '')",
        [dtxsid],
    )
    con.close()
    return dtxsid


@pytest.fixture
def kb_path(tmp_path):
    p = tmp_path / "kb.duckdb"
    con = duckdb.connect(str(p))
    con.execute("CREATE TABLE papers (paper_id VARCHAR, title VARCHAR, year INTEGER, venue VARCHAR, doi VARCHAR, citation_count INTEGER)")
    con.execute("CREATE TABLE paper_genes (paper_id VARCHAR, gene_symbol VARCHAR)")
    con.execute("CREATE TABLE genes (gene_symbol VARCHAR, organs VARCHAR[], evidence VARCHAR, mention_count INTEGER)")
    con.execute("CREATE TABLE pathways (gene_symbol VARCHAR, pathway_db VARCHAR, pathway_id VARCHAR, pathway_name VARCHAR, species VARCHAR)")
    con.execute("CREATE TABLE gene_go_terms (gene_symbol VARCHAR, go_id VARCHAR)")
    con.execute("CREATE TABLE go_terms (go_id VARCHAR, go_term VARCHAR, cluster_id INTEGER)")
    con.execute("CREATE TABLE paper_claims (paper_id VARCHAR, claim VARCHAR)")
    con.execute("INSERT INTO papers VALUES ('pa', 'CYP7A1 and bile acid synthesis', 2020, 'Tox Sci', '10.1/a', 40), ('pb', 'PPAR-alpha in rat liver', 2019, 'Hepatology', '10.1/b', 12)")
    con.execute("INSERT INTO paper_genes VALUES ('pa', 'CYP7A1'), ('pb', 'CYP7A1'), ('pb', 'ACOX1')")
    con.execute("INSERT INTO genes VALUES ('CYP7A1', ['liver'], 'consensus', 3)")
    con.execute("INSERT INTO pathways VALUES ('CYP7A1', 'KEGG', 'k1', 'Bile acid biosynthesis', 'rat')")
    con.execute("INSERT INTO gene_go_terms VALUES ('CYP7A1', 'GO:1')")
    con.execute("INSERT INTO go_terms VALUES ('GO:1', 'bile acid biosynthetic process', 4)")
    con.execute("INSERT INTO paper_claims VALUES ('pa', 'CYP7A1 is rate limiting')")
    con.close()
    return str(p)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def test_sql_tools_are_read_only_and_capped(session_with_db, kb_path):
    tb = ChatToolbox(session_with_db, SourceRegistry(), kb_path=kb_path)
    tables = json.loads(tb.execute("list_tables", {}))
    assert any(t["name"] == "apical_result" for t in tables["tables"])
    rows = json.loads(tb.execute("run_sql", {"sql": "SELECT endpoint, bmd_num FROM apical_result"}))
    assert rows["rows"] == [["ALT", 12.5]] and rows["truncated"] is False
    rejected = json.loads(tb.execute("run_sql", {"sql": "DELETE FROM apical_result"}))
    assert "error" in rejected
    assert [t["tool"] for t in tb.trace] == ["list_tables", "run_sql", "run_sql"]


def test_sql_tool_explains_missing_db(sessions_dir, kb_path):
    (sessions_dir / "DTXSID_NODB").mkdir()
    tb = ChatToolbox("DTXSID_NODB", SourceRegistry(), kb_path=kb_path)
    out = json.loads(tb.execute("run_sql", {"sql": "SELECT 1"}))
    assert "run Process first" in out["error"]


def test_kb_tools_register_stable_citation_tokens(session_with_db, kb_path):
    reg = SourceRegistry()
    tb = ChatToolbox(session_with_db, reg, kb_path=kb_path)
    ev = json.loads(tb.execute("kb_gene_evidence", {"gene_symbol": "cyp7a1"}))
    assert ev["gene"] == "CYP7A1" and ev["organs"] == ["liver"]
    assert [p["cite"] for p in ev["papers"]] == ["[S1]", "[S2]"]      # ranked by citations
    assert ev["papers"][0]["title"] == "CYP7A1 and bile acid synthesis"
    pool = json.loads(tb.execute("kb_papers_for_genes", {"gene_symbols": ["CYP7A1", "ACOX1"]}))
    # Same papers → same tokens (registry de-duplicates by paper_id).
    assert {p["cite"] for p in pool["papers"]} == {"[S1]", "[S2]"}
    assert reg.tokens() == {"S1", "S2"}
    genes = json.loads(tb.execute("kb_pathway_genes", {"pathway_name": "Bile acid biosynthesis"}))
    assert genes["genes"] == ["CYP7A1"]
    # Round-trips through JSON for persistence.
    assert SourceRegistry.from_json(reg.to_json()).tokens() == {"S1", "S2"}


def test_kb_tools_degrade_when_kb_missing(session_with_db, tmp_path):
    tb = ChatToolbox(session_with_db, SourceRegistry(), kb_path=tmp_path / "nope.duckdb")
    out = json.loads(tb.execute("kb_gene_evidence", {"gene_symbol": "CYP7A1"}))
    assert "unavailable" in out["error"]
    assert "error" in json.loads(tb.execute("no_such_tool", {}))


def test_report_section_tools(session_with_db, kb_path, monkeypatch):
    import narrative.chat_tools as ct
    fake = {"background": {"paragraphs": ["p1", "p2"]}, "bmd_summary": {"endpoints": [{"endpoint": "ALT"}]}, "empty": []}
    monkeypatch.setattr("rendering.latex_export.load_session_data", lambda *a, **k: fake)
    tb = ct.ChatToolbox(session_with_db, SourceRegistry(), kb_path=kb_path)
    listing = json.loads(tb.execute("list_report_sections", {}))
    assert {s["section"] for s in listing["sections"]} == {"background", "bmd_summary"}
    assert json.loads(tb.execute("read_report_section", {"section": "background", "subkey": "paragraphs"})) == ["p1", "p2"]
    assert "error" in json.loads(tb.execute("read_report_section", {"section": "missing"}))


# ---------------------------------------------------------------------------
# Agent loop with a scripted fake model
# ---------------------------------------------------------------------------

def _block(**kw):
    return types.SimpleNamespace(**kw)


class _FakeClient:
    """Scripted responses: each call pops the next (stop_reason, blocks)."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.messages = self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        stop, blocks = self.script.pop(0)
        return types.SimpleNamespace(stop_reason=stop, content=blocks)


@pytest.mark.asyncio
async def test_run_turn_executes_tools_and_verifies_citations(session_with_db, kb_path):
    reg = SourceRegistry()
    tb = ChatToolbox(session_with_db, reg, kb_path=kb_path)
    client = _FakeClient([
        ("tool_use", [
            _block(type="text", text="Let me check."),
            _block(type="tool_use", id="t1", name="run_sql", input={"sql": "SELECT bmd_num FROM apical_result"}),
            _block(type="tool_use", id="t2", name="kb_gene_evidence", input={"gene_symbol": "CYP7A1"}),
        ]),
        ("end_turn", [
            _block(type="text", text="ALT BMD was 12.5 mg/kg. Bile acid synthesis is implicated [S1]. Also [S7]."),
        ]),
    ])
    events = []
    result = await agent.run_turn(
        history=[{"role": "user", "content": "earlier q"}, {"role": "assistant", "content": "earlier a", "tool_trace": [1]}],
        user_message="What is the ALT BMD?", toolbox=tb, chemical_name="Testol",
        client=client, emit=lambda e, d: events.append(e),
    )
    # Two model rounds; the second call carried the tool results back.
    assert len(client.calls) == 2 and result["rounds"] == 2
    second = client.calls[1]["messages"]
    assert second[-1]["role"] == "user" and {b["tool_use_id"] for b in second[-1]["content"]} == {"t1", "t2"}
    assert second[-2]["role"] == "assistant" and second[-2]["content"][1]["type"] == "tool_use"
    # History replays as plain text only (no tool traces); system names the chemical.
    assert second[0] == {"role": "user", "content": "earlier q"}
    assert "Testol" in client.calls[0]["system"] and client.calls[0]["tools"] is tb.specs()
    # Answer, references resolved from the registry, the invented [S7] flagged.
    assert result["answer"].startswith("ALT BMD was 12.5")
    assert [r["token"] for r in result["references"]] == ["S1"]
    assert result["references"][0]["title"] == "CYP7A1 and bile acid synthesis"
    assert [i["token"] for i in result["unresolved_citations"]] == ["[S7]"]
    assert [t["tool"] for t in result["tool_trace"]] == ["run_sql", "kb_gene_evidence"]
    assert events == ["thinking", "tool_call", "tool_result", "tool_call", "tool_result", "thinking", "answer"]


@pytest.mark.asyncio
async def test_run_turn_bounds_tool_rounds(session_with_db, kb_path, monkeypatch):
    monkeypatch.setattr(agent, "MAX_TOOL_ROUNDS", 2)
    loop_forever = [("tool_use", [_block(type="tool_use", id=f"t{i}", name="list_tables", input={})]) for i in range(10)]
    client = _FakeClient(loop_forever)
    tb = ChatToolbox(session_with_db, SourceRegistry(), kb_path=kb_path)
    result = await agent.run_turn(history=[], user_message="q", toolbox=tb, client=client)
    assert result["rounds"] == 3 and "tool-call budget" in result["answer"]


# ---------------------------------------------------------------------------
# Store + routes
# ---------------------------------------------------------------------------

def test_chat_store_roundtrip_and_validation(sessions_dir):
    (sessions_dir / "DTXSID_ST").mkdir()
    t = chat_store.new_thread("DTXSID_ST")
    assert chat_store.list_threads("DTXSID_ST")[0]["id"] == t["id"]
    chat_store.append_turn(t, "first question?", {"answer": "a", "references": [], "unresolved_citations": [], "tool_trace": []}, [{"token": "S1", "paper_id": "pa", "title": "A"}])
    chat_store.save_thread("DTXSID_ST", t)
    back = chat_store.load_thread("DTXSID_ST", t["id"])
    assert back["title"] == "first question?" and len(back["messages"]) == 2 and back["sources"][0]["token"] == "S1"
    assert chat_store.load_thread("DTXSID_ST", "t0-nope") is None
    with pytest.raises(chat_store.InvalidThreadId):
        chat_store.load_thread("DTXSID_ST", "../x")
    assert chat_store.delete_thread("DTXSID_ST", t["id"]) and chat_store.list_threads("DTXSID_ST") == []


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    out = []
    for chunk in text.split("\n\n"):
        ev, data = None, ""
        for line in chunk.split("\n"):
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                data += line[5:].strip()
        if ev:
            out.append((ev, json.loads(data) if data else {}))
    return out


def test_chat_routes_stream_and_persist(client, session_with_db, monkeypatch):
    import web_routes.chat_routes as cr

    async def fake_run_turn(*, history, user_message, toolbox, chemical_name, model, emit):
        await emit("tool_call", {"tool": "run_sql", "input": {"sql": "SELECT 1"}})
        toolbox.registry.register({"paper_id": "pa", "title": "A"})
        return {"answer": f"Answer to {user_message} [S1]", "references": [{"token": "S1", "title": "A"}],
                "unresolved_citations": [], "tool_trace": [{"tool": "run_sql"}], "model_used": "m", "rounds": 1}

    monkeypatch.setattr(cr, "run_turn", fake_run_turn)
    d = session_with_db
    tid = client.post(f"/api/chat/{d}/threads", json={"title": ""}).json()["id"]
    assert client.get(f"/api/chat/{d}/threads").json()["threads"][0]["id"] == tid

    resp = client.post(f"/api/chat/{d}/threads/{tid}/messages", json={"message": "hello"})
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(resp.text)
    assert [e for e, _ in events] == ["tool_call", "complete"]
    assert events[-1][1]["answer"] == "Answer to hello [S1]" and events[-1][1]["thread_id"] == tid

    thread = client.get(f"/api/chat/{d}/threads/{tid}").json()
    assert [m["role"] for m in thread["messages"]] == ["user", "assistant"]
    assert thread["messages"][1]["references"][0]["token"] == "S1"
    assert thread["sources"][0]["token"] == "S1" and thread["title"] == "hello"

    assert client.post(f"/api/chat/{d}/threads/{tid}/messages", json={"message": ""}).status_code == 400
    assert client.post(f"/api/chat/{d}/threads/{tid}/messages", json={"message": "x" * 5000}).status_code == 400
    assert client.get(f"/api/chat/{d}/threads/../etc").status_code in (400, 404)
    assert client.get(f"/api/chat/{d}/threads/t0-missing").status_code == 404
    assert client.delete(f"/api/chat/{d}/threads/{tid}").json() == {"ok": True}


def test_chat_route_reports_agent_failure_as_error_event(client, session_with_db, monkeypatch):
    import web_routes.chat_routes as cr

    async def boom(**kw):
        raise RuntimeError("model down")

    monkeypatch.setattr(cr, "run_turn", boom)
    tid = client.post(f"/api/chat/{session_with_db}/threads").json()["id"]
    events = _parse_sse(client.post(f"/api/chat/{session_with_db}/threads/{tid}/messages", json={"message": "q"}).text)
    assert events == [("error", {"error": "chat failed: model down"})]
    assert client.get(f"/api/chat/{session_with_db}/threads/{tid}").json()["messages"] == []
