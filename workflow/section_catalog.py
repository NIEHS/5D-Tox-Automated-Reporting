"""
workflow.section_catalog — the workflow view of the document tree.

Rendering is tree-driven (Architectural Invariant #2): the ``DocNode`` tree owns
structure, ordering, numbering, and platform→section mapping. The *workflow* — what
can be generated, what unlocks what, what the Sections screen lists — historically
was NOT derived from the tree. It was hand-maintained in seven places
(``section_readiness._UNLOCK_RULES``/``_SINGLETON_KEYS``, ``session_routes``'
``VALID_SECTION_TYPES``/approve branches/``_resolve_section_key``/payload list/reset,
``store._BARE_SECTION_STEMS``) that agreed only by manual upkeep — see
``docs/plans/section-catalog-dependency-map.md``.

This module is the single derived catalog those registries were duplicating. It walks
a tree once and yields one ``SectionSpec`` per workflow unit:

  * the singleton content sections (``background``, ``methods``, ``summary``,
    ``bmd_summary``) — one node each;
  * the programmatic group narratives (``animal_condition``, ``clinical_pathology``,
    ``internal_dose``) — display-only status rows, no generate/approve;
  * the instance FAMILIES (``bm2``, ``genomics``) — the catalog names the family and
    its metadata; the concrete instances (``bm2_<slug>``, ``genomics_<organ>_<sex>``)
    stay disk-discovered because their keys are title-/data-derived, not tree-derived
    (``session_store.bm2_slug`` slugs the section title, and one bm2 file can span two
    platform ``table`` nodes).

Phase 1 wires the READ side only: ``section_readiness`` reads ``KIND_UNLOCK`` from
here (one unlock table, not two), and the engine seeds its readiness universe from the
catalog so a section present in the template appears in the workflow even before
anything is on disk (this is what finally gives ``internal_dose`` a row). The write
side (approve/payload/reset) still keys off literals — ``store``/``approvable`` are
declared here so that later phase is mechanical.

Lives in ``workflow/`` (not ``document_model/``) so it can read the tree AND consult
``workflow.content_origin`` without creating a ``document_model → workflow`` import
cycle (``document_model`` imports nothing from ``workflow``). The tree is read
strictly read-only.
"""

from __future__ import annotations

from dataclasses import dataclass

from document_model.document_node import DocNode
from workflow.content_origin import ContentOrigin, origin_for_section_type

# ── Unlock table (the single source; section_readiness imports this) ──────────
#
# Maps a workflow section TYPE / family to the unlock groups it requires (OR
# semantics; empty = no approval dependency, available as soon as its data exists).
# This is the ``_UNLOCK_RULES`` that used to live in section_readiness — moved here so
# the catalog and the readiness engine cannot drift. Group vocabulary:
#   ()                        always available (front matter / auto-derived)
#   ("processed",)            unlocked once the session is Processed (resource flag)
#   ("knowledge_base",)       unlocked once bmdx.duckdb is present (resource flag)
#   ("background","results")  unlocked on background approved OR ≥1 result approved
KIND_UNLOCK: dict[str, tuple[str, ...]] = {
    "background": (),
    "methods": ("processed",),
    "summary": ("background", "results"),
    "bmd_summary": (),
    "bm2": (),
    "genomics": ("knowledge_base",),
    # Programmatic group narratives — deterministic prose overlays, always available
    # once their data exists; display-only (not approvable).
    "animal_condition": (),
    "clinical_pathology": (),
    "internal_dose": (),
}


@dataclass(frozen=True)
class SectionSpec:
    """The workflow view of one document section (or instance family).

    ``key`` is a singleton section_key (``background``/``methods``/``summary``/
    ``bmd_summary``), a group-narrative key (``animal_condition``/
    ``clinical_pathology``/``internal_dose``), or a FAMILY name (``bm2``/
    ``genomics``) whose concrete instances are discovered on disk. ``store`` is the
    session-relative file pattern the key persists to (``{key}.json`` for singletons,
    a ``{...}`` pattern for families) — declared now for the later write-side phase.
    """

    key: str
    node_ids: tuple[str, ...]
    kind: str  # "llm" | "programmatic" | "derived" | "authored"
    approvable: bool
    unlock: tuple[str, ...]
    instance_of: str | None
    store: str


# Group narratives that render as prose overlays (narrative+tables nodes whose
# narrative_key is a programmatic group narrative). Their tables surface separately as
# bm2_* instances; these keys are the NARRATIVE, which had no workflow row before.
_GROUP_NARRATIVE_KEYS: frozenset[str] = frozenset(
    {"animal_condition", "clinical_pathology", "internal_dose"}
)

# data_key values that are front-matter / generated-list nodes with no workflow unit
# (title page, ToC, tables list, abstract, references, and the authored front-matter
# parts). Present in the tree, produced elsewhere — never a Sections-screen row.
_FRONT_MATTER_DATA_KEYS: frozenset[str] = frozenset(
    {
        "foreword",
        "about_report",
        "peer_review",
        "publication_details",
        "acknowledgments",
        "abstract",
        "references",
        "sample_counts",
    }
)


def _kind_for(key: str, family: str | None) -> str:
    """Classify a section's producer kind, reusing content_origin as the source.

    ``bmd_summary`` is auto-DERIVED (a deterministic reduction that also carries an
    LLM paragraph — one section, not two); group narratives are PROGRAMMATIC prose;
    everything else defers to ``content_origin`` (LLM vs programmatic), which is the
    existing single classifier keyed by the same vocabulary.
    """
    if key == "bmd_summary":
        return "derived"
    if key in _GROUP_NARRATIVE_KEYS:
        return "programmatic"
    origin = origin_for_section_type(family or key)
    if origin is ContentOrigin.PROGRAMMATIC:
        return "programmatic"
    return "llm"


def catalog_for_tree(tree: list[DocNode]) -> list[SectionSpec]:
    """Walk a DocNode forest and return its workflow catalog (document order).

    One spec per singleton content node, per programmatic group narrative, and per
    instance family present in the tree. Instance families are emitted once (not per
    instance) — concrete instances remain disk-discovered. Pure over the tree; no I/O.
    """
    from document_model.document_tree import walk_tree

    specs: list[SectionSpec] = []
    seen: set[str] = set()

    def add(key: str, node_id: str, *, family: str | None, approvable: bool) -> None:
        if key in seen:
            # Merge the additional feeding node into the existing spec (e.g. a
            # family spanning several platform table nodes, or genomics' two
            # narrative nodes sharing data_key genomics_sections).
            for i, s in enumerate(specs):
                if s.key == key:
                    specs[i] = SectionSpec(
                        key=s.key,
                        node_ids=s.node_ids + (node_id,),
                        kind=s.kind,
                        approvable=s.approvable,
                        unlock=s.unlock,
                        instance_of=s.instance_of,
                        store=s.store,
                    )
                    break
            return
        seen.add(key)
        kind = _kind_for(key, family)
        if family == "bm2":
            store = "bm2_{slug}.json"
        elif family == "genomics":
            store = "genomics_{organ}_{sex}.json"
        elif key in _GROUP_NARRATIVE_KEYS:
            store = ""  # rendered from the process overlay; no standalone file
        else:
            store = f"{key}.json"
        specs.append(
            SectionSpec(
                key=key,
                node_ids=(node_id,),
                kind=kind,
                approvable=approvable,
                unlock=KIND_UNLOCK.get(family or key, ()),
                instance_of=family,
                store=store,
            )
        )

    def visit(node: DocNode) -> None:
        nt = node.node_type
        # Genomics interpretation nodes → the genomics family.
        if nt == "genomics-section":
            add("genomics", node.id, family="genomics", approvable=False)
            return
        # Apical result tables (platform-bound) → the bm2 family. Two platform table
        # nodes (Body Weight, Organ Weight, …) collapse into one family spec; the
        # concrete bm2_<slug> instances are disk-discovered.
        if node.platform and nt in ("table", "incidence-table"):
            add("bm2", node.id, family="bm2", approvable=True)
            return
        # Programmatic group narratives (narrative+tables) → display-only rows.
        if nt == "narrative+tables" and node.narrative_key in _GROUP_NARRATIVE_KEYS:
            add(node.narrative_key, node.id, family=None, approvable=False)
            return
        # Singleton content sections, identified by their data_key.
        dk = node.data_key
        if not dk or dk in _FRONT_MATTER_DATA_KEYS:
            return
        if dk == "genomics_sections":
            # A genomics node without node_type genomics-section — still the family.
            add("genomics", node.id, family="genomics", approvable=False)
            return
        if dk in ("background", "methods", "summary", "bmd_summary"):
            add(dk, node.id, family=None, approvable=True)

    walk_tree(tree, visit)
    return specs


def approvable_section_types(tree: list[DocNode] | None = None) -> frozenset[str]:
    """The section TYPES a write route may accept (R2 `VALID_SECTION_TYPES`).

    A type is writable iff its catalog spec declares a `store` file — the four
    singletons plus the two instance families (as their bare family name). Group
    narratives (no store) and front-matter are excluded. Derived from the tree so
    the approve route's allowlist tracks the template.
    """
    from document_model.document_tree import DOCUMENT_TREE

    catalog = catalog_for_tree(tree if tree is not None else DOCUMENT_TREE)
    return frozenset(
        (s.instance_of or s.key) for s in catalog if s.store
    )


def singleton_section_files(tree: list[DocNode] | None = None) -> tuple[str, ...]:
    """The concrete section files for the SINGLETON sections (R4 payload / R5 reset).

    Only the singletons have a fixed filename (`{key}.json`); instance families use
    a `{...}` pattern and are handled by glob at the call sites. Document order.
    """
    from document_model.document_tree import DOCUMENT_TREE

    catalog = catalog_for_tree(tree if tree is not None else DOCUMENT_TREE)
    return tuple(
        s.store for s in catalog if s.instance_of is None and s.store
    )


def resolve_section_key(body: dict) -> tuple[str | None, str | None]:
    """Map a request body's section_type (+ extras) onto the on-disk section_key.

    The catalog-owned twin of session_routes._resolve_section_key (R3): singletons
    map to themselves; `bm2` needs `bm2_slug`; `genomics` needs `organ`/`sex`.
    Returns (section_key, error); exactly one is non-None.
    """
    section_type = body.get("section_type", "")
    approvable = approvable_section_types()
    if section_type not in approvable:
        return (None, f"Unknown section_type: {section_type}")
    if section_type == "bm2":
        slug = body.get("bm2_slug", "")
        if not slug:
            return (None, "bm2_slug is required for bm2 sections")
        return (f"bm2_{slug}", None)
    if section_type == "genomics":
        organ = body.get("organ", "").lower().replace(" ", "_")
        sex = body.get("sex", "").lower().replace(" ", "_")
        if not organ or not sex:
            return (None, "organ and sex are required for genomics sections")
        return (f"genomics_{organ}_{sex}", None)
    # A singleton type: its key IS the section_key.
    return (section_type, None)


def catalog_for_session(dtxsid: str | None = None) -> list[SectionSpec]:
    """Catalog for a session, resolving the per-session tree then the global one.

    Mirrors ``rendering.report_data.marshal_export_data``: a per-session structure
    override (``document_config.build_session_tree``) wins so a section removed in the
    configurator drops out of the workflow too; otherwise the global ``DOCUMENT_TREE``.
    """
    from document_model.document_tree import DOCUMENT_TREE

    tree: list[DocNode] | None = None
    if dtxsid:
        from document_model.document_config import build_session_tree

        # The per-session structure override is best-effort: an invalid id or a
        # malformed stored document.yaml degrades to the global template rather
        # than failing readiness derivation (the catalog is a READ concern).
        try:
            tree = build_session_tree(dtxsid)
        except Exception:
            tree = None
    return catalog_for_tree(tree if tree is not None else DOCUMENT_TREE)
