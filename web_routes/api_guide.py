"""
web_routes/api_guide.py — the API page (/docs), arranged for a reader who is
not a programmer.

FastAPI builds the page from the routes: one flat list in the order the routes
were registered, each titled from its function's name ("Api Workflow State")
and described by a docstring written for the next programmer.  That page is
also where a study team looks when it asks "what does the software do at this
step, what does it read, and where is the code" — so this module rewrites the
schema the page is drawn from, out of a declared guide:

  * ``api_guide*.yaml`` (beside this file) names every operation once: its
    group (a step of the workflow, in workflow order), a plain title, and for
    the steps a reader follows, what it does, what it reads, what it writes,
    the notebook step that runs the same thing, and the core function that
    does the work;
  * the handler's file, function and line are read from the route itself, so
    they cannot go out of date;
  * the docstring is kept, under "Technical notes".

Nothing about a route changes: paths, parameters and operation ids are
FastAPI's (two things it prints under every operation are dropped from the
page: the generic "Validation Error" answer and the empty example).  A branch that adds routes adds its own ``api_guide_<x>.yaml``
(a group of its own, or operations for an existing group).  The tests
(tests/unit/test_api_guide.py) refuse an operation the guide does not name, a
guide entry no route answers, a core function that does not exist and a
notebook step the notebook does not have.
"""

from __future__ import annotations

import importlib
import inspect
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
NOTEBOOK = "notebooks/workflow_walkthrough.ipynb"
_METHODS = ("get", "post", "put", "patch", "delete")

# How Swagger UI draws the page: every group closed (the page opens as a list
# of the workflow's steps), no "Schemas" block of internal type names at the
# foot, and no request timing.
SWAGGER_UI = {
    "docExpansion": "none",
    "defaultModelsExpandDepth": -1,
    "displayRequestDuration": False,
}

_FALLBACK_TITLE = "Not described on this page"


@dataclass(frozen=True)
class Operation:
    method: str                 # "GET"
    path: str                   # "/api/pool/validate/{dtxsid}"
    group: str                  # the group's key
    title: str
    does: str = ""
    reads: str = ""
    writes: str = ""
    code: tuple[str, ...] = ()  # dotted names of the core functions
    notebook: str = ""          # a heading of the notebook: "8. Integrate"
    changes: bool = True        # False: a request that is not a GET, and saves nothing

    @property
    def reads_only(self) -> bool:
        return self.method == "GET" or not self.changes


@dataclass
class Group:
    key: str
    order: int
    title: str
    about: str
    operations: list[Operation] = field(default_factory=list)


@dataclass
class Guide:
    intro: str
    groups: list[Group]                       # in page order
    not_described: list[dict]                 # [{prefix | path, why}]

    def operations(self) -> dict[tuple[str, str], Operation]:
        return {(op.method, op.path): op for g in self.groups for op in g.operations}

    def numbered(self) -> dict[str, str]:
        """Group key → the title the page shows ("4. Process: …")."""
        return {g.key: f"{i}. {g.title}" for i, g in enumerate(self.groups, 1)}

    def why_not_described(self, path: str) -> str | None:
        """The reason the guide gives for leaving ``path`` out (a ``path`` it
        names exactly, or one under a ``prefix``), or None when it gives none."""
        for nd in self.not_described:
            if path == nd.get("path") or (nd.get("prefix") and path.startswith(nd["prefix"])):
                return _one_line(nd.get("why")) or "Not part of the workflow this page describes."
        return None

    def is_not_described(self, path: str) -> bool:
        return self.why_not_described(path) is not None


class GuideError(ValueError):
    """The guide files contradict themselves (a duplicate, a group without a
    title, an entry without a title)."""


def guide_files() -> list[Path]:
    return sorted(_HERE.glob("api_guide*.yaml"))


def _one_line(text) -> str:
    return " ".join(str(text or "").split())


def load_guide(files: list[Path] | None = None) -> Guide:
    """The guide of every ``api_guide*.yaml``, merged: a later file may add a
    group, or operations to a group an earlier file declared."""
    intro, groups, not_described = "", {}, []
    seen: dict[tuple[str, str], str] = {}
    for path in files if files is not None else guide_files():
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        intro = doc.get("intro") or intro
        not_described += doc.get("not_described") or []
        for g in doc.get("groups") or []:
            key = g["key"]
            group = groups.get(key)
            if group is None:
                if not g.get("title") or "order" not in g:
                    raise GuideError(f"{path.name}: group {key!r} needs a title and an order")
                group = groups[key] = Group(key, int(g["order"]), _one_line(g["title"]),
                                            _one_line(g.get("about")))
            for entry in g.get("operations") or []:
                method, _, route = str(entry.get("op", "")).partition(" ")
                op_key = (method.upper(), route.strip())
                if not route or not entry.get("title"):
                    raise GuideError(f"{path.name}: {entry!r} needs an op and a title")
                if op_key in seen:
                    raise GuideError(f"{path.name}: {entry['op']} is already in {seen[op_key]}")
                seen[op_key] = path.name
                code = entry.get("code") or ()
                group.operations.append(Operation(
                    method=op_key[0], path=op_key[1], group=key,
                    title=_one_line(entry["title"]), does=_one_line(entry.get("does")),
                    reads=_one_line(entry.get("reads")), writes=_one_line(entry.get("writes")),
                    code=tuple([code] if isinstance(code, str) else code),
                    notebook=_one_line(entry.get("notebook")),
                    changes=bool(entry.get("changes", True))))
    return Guide(intro=intro.strip(), groups=sorted(groups.values(), key=lambda g: g.order),
                 not_described=not_described)


def resolve_symbol(dotted: str):
    """The object a dotted name of the guide's ``code`` names
    ("workflow.engine.WorkflowEngine.state"), or ImportError/AttributeError."""
    parts = dotted.split(".")
    for cut in range(len(parts), 0, -1):
        try:
            obj = importlib.import_module(".".join(parts[:cut]))
        except ModuleNotFoundError:
            continue
        for name in parts[cut:]:
            obj = getattr(obj, name)
        return obj
    raise ImportError(dotted)


def handlers(app) -> dict[tuple[str, str], object]:
    """(METHOD, path) → the function that answers it, for every operation the
    page lists."""
    out = {}
    for route in app.routes:
        if isinstance(route, APIRoute) and route.include_in_schema:
            for method in route.methods - {"HEAD", "OPTIONS"}:
                out[(method, route.path)] = route.endpoint
    return out


def _handler_location(endpoint) -> str:
    """"`api_pool_integrate` in `web_routes/pool_routes.py` (line 272)"."""
    fn = inspect.unwrap(endpoint)
    try:
        file = Path(inspect.getsourcefile(fn) or "").resolve().relative_to(_REPO)
        line = inspect.getsourcelines(fn)[1]
    except (OSError, TypeError, ValueError):
        return f"`{fn.__name__}`"
    return f"`{fn.__name__}` in `{file}` (line {line})"


def _description(op: Operation | None, endpoint, why_not: str = "") -> str:
    parts = []
    if op is None:
        parts.append(why_not or "This operation has no entry in the guide yet.")
    else:
        if op.does:
            parts.append(op.does)
        parts.append("**Reads only:** nothing that is saved is changed." if op.reads_only
                     else "**Changes what is saved.**")
        if op.reads:
            parts.append(f"**Reads:** {op.reads}")
        if op.writes:
            parts.append(f"**Writes:** {op.writes}")
        if op.notebook:
            parts.append(f"**In the notebook:** step \"{op.notebook}\" of `{NOTEBOOK}` "
                         "runs the same thing, with the code in view.")
    where = f"the request is answered by {_handler_location(endpoint)}" if endpoint else ""
    if op is not None and op.code:
        names = ", ".join(f"`{name}`" for name in op.code)
        parts.append(f"**Where the code is:** the work is done by {names}; {where}.")
    elif where:
        parts.append(f"**Where the code is:** {where}.")
    notes = inspect.getdoc(inspect.unwrap(endpoint)) if endpoint else None
    if notes and (op is not None or not why_not):
        parts.append("<details><summary>Technical notes (the programmer's own "
                     f"description)</summary>\n\n```text\n{notes}\n```\n\n</details>")
    return "\n\n".join(parts)


def _plain_responses(spec: dict) -> None:
    """Drop what FastAPI lists under every operation and tells a reader
    nothing: the "Validation Error" answer (the same for all), and the example
    of an answer whose shape the route does not declare (shown as "string")."""
    responses = spec.get("responses") or {}
    invalid = responses.get("422") or {}
    ref = (((invalid.get("content") or {}).get("application/json") or {}).get("schema") or {})
    if ref.get("$ref", "").endswith("/HTTPValidationError"):
        del responses["422"]
    for response in responses.values():
        if response.get("content") == {"application/json": {"schema": {}}}:
            del response["content"]


def guided_schema(app, guide: Guide | None = None) -> dict:
    """The OpenAPI schema of ``app`` with the guide applied: groups in workflow
    order, each operation under its plain title with its description."""
    guide = guide or load_guide()
    schema = get_openapi(title=app.title, version=app.version,
                         description=guide.intro or app.description, routes=app.routes)
    by_key, titles, endpoints = guide.operations(), guide.numbered(), handlers(app)
    example = os.environ.get("BMDX_DOCS_EXAMPLE_STUDY", "").strip()

    position = {key: i for i, key in enumerate(by_key)}
    paths = schema.get("paths") or {}
    fallback_used = False
    for path, item in paths.items():
        for method in _METHODS:
            spec = item.get(method)
            if spec is None:
                continue
            key = (method.upper(), path)
            op = by_key.get(key)
            if op is None:
                fallback_used = True
                why = guide.why_not_described(path) or ""
                spec["tags"] = [_FALLBACK_TITLE]
                spec["description"] = _description(None, endpoints.get(key), why)
            else:
                spec["tags"] = [titles[op.group]]
                spec["summary"] = op.title
                spec["description"] = _description(op, endpoints.get(key))
            _plain_responses(spec)
            if example:
                for param in spec.get("parameters") or []:
                    if param.get("in") == "path" and param.get("name") == "dtxsid":
                        param["example"] = example

    # Swagger UI lists a group's operations in the order the schema holds
    # them: the guide's order, with what the guide does not name at the end.
    def rank(path: str) -> int:
        return min((position.get((m.upper(), path), len(position))
                    for m in _METHODS if m in paths[path]), default=len(position))

    ordered = {}
    for path in sorted(paths, key=rank):
        item = paths[path]
        first = sorted((m for m in _METHODS if m in item),
                       key=lambda m: position.get((m.upper(), path), len(position)))
        ordered[path] = {**{m: item[m] for m in first},
                         **{k: v for k, v in item.items() if k not in first}}
    schema["paths"] = ordered

    schema["tags"] = [{"name": titles[g.key], "description": g.about} for g in guide.groups]
    if fallback_used:
        schema["tags"].append({"name": _FALLBACK_TITLE,
                               "description": "Operations this guide does not describe."})
    return schema


def install(app) -> None:
    """Make ``app`` serve the guided schema (built once, on the first request
    for it, when every route is registered)."""
    def openapi() -> dict:
        if app.openapi_schema is None:
            app.openapi_schema = guided_schema(app)
        return app.openapi_schema

    app.openapi = openapi
    app.swagger_ui_parameters = {**(app.swagger_ui_parameters or {}), **SWAGGER_UI}
