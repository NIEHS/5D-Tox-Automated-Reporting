"""The API page (/docs) is drawn from a declared guide (web_routes/api_guide).

The page is where the study team looks for what the software does at a step,
what it reads and where the code is.  These tests keep the guide and the
server from drifting apart: every operation is named, every entry answers to
a route, every core function named exists, every notebook step named is a
heading of the notebook, and the wording follows the rules for team-facing
text (nobody addressed directly; American spelling).
"""

import json
import re
from pathlib import Path

import pytest

from web_routes import api_guide

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def app():
    from web_routes.background_server import app
    return app


@pytest.fixture(scope="module")
def guide():
    return api_guide.load_guide()


@pytest.fixture(scope="module")
def schema(app):
    return api_guide.guided_schema(app)


def test_every_operation_is_named_in_the_guide(app, guide):
    named = guide.operations()
    missing = sorted(f"{m} {p}" for (m, p) in api_guide.handlers(app)
                     if (m, p) not in named and not guide.is_not_described(p))
    assert not missing, (
        "operations without an entry in web_routes/api_guide*.yaml "
        f"(give each a group and a plain title): {missing}")


def test_every_entry_answers_to_a_route(app, guide):
    served = api_guide.handlers(app)
    stale = sorted(f"{m} {p}" for (m, p) in guide.operations() if (m, p) not in served)
    assert not stale, f"guide entries no route answers: {stale}"


def test_the_code_each_entry_names_exists(guide):
    for op in guide.operations().values():
        for name in op.code:
            try:
                api_guide.resolve_symbol(name)
            except (ImportError, AttributeError) as e:
                pytest.fail(f"{op.method} {op.path} names {name}, which does not exist ({e})")


def test_the_notebook_steps_named_are_headings_of_the_notebook(guide):
    nb = json.loads((REPO / api_guide.NOTEBOOK).read_text(encoding="utf-8"))
    headings = {re.sub(r"^#+\s*", "", line).strip()
                for cell in nb["cells"] if cell["cell_type"] == "markdown"
                for line in "".join(cell["source"]).splitlines() if line.startswith("#")}
    wrong = sorted({op.notebook for op in guide.operations().values()
                    if op.notebook and op.notebook not in headings})
    assert not wrong, f"not headings of {api_guide.NOTEBOOK}: {wrong}"


def _texts(guide):
    yield "intro", guide.intro
    for nd in guide.not_described:
        yield nd.get("prefix") or nd["path"], nd.get("why", "")
    for g in guide.groups:
        yield g.key, f"{g.title} {g.about}"
        for op in g.operations:
            yield f"{op.method} {op.path}", " ".join((op.title, op.does, op.reads, op.writes))


SECOND_PERSON = re.compile(r"\b(you|your|yours|yourself)\b", re.I)
BRITISH = re.compile(
    r"\b(\w*colour\w*|\w*behaviour\w*|\w*favour\w*|\w*(?:organi|summari|recogni|normali|"
    r"categori|standardi|materiali|optimi|minimi|customi|finali|initiali|visuali|prioriti|"
    r"harmoni|utili|characteri|speciali|generali|synchroni|authori|digiti|randomi)"
    r"s(?:e[ds]?|ing|ation\w*)|analyse[ds]?|emphasise[ds]?|modell(?:ed|ing)|labell(?:ed|ing)|"
    r"cent(?:re|red)|programme|licence|catalogue[ds]?|grey)\b", re.I)


def test_the_wording_addresses_nobody_and_is_american(guide):
    problems = []
    for where, text in _texts(guide):
        if m := SECOND_PERSON.search(text):
            problems.append(f"{where}: addresses the reader ({m.group(0)!r})")
        if m := BRITISH.search(text):
            problems.append(f"{where}: British spelling ({m.group(0)!r})")
    assert not problems, problems


def test_the_page_lists_the_workflow_in_order(schema, guide):
    tags = [t["name"] for t in schema["tags"]]
    assert tags[:4] == ["1. Study files", "2. Combined data: one dataset from all the files",
                        "3. Study facts the report states",
                        "4. Process: statistics, benchmark doses, tables and figures"]
    assert tags[-1] == "Not described on this page"
    # One group for every operation, and no operation left with FastAPI's
    # title from the function's name.
    for path, item in schema["paths"].items():
        for method, spec in item.items():
            assert len(spec["tags"]) == 1 and spec["tags"][0] in tags, (method, path)
            if not guide.is_not_described(path):
                assert not spec["summary"].startswith("Api "), (method, path)


def test_an_operation_says_what_it_does_and_where_its_code_is(schema):
    spec = schema["paths"]["/api/pool/integrate/{dtxsid}"]["post"]
    assert spec["summary"] == "Combine the files into one dataset"
    text = spec["description"]
    assert "**Changes what is saved.**" in text
    assert "**Writes:** `integrated.json` (the dataset)" in text
    assert '**In the notebook:** step "8. Integrate"' in text
    assert "the work is done by `workflow.steps.integrate_step`" in text
    assert re.search(r"`api_pool_integrate` in `web_routes/pool_routes.py` \(line \d+\)", text)
    assert "Technical notes" in text and "Merge all pool files" in text
    # The route is FastAPI's own: its parameters and operation id are kept.
    assert [p["name"] for p in spec["parameters"]] == ["dtxsid"]
    assert spec["operationId"].startswith("api_pool_integrate")
    # What FastAPI prints under every operation and says nothing is dropped.
    assert list(spec["responses"]) == ["200"] and "content" not in spec["responses"]["200"]

    reads = schema["paths"]["/api/workflow/{dtxsid}/state"]["get"]["description"]
    assert "**Reads only:** nothing that is saved is changed." in reads
    render = schema["paths"]["/api/prompts/{section}/render"]["post"]["description"]
    assert "**Reads only:**" in render  # a POST that saves nothing says so


def test_a_groups_operations_follow_the_guides_order(schema, guide):
    """Swagger UI lists a group's operations in schema order."""
    in_schema = [(m.upper(), p) for p, item in schema["paths"].items() for m in item]
    for group in guide.groups:
        want = [(op.method, op.path) for op in group.operations]
        got = [k for k in in_schema if k in set(want)]
        # Two methods of one path stay together, so compare each path's first place.
        first = lambda keys: list(dict.fromkeys(p for _, p in keys))  # noqa: E731
        assert first(got) == first(want), group.key


def test_an_example_study_fills_the_study_field(app, monkeypatch):
    monkeypatch.setenv("BMDX_DOCS_EXAMPLE_STUDY", "DTXSID6020430")
    spec = api_guide.guided_schema(app)["paths"]["/api/workflow/{dtxsid}/state"]["get"]
    assert spec["parameters"][0]["example"] == "DTXSID6020430"


def test_a_guide_that_names_an_operation_twice_is_refused(tmp_path):
    one = tmp_path / "api_guide.yaml"
    one.write_text("groups:\n  - key: a\n    order: 1\n    title: A\n    operations:\n"
                   "      - {op: GET /x, title: X}\n")
    two = tmp_path / "api_guide_more.yaml"
    two.write_text("groups:\n  - key: a\n    operations:\n      - {op: GET /y, title: Y}\n"
                   "  - key: b\n    order: 0\n    title: B\n    operations:\n"
                   "      - {op: GET /x, title: again}\n")
    with pytest.raises(api_guide.GuideError, match="GET /x is already in api_guide.yaml"):
        api_guide.load_guide([one, two])
    two.write_text("groups:\n  - key: a\n    operations:\n      - {op: GET /y, title: Y}\n"
                   "  - key: b\n    order: 0\n    title: B\n")
    merged = api_guide.load_guide([one, two])
    assert [g.key for g in merged.groups] == ["b", "a"]
    assert [op.path for op in merged.groups[1].operations] == ["/x", "/y"]
    assert merged.numbered() == {"b": "1. B", "a": "2. A"}
