"""
ui_api.review — the review page: the report as the Bookshelf shows it, with
its sections beside it (the demo path, docs/ui-redesign/modules/demo/spec.md
§4 S5).

One read, ``review(dtxsid)``, for a report or a single study; asked of a
study of a report, it answers for the report and says which study was asked
for (the book is the report's). It serves:

  * the book: its address on the Bookshelf and whether it can be shown, with
    the reason when it cannot (ui_api.studies: a report is on the shelf once
    every study it covers was processed); and the Word and PDF downloads;
  * the sections, grouped by the session that owns them, in the order the
    report prints them: a report over several studies owns what no study's
    data changes (the front matter, the Background: the catalog's
    ``data_dependent``); each study owns the rest. Every row is the read
    model's row (ui_api.read_model.sections_state: its state and the
    ``accept`` verdict), with the owner, a title, who writes it, and
    ``anchor``;
  * the publish readiness of the report and of each study, as the read model
    serves it;
  * whether the section acts are offered at all: not on the finished side of
    a demo pair (ui_api.demo), where the answer names the live copy.

**The anchor** is the id of the element in the Bookshelf page where the
section starts, or None. It is derived, never guessed:

  1. the tree the page is rendered from is built the way the render builds it
     (``document_model.document_tree.study_tree``: a section repeated per
     study or per tissue becomes one copy each, its id suffixed with the
     study's key and the tissue), from what a read can know without loading
     the report's data: the studies' keys (studies.json), the tissues of the
     gene-level interpretations, and the data domains the result sections
     cover;
  2. a section's node is found in that tree: a singleton's by the catalog; a
     results table's by its data domain (the section file's ``platform``); a
     gene-level interpretation's by its tissue. In a report over several
     studies a study's section is the copy scoped to that study when there is
     one, else the part the studies share;
  3. the element's id is what the BITS emitter gives that node
     (rendering.bits_book, rendering.jats_generator: ``fm-`` a front-matter
     part, ``bp-`` a body part, ``sec-`` a section, ``T-`` a table), which the
     Bookshelf page keeps.

A section with no node in the tree (the Abstract, which the book holds in its
metadata; a results section the report prints no table for) has no anchor.
The page checks the element exists before it scrolls, so a tree the render
pruned further than this read can know is said, not hidden.

Reading has no side effects (the read model's read-only store).
"""

from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

# The groups of the API page (web_routes/api_guide.yaml) this page belongs to.
API_GROUPS = ("review", "report")

REPORT_TITLE = "The report"

# Who writes a section, by the catalog's kind, in plain words.
_WRITER_SAY = {
    "llm": "Written by a language model.",
    "programmatic": "Built from the study's data by the program.",
    "derived": ("Built from the study's results by the program; paragraphs that interpret "
                "them, where the section has any, are written by a language model."),
    "authored": "Supplied or standard text; the application does not write it.",
}
_WRITER_SAY_DEFAULT = "The application does not say who writes this part."

_TABLE_TYPES = frozenset({"table", "incidence-table", "sample-counts-table", "data-table",
                          "authored-table"})
_SEC_TYPES = frozenset({"heading-only", "bmd-summary", "genomics-section"})
_NARRATIVE_TYPES = frozenset({"narrative", "narrative+tables"})


# ---------------------------------------------------------------------------
# The tree the Bookshelf page is rendered from, and a node's element id
# ---------------------------------------------------------------------------

def element_id(node, top_level: bool) -> str | None:
    """The id of the element the BITS emitter writes for ``node`` (and the
    Bookshelf page keeps), None when it writes none of its own.

    A top-level node is a part of the book (rendering.bits_book._part): a
    front-matter part, a body part, an appendix. Any other node goes through
    the shared block emitters (rendering.jats_generator._DISPATCH): a titled
    section, a table, a figure. An untitled narrative is no section of its
    own; the Abstract is held in the book's metadata."""
    from rendering.jats_generator import table_wrap_id

    if top_level:
        element = getattr(node, "element", None)
        if element in ("foreword", "front-matter-part"):
            return f"fm-{node.id}"
        if element == "book-part":
            return f"bp-{node.id}"
        if element == "ack":
            return f"ack-{node.id}"
        if element not in ("book-app", "app", "sec"):
            return None
    kind = node.node_type
    if kind == "appendix":
        return f"app-{node.id}"
    if kind in _TABLE_TYPES:
        return table_wrap_id(node.id)
    if kind == "figure":
        return f"fig-{node.id}"
    if kind in _SEC_TYPES:
        return f"sec-{node.id}"
    if kind in _NARRATIVE_TYPES and (node.title or getattr(node, "sec_label", None)):
        return f"sec-{node.id}"
    return None


def _organ_of(key: str) -> str | None:
    """The tissue of a gene-level interpretation's key (genomics_<organ>_<sex>)."""
    rest = key.removeprefix("genomics_")
    organ = rest.rsplit("_", 1)[0] if "_" in rest else ""
    return organ or None


def _same_organ(scope: str | None, organ: str) -> bool:
    return bool(scope) and scope.strip().lower().replace(" ", "_") == organ


class _Book:
    """The tree the Bookshelf page is rendered from, as far as a read can
    know it, with each node's position in the document's order."""

    def __init__(self, tree, study_keys: list[str], organs: list[str], platforms: set[str]):
        from document_model.document_tree import study_tree
        from pipeline.deposit import SPECIES_TITLES

        facts = {
            # As rendering.report_compose names the studies of a report.
            "studies": [{"key": k, "title": SPECIES_TITLES.get(k, k.title()), "data": {}}
                        for k in study_keys],
            "genomics_sections": [{"organ": o.replace("_", " ")} for o in organs],
        }
        collected = set(platforms)
        if organs:
            collected.add("gene_expression")
        self.several = bool(study_keys)
        self.nodes = study_tree(tree, collected or None, None, facts)
        self.order: list = []          # every node, in document order
        self.top: set[int] = {id(n) for n in self.nodes}
        self.parent: dict[int, object] = {}
        self._walk(self.nodes, None)
        self.position = {id(n): i for i, n in enumerate(self.order)}

    def _walk(self, nodes, parent) -> None:
        for node in nodes:
            self.order.append(node)
            if parent is not None:
                self.parent[id(node)] = parent
            self._walk(node.children or [], node)

    def anchor(self, node) -> str | None:
        return element_id(node, id(node) in self.top)

    def _pick(self, nodes: list, study: str | None):
        """Of a section's nodes, the one where it starts for ``study`` (None:
        the report itself, or a single study): the first copy scoped to the
        study, else the first part no study is scoped to."""
        nodes = [n for n in nodes if self.anchor(n)]
        if study is not None:
            own = [n for n in nodes if getattr(n, "scope_species", None) == study]
            if own:
                return own[0]
        shared = [n for n in nodes if getattr(n, "scope_species", None) is None]
        return shared[0] if shared else None

    def singleton(self, key: str, study: str | None):
        from workflow.section_catalog import catalog_for_tree
        if not hasattr(self, "_specs"):
            self._specs = {s.key: s for s in catalog_for_tree(self.nodes)}
        spec = self._specs.get(key)
        if spec is None:
            return None
        ids = set(spec.node_ids)
        return self._pick([n for n in self.order if n.id in ids], study)

    def table(self, platform: str | None, study: str | None):
        if not platform:
            return None
        return self._pick([n for n in self.order if n.platform == platform
                           and n.node_type in ("table", "incidence-table")], study)

    def interpretation(self, organ: str | None, study: str | None):
        if not organ:
            return None
        return self._pick([n for n in self.order
                           if _same_organ(getattr(n, "scope_organ", None), organ)
                           and self._in_genomics(n)], study)

    def _in_genomics(self, node) -> bool:
        while node is not None:
            if node.node_type == "genomics-section":
                return True
            node = self.parent.get(id(node))
        return False

    def heading_over(self, node) -> str | None:
        """The title of the heading ``node`` is printed under, when it is
        written out (a title with a field the study's facts fill is not: this
        read does not load those facts)."""
        parent = self.parent.get(id(node))
        title = (getattr(parent, "title", None) or "").strip()
        return title if title and "${" not in title else None


# ---------------------------------------------------------------------------
# The rows
# ---------------------------------------------------------------------------

def _key_in_words(key: str) -> str:
    return key.replace("_", " ").replace("-", " ").strip().capitalize()


def _row(row: dict, owner: str, study: str | None, section: dict | None,
         book: _Book | None, untitled: dict[str, object]) -> tuple[dict, int | None]:
    """A read-model row as the review page shows it, and its node's position
    in the document (None when it has no node)."""
    from ui_api.writing import interpretation_title

    key, family = row["key"], row.get("instance_of")
    node = None
    if book is not None:
        if family == "bm2":
            node = book.table((section or {}).get("platform"), study)
        elif family == "genomics":
            node = book.interpretation(_organ_of(key), study)
        else:
            node = book.singleton(key, study)
    title = row.get("title")
    if not title and family == "genomics":
        organ, sex = _organ_of(key), key.rsplit("_", 1)[-1]
        title = interpretation_title(organ or key, sex)
    if not title and key in untitled and book is not None:
        # A section printed without a heading of its own (a study's part of
        # "Clinical Pathology"): the heading it is printed under.
        title = book.heading_over(untitled[key])
    out = {**row, "owner": owner, "title": title or _key_in_words(key),
           "writer_say": _WRITER_SAY.get(row.get("kind"), _WRITER_SAY_DEFAULT),
           "anchor": book.anchor(node) if (book is not None and node is not None) else None}
    return out, (book.position[id(node)] if (book is not None and node is not None) else None)


def _in_document_order(rows: list[tuple[dict, int | None]]) -> list[dict]:
    """The rows by where each starts in the book; a row with no place there
    keeps its place in the catalog's order, after the row before it."""
    placed, last = [], -1.0
    for i, (row, position) in enumerate(rows):
        last = float(position) if position is not None else last + 1e-6 * (i + 1)
        placed.append((last, i, row))
    return [row for _, _, row in sorted(placed, key=lambda t: (t[0], t[1]))]


def _group(owner: str, key: str | None, title: str, rows: list[dict], belongs,
           sections: dict[str, dict], book: _Book | None, untitled: dict, engine) -> dict:
    from ui_api.read_model import publish_readiness_state
    shown = [_row(r, owner, key, sections.get(r["key"]), book, untitled)
             for r in rows if belongs(r)]
    return {"owner": owner, "key": key, "title": title, "exists": True,
            "publish": publish_readiness_state(engine),
            "sections": _in_document_order(shown)}


# ---------------------------------------------------------------------------
# The read
# ---------------------------------------------------------------------------

def api_page_links() -> list[dict]:
    """Where this step is on the API page (/docs): its groups, by the
    numbered titles the page prints."""
    from urllib.parse import quote
    from web_routes import api_guide
    guide = api_guide.load_guide()
    numbered = guide.numbered()
    titles = {g.key: g.title for g in guide.groups}
    return [{"group": key, "title": titles[key], "href": f"/docs#/{quote(numbered[key])}"}
            for key in API_GROUPS if key in numbered]


def _acts(asked: str) -> dict:
    """Whether the section acts are offered on this session at all: not on
    the finished side of a demo pair, where ``counterpart`` is the session of
    the live copy that corresponds to the one asked for."""
    from ui_api.demo import pair_of, require_not_reference
    from ui_api.refusals import explain

    try:
        require_not_reference(asked)
    except Exception as exc:  # noqa: BLE001 — shown as the reason, in plain words
        pair = pair_of(asked) or {}
        return {"allowed": False, "say": explain(exc)["error"]["say"],
                "counterpart": pair.get("counterpart")}
    return {"allowed": True, "say": None, "counterpart": None}


def _book_answer(report: str, kind: str, relations: dict) -> tuple[dict, list[dict]]:
    """The book's address and whether it can be shown (with the reason), and
    the downloads, which exist when the book does."""
    from ui_api.studies import _bookshelf

    shelf = _bookshelf(report, kind, relations)
    shown = bool(shelf["on_shelf"])
    book = {"shown": shown, "url": shelf["url"] if shown else None, "say": shelf["say"]}
    downloads = [] if not shown else [
        {"format": "docx", "title": "Word document", "url": f"/Bookshelf/{report}/report.docx",
         "filename": f"{report}-report.docx"},
        {"format": "pdf", "title": "PDF", "url": f"/Bookshelf/{report}/report.pdf",
         "filename": f"{report}-report.pdf"},
    ]
    return book, downloads


def _study_title(key: str) -> str:
    return f"{key.replace('_', ' ').replace('-', ' ').capitalize()} study"


def review(dtxsid: str) -> dict:
    """The review page's read (the module docstring). ``study_not_found``
    for a session that does not exist; a malformed id is ``invalid_study_id``."""
    from ui_api.read_model import (ReadOnlyDiskPoolStore, _rendering_catalog, sections_state)
    from ui_api.studies import StudyRefusal, session_exists, session_kind
    from workflow.engine import WorkflowEngine

    if not session_exists(dtxsid):
        raise StudyRefusal("study_not_found", f"no session {dtxsid}", 404, {"id": dtxsid})
    asked_kind = session_kind(dtxsid)
    asked = None
    report = dtxsid
    if asked_kind["kind"] == "member" and asked_kind["relations"]["parent"]:
        report = asked_kind["relations"]["parent"]
    kind = asked_kind if report == dtxsid else session_kind(report)
    members = [(m["key"], m["id"]) for m in kind["relations"]["members"]]
    if report != dtxsid:
        key = next((k for k, m in members if m == dtxsid), None)
        asked = {"id": dtxsid, "key": key,
                 "say": (f"This study is part of the report {report}. The book is the "
                         "report's, so the page shows the whole report; this study's "
                         "sections are opened first.")}

    store = ReadOnlyDiskPoolStore()
    catalog, tree, tree_error = _rendering_catalog(report)
    specs = {s.key: s for s in catalog}

    def spec_of(row: dict):
        return specs.get(row.get("instance_of") or row["key"])

    def states(sid: str) -> tuple[list[dict], dict[str, dict], WorkflowEngine]:
        engine = WorkflowEngine(sid, store)
        rows = sections_state(sid, engine, store, store.session_dir(sid), catalog, tree)
        return rows, store.read_section_dicts(sid), engine

    # What each session holds, read once.
    held: dict[str, tuple] = {report: states(report)}
    for _, member in members:
        if session_exists(member):
            held[member] = states(member)

    # The tree the book is rendered from (the anchors), from what was read.
    book = None
    untitled: dict[str, object] = {}
    if tree is not None:
        organs, platforms = [], set()
        for rows, sections, _ in held.values():
            for r in rows:
                organ = _organ_of(r["key"]) if r.get("instance_of") == "genomics" else None
                if organ and organ not in organs:
                    organs.append(organ)
            platforms |= {s["platform"] for k, s in sections.items()
                          if k.startswith("bm2_") and isinstance(s.get("platform"), str)}
        try:
            book = _Book(tree, [k for k, _ in members], organs, platforms)
        except Exception as exc:  # noqa: BLE001 — no anchors, and the answer says so
            logger.warning("The review of %s has no anchors: %s", report, exc)
            tree_error = tree_error or _explained(exc)
    if book is not None and tree is not None:
        # The sections the definition prints without a heading of their own
        # (a study's part of "Clinical Pathology"): each with its first copy
        # in the book, whose heading stands in for its title.
        from document_model.document_tree import walk_tree
        written: dict[str, str] = {}
        walk_tree(tree, lambda n: written.setdefault(n.id, (n.title or "").strip()))
        copies: dict[str, object] = {}
        for node in book.order:
            copies.setdefault(node.id.split("--", 1)[0], node)
        for spec in catalog:
            first = spec.node_ids[0] if spec.node_ids else None
            if spec.instance_of is None and first in copies and not written.get(first):
                untitled[spec.key] = copies[first]

    groups: list[dict] = []
    rows, sections, engine = held[report]
    if members:
        groups.append(_group(
            report, None, REPORT_TITLE, rows,
            lambda r: not getattr(spec_of(r), "data_dependent", True),
            sections, book, untitled, engine))
        for key, member in members:
            if member not in held:
                groups.append({"owner": member, "key": key, "title": _study_title(key),
                               "exists": False, "publish": None, "sections": [],
                               "say": f"The study {member} does not exist."})
                continue
            rows, sections, engine = held[member]
            groups.append(_group(
                member, key, _study_title(key), rows,
                lambda r: getattr(spec_of(r), "data_dependent", True),
                sections, book, untitled, engine))
    else:
        groups.append(_group(report, None, REPORT_TITLE, rows, lambda r: True,
                             sections, book, untitled, engine))

    shelf, downloads = _book_answer(report, kind["kind"], kind["relations"])
    out: dict = {
        "id": dtxsid, "kind": asked_kind["kind"],
        "report": {"id": report, "kind": kind["kind"]},
        "asked": asked,
        "book": shelf, "downloads": downloads,
        "acts": _acts(dtxsid),
        "groups": groups,
        "api_page": api_page_links(),
    }
    if tree_error is not None:
        # The report's definition could not be built: the sections still
        # list, in the workflow's own order, and none can be scrolled to.
        out["anchors_error"] = tree_error
    return out


def _explained(exc: BaseException) -> dict:
    from ui_api.refusals import explain
    return explain(exc)["error"]

