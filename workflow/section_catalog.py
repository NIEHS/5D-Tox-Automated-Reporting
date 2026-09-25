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
    # Authored/boilerplate front-matter content sections — display-only status rows.
    # Boilerplate (foreword/peer_review/publication_details/acknowledgments) is always
    # populated from the render scaffold; about_report is human-set (front_matter.json,
    # empty until authored); abstract is study-specific. None gate on approval — they
    # are always "available", the row just reflects filled-vs-pending.
    "foreword": (),
    "about_report": (),
    "peer_review": (),
    "publication_details": (),
    "acknowledgments": (),
    "abstract": (),
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
    # Whether a DATA reprocess (new/corrected study files) can invalidate this
    # section's content. False for sections generated from the chemical identity
    # alone (Background) and for authored front matter — a reprocess does not change
    # their inputs, so staling/demoting them (Phase 3a) would demand a re-bless of
    # prose that could not have changed. Consulted by workflow.reprocess.
    data_dependent: bool = True
    region: str | None = None  # "front" | "body" | None — the DocNode region the
    # section lives in; lets the workflow UI group front-matter rows separately.


# Group narratives that render as prose overlays (narrative+tables nodes whose
# narrative_key is a programmatic group narrative). Their tables surface separately as
# bm2_* instances; these keys are the NARRATIVE, which had no workflow row before.
_GROUP_NARRATIVE_KEYS: frozenset[str] = frozenset(
    {"animal_condition", "clinical_pathology", "internal_dose"}
)

# AUTHORED / boilerplate front-matter CONTENT sections — these DO get a display-only
# workflow row (their content can be pending: About This Report is empty until authored,
# the abstract until processed). Kept out of the singleton branch below and emitted via
# their own visit clause so they are display-only (approvable=False), not authored-
# approvable like background/methods.
_FRONT_MATTER_CONTENT_DATA_KEYS: frozenset[str] = frozenset(
    {
        "foreword",
        "about_report",
        "peer_review",
        "publication_details",
        "acknowledgments",
        "abstract",
    }
)

# data_key values that are auto-generated LIST nodes with no workflow unit (the ToC's
# tables list, the references list, sample counts). Present in the tree, produced
# entirely by a tree walk — never a Sections-screen row.
_FRONT_MATTER_DATA_KEYS: frozenset[str] = frozenset(
    {
        "references",
        "sample_counts",
    }
)


# Sections whose inputs are the chemical IDENTITY, not the study data: a data
# reprocess leaves them untouched. Background is generated from the identity
# (regulatory lookups + literature) and api_pool_reset deliberately preserves it
# for the same reason.
_IDENTITY_ONLY_KEYS: frozenset[str] = frozenset({"background"})


def _data_dependent_for(key: str, kind: str) -> bool:
    """Does a data reprocess invalidate this section? (See SectionSpec.data_dependent.)"""
    if key in _IDENTITY_ONLY_KEYS:
        return False
    if kind == "authored":
        return False
    return True


def is_data_dependent(section_key: str, tree: list[DocNode] | None = None) -> bool:
    """Catalog lookup for workflow.reprocess: instance keys (bm2_*, genomics_*)
    resolve through their family spec; unknown keys default to True (fail-safe —
    an unknown section is treated as data-derived and staled)."""
    from document_model.document_tree import DOCUMENT_TREE

    family = (
        "bm2" if section_key.startswith("bm2_")
        else "genomics" if section_key.startswith("genomics_")
        else section_key
    )
    for spec in catalog_for_tree(tree if tree is not None else DOCUMENT_TREE):
        if spec.key == family:
            return spec.data_dependent
    return True


def _kind_for(key: str, family: str | None) -> str:
    """FALLBACK classification of a section's producer kind, for nodes that carry
    no declared ``binding`` (hand-built DocNodes in tests / legacy scaffolds).

    Since ADR-0025 phase 5 the kind IS the node's ``binding`` — declared on the
    template entry or defaulted from its preset by the instantiator — and this
    inference is consulted only when that is absent.  It reuses content_origin:
    ``bmd_summary`` is auto-DERIVED (a deterministic reduction that also carries an
    LLM paragraph — one section, not two); group narratives are PROGRAMMATIC prose;
    everything else defers to ``content_origin`` (LLM vs programmatic), which is the
    existing single classifier keyed by the same vocabulary.
    """
    if key == "bmd_summary":
        return "derived"
    if key in _GROUP_NARRATIVE_KEYS:
        return "programmatic"
    if key in _FRONT_MATTER_CONTENT_DATA_KEYS:
        # Front-matter content is authored/boilerplate (scaffold text + human-set
        # front_matter.json), not model-generated — classify as "authored" so the UI
        # neither offers a generate button nor mislabels it as an LLM section.
        return "authored"
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

    def add(
        key: str, node_id: str, *, family: str | None, approvable: bool,
        region: str | None = None, binding: str | None = None,
    ) -> None:
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
                        data_dependent=s.data_dependent,
                        region=s.region,
                    )
                    break
            return
        seen.add(key)
        # ADR-0025 phase 5: the declared binding on the (first) feeding node is
        # the producer kind.  `container` says nothing about who produces the
        # content (a heading that merely carries the section's data_key, like
        # Materials and Methods), so it — like an absent binding on a node built
        # without a template — falls back to the content_origin inference.
        kind = binding if binding and binding != "container" else _kind_for(key, family)
        if family == "bm2":
            store = "bm2_{slug}.json"
        elif family == "genomics":
            store = "genomics_{organ}_{sex}.json"
        elif key in _GROUP_NARRATIVE_KEYS or key in _FRONT_MATTER_CONTENT_DATA_KEYS:
            store = ""  # rendered from the scaffold/overlay; no standalone section file
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
                data_dependent=_data_dependent_for(key, kind),
                region=region,
            )
        )

    def visit(node: DocNode) -> None:
        nt = node.node_type
        # Genomics interpretation nodes → the genomics family.
        if nt == "genomics-section":
            add("genomics", node.id, family="genomics", approvable=False,
                binding=node.binding)
            return
        # Apical result tables (platform-bound) → the bm2 family. Two platform table
        # nodes (Body Weight, Organ Weight, …) collapse into one family spec; the
        # concrete bm2_<slug> instances are disk-discovered.
        if node.platform and nt in ("table", "incidence-table"):
            add("bm2", node.id, family="bm2", approvable=True, binding=node.binding)
            return
        # Programmatic group narratives (narrative+tables) → display-only rows.
        if nt == "narrative+tables" and node.narrative_key in _GROUP_NARRATIVE_KEYS:
            add(node.narrative_key, node.id, family=None, approvable=False,
                region=node.region, binding=node.binding)
            return
        # Singleton content sections, identified by their data_key.
        dk = node.data_key
        if not dk or dk in _FRONT_MATTER_DATA_KEYS:
            return
        # Authored/boilerplate front-matter content → display-only rows (region-tagged
        # so the UI groups them apart from body sections). Not approvable: the app is
        # not an editor (ADR-0018); the row just reflects filled-vs-pending.
        if dk in _FRONT_MATTER_CONTENT_DATA_KEYS:
            add(dk, node.id, family=None, approvable=False, region=node.region,
                binding=node.binding)
            return
        if dk == "genomics_sections":
            # A genomics node without node_type genomics-section — still the family.
            add("genomics", node.id, family="genomics", approvable=False,
                binding=node.binding)
            return
        if dk in ("background", "methods", "summary", "bmd_summary"):
            add(dk, node.id, family=None, approvable=True, region=node.region,
                binding=node.binding)

    walk_tree(tree, visit)
    return specs


# Memo for approvable_section_types(): {id(tree): (tree, result)} — single entry,
# invalidated by identity (see the function body).
_APPROVABLE_CACHE: dict[int, tuple[object, frozenset]] = {}


def approvable_section_types(tree: list[DocNode] | None = None) -> frozenset[str]:
    """The section TYPES a write route may accept (R2 `VALID_SECTION_TYPES`).

    A type is writable iff its catalog spec declares a `store` file — the four
    singletons plus the two instance families (as their bare family name). Group
    narratives (no store) and front-matter are excluded. Derived from the tree so
    the approve route's allowlist tracks the template.
    """
    from document_model.document_tree import DOCUMENT_TREE

    if tree is None:
        # The global tree is rebuilt as a NEW list on template reload, so its
        # identity is a valid cache key; a constant result per tree object means
        # one walk per template load, not one per approve/save request.
        tree = DOCUMENT_TREE
        cached = _APPROVABLE_CACHE.get(id(tree))
        if cached is not None and cached[0] is tree:
            return cached[1]
        result = frozenset(
            (s.instance_of or s.key) for s in catalog_for_tree(tree) if s.store
        )
        _APPROVABLE_CACHE.clear()
        _APPROVABLE_CACHE[id(tree)] = (tree, result)
        return result
    catalog = catalog_for_tree(tree)
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


def resolve_section_key(
    body: dict, approvable: "frozenset[str] | None" = None,
) -> tuple[str | None, str | None]:
    """Map a request body's section_type (+ extras) onto the on-disk section_key.

    The catalog-owned twin of session_routes._resolve_section_key (R3): singletons
    map to themselves; `bm2` needs `bm2_slug`; `genomics` needs `organ`/`sex`.
    Returns (section_key, error); exactly one is non-None.
    """
    section_type = body.get("section_type", "")
    # Callers that already computed the allowlist (the approve route validates
    # the type before resolving the key) pass it in — one tree walk per request.
    if approvable is None:
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
