"""
document_template.py — load a data-driven document template and instantiate it
into the canonical DocNode tree (ADR-0003, Phase 2).

A *template* is data (a YAML file under templates/): an ordered, nested
selection of component types from the catalog (render_capabilities).  This
module turns that data into the runtime DocNode tree the renderers and the
navigation panel consume.  So the document structure is now AUTHORED as data
and the in-memory tree is the OUTPUT of instantiating it — invariant #2 (the
tree drives all structure) is preserved; only the tree's *source* moved from a
hand-written Python literal to a template the instantiator reproduces.

Three things the template does NOT carry, because they are computed:

  - level — derived as `0 if the type is headingless else nesting depth`,
    using the catalog's `headingless` flag.
  - table_number — positional, assigned later by the numbering pre-pass
    (compute_table_numbers).
  - figure_number — reserved positional field; there is no DocNode-level
    figure-numbering pass yet (genomics chart figure numbers are assigned on
    the chart payloads by genomics_charts.attach_genomics_charts), so it stays
    None on the tree today.

Single source of truth for the node shape
------------------------------------------
The set of fields a template node may bind is DERIVED from the DocNode
dataclass (document_node.DocNode) — see `_BINDING_FIELDS` — rather than
re-listed here.  Adding a field to DocNode therefore cannot silently diverge
from what the instantiator forwards or what the validator accepts.

Import graph (no cycle): document_node (a leaf module) ← document_template ←
document_tree; document_template also reads the catalog (render_capabilities).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from dataclasses import fields
from pathlib import Path

import yaml

from document_model.document_node import DocNode
from document_model.content_item import ContentItem
from styling_export.freeform_content import VALID_REPRESENTATIONS, resolve_freeform
from document_model.render_capabilities import (
    COMPONENT_CATALOG,
    CONTENT_KINDS,
    capabilities_for,
    is_allowed_child,
    is_captionable,
    is_headingless,
    required_bindings_for,
)


# ---------------------------------------------------------------------------
# Constants — derived from the DocNode shape so they cannot drift
# ---------------------------------------------------------------------------

# Where authored templates live.  One file per template; YAML is the authoring
# format (comments, readability), JSON is the canonical comparison form used by
# the golden-tree test.
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

# DocNode fields the instantiator computes or handles specially, so a template
# must NOT bind them by name:
#   level, table_number, figure_number — computed
#   node_type — bound via the template's `type` key (the one renamed field)
#   children  — recursion, not a scalar binding
#   region    — set by the top-level region container (ADR-0004 amendment d),
#               inherited by descendants — never authored on a node entry.
#   resolved_content — computed by _instantiate_node from the authored
#               content/content_file/representation (freeform nodes); never
#               authored.
_COMPUTED_OR_SPECIAL = frozenset(
    {"level", "node_type", "children", "content_items", "table_number",
     "figure_number", "region", "resolved_content"}
)

# The freeform component types whose content is AUTHORED (in the template or an
# external file) rather than read from the pipeline data dict.  Their content
# bindings get a dedicated validation branch + a resolve step at instantiation.
_FREEFORM_TYPES = frozenset({"freeform-page", "freeform-block"})

# Node types that may carry a `subtype`.  For cover/title-page it selects the
# branded cover layout (see cover_layouts); for `figure` it is the pictorial KIND
# (render_capabilities.FIGURE_SUBTYPES: chart | logo — ADR-0012).  A subtype on
# any other type is a template authoring error.
_SUBTYPABLE_TYPES = frozenset({"cover", "title-page", "figure"})

# Valid region names — project directly to BITS <front-matter> / <book-body> /
# <book-back> on a future BITS export (ADR-0004 amendment d).
_VALID_REGIONS: tuple[str, ...] = ("front", "body", "back")
_REGION_CONTAINER_KEYS = frozenset({"region", "children"})

# The scalar binding fields a template node supplies BY THE SAME NAME as the
# DocNode field (id, title, data_key, platform, narrative_key, ready_key,
# methods_key).  DERIVED from DocNode so there is ONE source of truth: add a
# (non-computed) field to DocNode and it becomes forwardable automatically,
# with no risk of the validator and the constructor disagreeing.
_BINDING_FIELDS = tuple(
    f.name for f in fields(DocNode) if f.name not in _COMPUTED_OR_SPECIAL
)

# Every key a template node entry may carry: the binding fields plus `type`
# (→ node_type), `children` (recursion), and `content_items` (ADR-0003 Part B
# ordered sub-addressable items).  Anything else is an authoring mistake (a typo,
# a stale field) and is rejected loudly.
_KNOWN_KEYS = frozenset(_BINDING_FIELDS) | {"type", "children", "content_items"}

# Keys every node entry must supply regardless of type.
_REQUIRED_KEYS = ("id", "type", "title")


# ---------------------------------------------------------------------------
# Helper / validation functions (private)
# ---------------------------------------------------------------------------

def _validate_entry(entry: dict, parent_type: str | None) -> None:
    """
    Reject a malformed template entry before it becomes a broken tree node.

    Checks, in order: it's a mapping; it has the required keys; it has no
    unknown keys; its type exists in the catalog; the catalog's containment
    grammar permits this type under its parent; and every binding the type
    REQUIRES (e.g. a `table` needs a `platform`) is present and non-empty.
    """
    if not isinstance(entry, dict):
        raise ValueError(
            f"template node must be a mapping, got {type(entry).__name__}: {entry!r}"
        )

    node_id = entry.get("id", "<no-id>")

    missing = [k for k in _REQUIRED_KEYS if k not in entry]
    if missing:
        raise ValueError(f"template node {node_id!r} is missing required key(s): {missing}")

    unknown = set(entry) - _KNOWN_KEYS
    if unknown:
        raise ValueError(f"template node {node_id!r} has unknown key(s): {sorted(unknown)}")

    node_type = entry["type"]
    if node_type not in COMPONENT_CATALOG:
        raise ValueError(
            f"template node {node_id!r} uses type {node_type!r}, which is not in the catalog"
        )

    # Containment grammar: a child's type must be an allowed child of its
    # parent's type.  Top-level nodes have no parent and are not checked here.
    if parent_type is not None and not is_allowed_child(parent_type, node_type):
        raise ValueError(
            f"template node {node_id!r}: type {node_type!r} is not an allowed child "
            f"of parent type {parent_type!r}"
        )

    # Required bindings: a type may declare wiring it cannot render without
    # (e.g. a `table` must name a `platform`).  Catch the omission HERE, at
    # load time, instead of as a silently-empty section at render time.
    for binding in required_bindings_for(node_type):
        value = entry.get(binding)
        if value is None or value == "":
            raise ValueError(
                f"template node {node_id!r} of type {node_type!r} is missing "
                f"required binding {binding!r}"
            )

    # Layout settings are gated on the type's capability (ADR-0003 Amendment 1):
    # orientation may only be authored on an orientable type, and only as
    # portrait/landscape.  A bad hand-edit fails loudly at load time.
    orientation = entry.get("orientation")
    if orientation is not None:
        if orientation not in ("portrait", "landscape"):
            raise ValueError(
                f"template node {node_id!r}: orientation must be 'portrait' or "
                f"'landscape', got {orientation!r}"
            )
        if not capabilities_for(node_type).orientable:
            raise ValueError(
                f"template node {node_id!r}: orientation set but type "
                f"{node_type!r} is not orientable"
            )

    # Captions are gated on the type's captionable flag (ADR-0004 amendment a):
    # caption only on table-like types (BITS <table-wrap>/<fig>); a section
    # carries only <title>.  Empty/None captions are simply absent.
    if entry.get("caption") and not is_captionable(node_type):
        raise ValueError(
            f"template node {node_id!r}: caption set but type "
            f"{node_type!r} is not captionable"
        )

    # Freeform authored-content bindings (freeform-page / freeform-block).
    if node_type in _FREEFORM_TYPES:
        _validate_freeform_entry(entry, node_id)
    elif any(entry.get(k) for k in ("content", "content_file", "representation")):
        # content/content_file/representation only mean something on freeform
        # types; flag a stray binding on any other type rather than silently
        # ignoring it.
        raise ValueError(
            f"template node {node_id!r} of type {node_type!r}: "
            f"content/content_file/representation are only valid on "
            f"{sorted(_FREEFORM_TYPES)}"
        )

    # `subtype` (which branded cover layout) is only meaningful on cover /
    # title-page; flag a stray subtype on any other type (same discipline as the
    # freeform bindings above) rather than silently ignoring it.
    if entry.get("subtype") and node_type not in _SUBTYPABLE_TYPES:
        raise ValueError(
            f"template node {node_id!r} of type {node_type!r}: "
            f"subtype is only valid on {sorted(_SUBTYPABLE_TYPES)}"
        )

    # ADR-0003 Part B: validate an authored content_items list (if any).
    if entry.get("content_items"):
        _validate_content_items(entry["content_items"], node_id)


def _validate_content_items(items, node_id: str) -> None:
    """Validate a node's authored content_items list (ADR-0003 Part B).

    Loud, load-time checks mirroring _validate_entry's discipline: the list is a
    list of mappings; each item has `id` + `kind`; no unknown keys; `kind` is in
    CONTENT_KINDS; content source is exactly one of `text` xor `data_key`;
    `orientation` (if set) is portrait/landscape; and item ids are UNIQUE WITHIN
    the component (not global — the composite "<node>::<item>" key is what is
    addressed, so cross-component reuse is legitimate and must NOT be indexed
    globally)."""
    if not isinstance(items, list):
        raise ValueError(
            f"template node {node_id!r}: content_items must be a list, "
            f"got {type(items).__name__}"
        )
    seen: set[str] = set()
    for i, item in enumerate(items):
        where = f"template node {node_id!r} content_items[{i}]"
        if not isinstance(item, dict):
            raise ValueError(f"{where}: each item must be a mapping, got {type(item).__name__}")
        unknown = set(item) - _CONTENT_ITEM_KEYS
        if unknown:
            raise ValueError(f"{where}: unknown key(s) {sorted(unknown)}")
        item_id = item.get("id")
        if not item_id:
            raise ValueError(f"{where}: missing required 'id'")
        kind = item.get("kind")
        if kind not in CONTENT_KINDS:
            raise ValueError(
                f"{where} (id={item_id!r}): kind {kind!r} is not a content kind "
                f"(known: {sorted(CONTENT_KINDS)})"
            )
        # Content source: exactly one of inline `text` or a `data_key` pointer.
        has_text = item.get("text") is not None
        has_data_key = bool(item.get("data_key"))
        if has_text and has_data_key:
            raise ValueError(f"{where} (id={item_id!r}): set only one of 'text' or 'data_key'")
        orientation = item.get("orientation")
        if orientation is not None and orientation not in ("portrait", "landscape"):
            raise ValueError(
                f"{where} (id={item_id!r}): orientation must be 'portrait' or "
                f"'landscape', got {orientation!r}"
            )
        if item_id in seen:
            raise ValueError(
                f"{where}: duplicate content-item id {item_id!r} within node "
                f"{node_id!r} (item ids must be unique within a component)"
            )
        seen.add(item_id)


def _validate_freeform_entry(entry: dict, node_id: str) -> None:
    """
    Validate the authored-content bindings of a freeform node.

    Rules:
      - `content` may be an inline string OR a dual-source mapping
        ({latex, html}); `content_file` is an external path OR a dual-source
        mapping of paths ({latex, html}).
      - exactly ONE source: `content` xor `content_file`.
      - a dual-source mapping (inline OR file) needs no `representation`;
        otherwise `representation` ∈ {latex, html, docx} is REQUIRED.
      - `representation: docx` MUST use a single-path `content_file`.
    """
    content = entry.get("content")
    content_file = entry.get("content_file")
    representation = entry.get("representation")

    is_dual_content = isinstance(content, dict)
    is_dual_file = isinstance(content_file, dict)
    has_inline = content is not None
    has_file = content_file is not None and content_file != ""

    if has_inline and has_file:
        raise ValueError(
            f"freeform node {node_id!r}: set exactly one of `content` / "
            f"`content_file`, not both"
        )
    if not has_inline and not has_file:
        raise ValueError(
            f"freeform node {node_id!r}: requires `content` or `content_file`"
        )

    if is_dual_content or is_dual_file:
        # A dual-source mapping (inline strings OR file paths) carries its own
        # per-surface source; a representation is meaningless (and a
        # `latex`/`html` key must exist).
        mapping = content if is_dual_content else content_file
        which = "content" if is_dual_content else "content_file"
        if not ({"latex", "html"} & set(mapping)):
            raise ValueError(
                f"freeform node {node_id!r}: dual-source `{which}` mapping must "
                f"have a `latex` and/or `html` key"
            )
        if representation is not None:
            raise ValueError(
                f"freeform node {node_id!r}: `representation` is not allowed with "
                f"a dual-source `{which}` mapping"
            )
        return

    # Single-source: representation is required and must be valid.
    if not representation:
        raise ValueError(
            f"freeform node {node_id!r}: `representation` is required "
            f"(one of {sorted(VALID_REPRESENTATIONS)})"
        )
    if representation not in VALID_REPRESENTATIONS:
        raise ValueError(
            f"freeform node {node_id!r}: `representation` must be one of "
            f"{sorted(VALID_REPRESENTATIONS)}, got {representation!r}"
        )
    if representation == "docx" and not has_file:
        raise ValueError(
            f"freeform node {node_id!r}: representation 'docx' requires "
            f"`content_file` (a .docx path)"
        )


def _validate_region_container(entry: dict) -> None:
    """
    Validate a top-level region container ({region: ..., children: [...]}) —
    ADR-0004 amendment d.  Caller has already confirmed `region` is a key.
    """
    extra = set(entry) - _REGION_CONTAINER_KEYS
    if extra:
        raise ValueError(f"region container has unknown key(s): {sorted(extra)}")
    region = entry["region"]
    if region not in _VALID_REGIONS:
        raise ValueError(
            f"region must be one of {list(_VALID_REGIONS)}, got {region!r}"
        )
    children = entry.get("children", [])
    if not isinstance(children, list):
        raise ValueError("region container 'children' must be a list")


# The keys a content_item entry may carry (ADR-0003 Part B).  Mirrors the
# ContentItem dataclass fields; an unknown key is a loud authoring error, same
# discipline as _KNOWN_KEYS for nodes.
_CONTENT_ITEM_KEYS = frozenset({
    "id", "kind", "part", "orientable", "breakable", "orientation",
    "break_before", "break_after", "text", "data_key", "caption",
})


def _instantiate_content_item(item: dict) -> ContentItem:
    """Build one ContentItem from a validated template entry (ADR-0003 Part B).

    Validation (kind membership, text-xor-data_key, id-uniqueness) has already
    run in _validate_content_items; this only constructs.  Absent optional keys
    take the ContentItem dataclass defaults.
    """
    return ContentItem(
        id=item["id"],
        kind=item["kind"],
        part=item.get("part"),
        orientable=bool(item.get("orientable", False)),
        breakable=bool(item.get("breakable", False)),
        orientation=item.get("orientation"),
        break_before=bool(item.get("break_before", False)),
        break_after=bool(item.get("break_after", False)),
        text=item.get("text"),
        data_key=item.get("data_key"),
        caption=item.get("caption"),
    )


def _instantiate_node(
    entry: dict,
    depth: int,
    parent_type: str | None,
    region: str | None,
) -> DocNode:
    """
    Instantiate a single node entry, recursing into its children.  `region`
    is the book region inherited from the top-level region container (ADR-0004
    amendment d); descendants share it.  `depth` (1 at the top) drives level
    derivation; `parent_type` drives containment validation.
    """
    _validate_entry(entry, parent_type)
    node_type = entry["type"]
    # level is derived, never authored: headingless types (cover, title page,
    # bare data tables) are level 0; everything else takes its nesting depth.
    level = 0 if is_headingless(node_type) else depth
    children = [
        _instantiate_node(c, depth + 1, node_type, region)
        for c in entry.get("children", [])
    ]
    # ADR-0003 Part B: an ordered list of sub-addressable content items the
    # component owns.  Built like `children` (a special, non-scalar-binding key);
    # empty for every current node (none author content_items yet).
    content_items = [_instantiate_content_item(ci) for ci in entry.get("content_items", [])]
    # Forward every binding field by name; an absent optional field becomes
    # None (DocNode's default), exactly matching the old hand-written literal.
    bindings = {name: entry.get(name) for name in _BINDING_FIELDS}
    node = DocNode(
        node_type=node_type, level=level, children=children,
        content_items=content_items, region=region, **bindings
    )
    # Freeform nodes carry AUTHORED content; resolve it to per-surface markup
    # ONCE here (a docx file is parsed a single time) and store it on the node so
    # both renderers just read node.resolved_content.  Validation has already
    # confirmed the source fields are well-formed.
    if node_type in _FREEFORM_TYPES:
        node.resolved_content = resolve_freeform(
            node.content, node.content_file, node.representation,
            base_dir=TEMPLATES_DIR,
        )
    return node


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _load_raw(name: str):
    """Parse a template YAML file by name; return the raw deserialized value
    (a list for legacy scaffolds, or a mapping with a ``document:`` key for the
    full config).  Raises FileNotFoundError if absent."""
    path = TEMPLATES_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"no template named {name!r} at {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_template(name: str) -> list[dict]:
    """
    Load a template by name (without extension) from TEMPLATES_DIR.

    Returns the raw list of node-entry dicts (the *document* structure).  The
    file may be EITHER:

      - a bare YAML list of node entries (legacy scaffolds, unit-test fixtures), or
      - a mapping with a ``document:`` key holding that list, alongside optional
        sibling blocks (``chart_style``, ``chart_types``) read by
        :func:`load_chart_style` / :func:`load_chart_types`.

    Either way this returns the document LIST, so ``instantiate``, ``build_tree``,
    and the golden-tree test are unaffected by the sibling blocks.  Raises
    ValueError if the shape is neither.
    """
    data = _load_raw(name)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "document" in data:
        doc = data["document"]
        if not isinstance(doc, list):
            raise ValueError(
                f"template {name!r}: 'document' must be a list of node entries, "
                f"got {type(doc).__name__}"
            )
        return doc
    raise ValueError(
        f"template {name!r} must be a YAML list of node entries, or a mapping "
        f"with a 'document' key, got {type(data).__name__}"
    )


def load_chart_style(name: str) -> dict:
    """
    Load the ``chart_style`` block from a template (the three-layer style config
    consumed by chart_style.resolve_chart_style).  Returns ``{}`` when the file
    is a bare list or has no ``chart_style`` key — so the no-config render path
    (built-in defaults only) is unchanged.

    Validates SHAPE only (loudly): ``chart_style`` must be a mapping whose
    ``defaults``/``types``/``instances`` sub-blocks, when present, are mappings.
    Unknown *style keys* are not fatal here — they are reported per-instance at
    render time (genomics_viz logs chart_style.unknown_style_keys).
    """
    data = _load_raw(name)
    if not isinstance(data, dict):
        return {}
    cfg = data.get("chart_style")
    if cfg is None:
        return {}
    if not isinstance(cfg, dict):
        raise ValueError(
            f"template {name!r}: 'chart_style' must be a mapping, "
            f"got {type(cfg).__name__}"
        )
    for sub in ("defaults", "types", "instances"):
        if sub in cfg and not isinstance(cfg[sub], dict):
            raise ValueError(
                f"template {name!r}: chart_style.{sub} must be a mapping, "
                f"got {type(cfg[sub]).__name__}"
            )
    return cfg


def load_chart_types(name: str):
    """
    Load the ``chart_types`` block and build the effective chart-type registry.

    Returns ``chart_registry.build_registry(raw)`` — the built-in code types
    (umap, cluster) merged with the data-driven types declared in the template.
    Each declared spec is validated LOUDLY by build_registry (a name colliding
    with a code type, a non-mapping spec, or a missing trace/x/y raises).  A bare
    list or a missing ``chart_types`` key yields just the built-ins (today's
    behaviour).
    """
    import genomics.chart_registry as chart_registry

    data = _load_raw(name)
    raw = data.get("chart_types") if isinstance(data, dict) else None
    if raw is not None and not isinstance(raw, dict):
        raise ValueError(
            f"template {name!r}: 'chart_types' must be a mapping of "
            f"name → spec, got {type(raw).__name__}"
        )
    return chart_registry.build_registry(raw)


def load_layout_style(name: str) -> dict:
    """
    Load the ``styles`` block from a template (the per-content-type font & flow
    config consumed by layout_style.resolve_layout_style).  Returns ``{}`` when
    the file is a bare list or has no ``styles`` key — so the no-config render
    path (each renderer's built-in look) is unchanged.

    Validates loudly at load time — this is stricter than load_chart_style
    because a bad style would corrupt the .tex compile / the CSS, not just log a
    warning:
      - ``styles`` is a mapping whose ``defaults``/``types``/``instances`` sub-
        blocks, when present, are mappings;
      - every ``styles.types`` key names a real catalog content type (a typo like
        ``narrtive`` would silently never match, so reject it);
      - every style leaf VALUE on a KNOWN key is acceptable
        (layout_style.validate_style: enum / length / color / number / bool).
    Unknown style KEYS stay non-fatal (reported at render time via
    layout_style.unknown_layout_keys), mirroring chart_style's discipline.
    """
    import document_model.layout_style as layout_style

    data = _load_raw(name)
    if not isinstance(data, dict):
        return {}
    cfg = data.get("styles")
    if cfg is None:
        return {}
    if not isinstance(cfg, dict):
        raise ValueError(
            f"template {name!r}: 'styles' must be a mapping, "
            f"got {type(cfg).__name__}"
        )
    for sub in ("defaults", "types", "instances", "title_page"):
        if sub in cfg and not isinstance(cfg[sub], dict):
            raise ValueError(
                f"template {name!r}: styles.{sub} must be a mapping, "
                f"got {type(cfg[sub]).__name__}"
            )
    # types keys must be real content types (a typo would silently never match).
    for node_type in (cfg.get("types") or {}):
        if node_type not in COMPONENT_CATALOG:
            raise ValueError(
                f"template {name!r}: styles.types.{node_type!r} is not a catalog "
                f"content type"
            )
    # title_page keys are ROLES from a closed set (a typo would silently never match).
    for role in (cfg.get("title_page") or {}):
        if role not in layout_style.TITLE_PAGE_ROLES:
            raise ValueError(
                f"template {name!r}: styles.title_page.{role!r} is not a "
                f"title-page role (known: {sorted(layout_style.TITLE_PAGE_ROLES)})"
            )
    # Value-check every style dict across all layers.
    layers: list[tuple[str, dict]] = []
    if isinstance(cfg.get("defaults"), dict):
        layers.append(("defaults", cfg["defaults"]))
    for k, v in (cfg.get("types") or {}).items():
        if isinstance(v, dict):
            layers.append((f"types.{k}", v))
    for k, v in (cfg.get("instances") or {}).items():
        if isinstance(v, dict):
            layers.append((f"instances.{k}", v))
    for k, v in (cfg.get("title_page") or {}).items():
        if isinstance(v, dict):
            layers.append((f"title_page.{k}", v))
    for where, style in layers:
        errors = layout_style.validate_style(style)
        if errors:
            raise ValueError(
                f"template {name!r}: styles.{where} has invalid value(s): "
                f"{'; '.join(errors)}"
            )
    return cfg


# The content AREAS an organ allowlist may scope — the only two places organ is
# a row/section axis (genomics sections; the organ-weight apical table).  A
# closed vocabulary so a typo'd area key (e.g. `genomic:`) fails loudly at load
# rather than silently filtering nothing.
REPORT_ORGAN_AREAS: frozenset[str] = frozenset({"genomics", "organ-weight"})

# Sex is a row/column axis in several places: the apical tables (a "Male"/
# "Female" key in every table_data), the genomics sections (one entry per
# organ×sex), and the Organ Weight table specifically (the reference's Table 3
# shows only the sex that had a responsive organ — e.g. "Liver Weights of Male
# Rats").  `apical` narrows EVERY apical table's sexes uniformly; `organ-weight`
# narrows ONLY the organ-weight table, so the reference can drop female from
# Table 3 while keeping both sexes in Tables 2/4/5/6.
REPORT_SEX_AREAS: frozenset[str] = frozenset({"apical", "genomics", "organ-weight"})

# Assays (individual clinical-pathology endpoints) are filterable for the
# multi-endpoint apical platforms.  The reference's "Select" tables (4/5/6) show
# a hand-curated per-sex subset that responsiveness alone does not reproduce, so
# each is driven by an explicit per-sex allowlist.
REPORT_ASSAY_AREAS: frozenset[str] = frozenset(
    {"clinical-chemistry", "hematology", "hormones"}
)


def _load_per_area_block(
    name: str, key: str, valid_areas: frozenset[str], area_noun: str | None = None
) -> dict[str, list[str]]:
    """
    Load a per-area ALLOWLIST block (a sibling of ``document``) — the shared
    loader behind ``organs:``, ``sex:`` and ``assays:``.

    The block is a MAPPING keyed by content area; each value a list of tokens:

        <key>:
          <area>: [token, ...]

    Returns ``{area: [tokens]}`` with each token lower-cased and stripped (the
    canonical match form, since the underlying strings are inconsistently cased
    across the pipeline).  An OMITTED area key (or an empty list) means NO
    filtering for that area; a missing block, or a file that is a bare list,
    means no filtering anywhere — ``{}`` (backward compatible).

    Validates SHAPE loudly:
      - the block must be a MAPPING (a bare list is the rejected flat shape);
      - each key must be one of ``valid_areas``;
      - each value must be a list of strings.

    ``area_noun`` is the word used in the "unknown ... area" error (defaults to
    the block ``key``); the organ loader passes "organ" to keep its historical
    wording stable.
    """
    noun = area_noun or key
    data = _load_raw(name)
    if not isinstance(data, dict):
        return {}
    raw = data.get(key)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(
            f"template {name!r}: {key!r} must be a mapping of area → "
            f"[token, ...], got {type(raw).__name__}"
        )

    filters: dict[str, list[str]] = {}
    for area, tokens in raw.items():
        if area not in valid_areas:
            raise ValueError(
                f"template {name!r}: unknown {noun} area {area!r}; "
                f"must be one of {sorted(valid_areas)}"
            )
        if not isinstance(tokens, list):
            raise ValueError(
                f"template {name!r}: {key}.{area} must be a list of names, "
                f"got {type(tokens).__name__}"
            )
        cleaned: list[str] = []
        for item in tokens:
            if not isinstance(item, str):
                raise ValueError(
                    f"template {name!r}: every entry in {key}.{area} must be a "
                    f"string, got {type(item).__name__}: {item!r}"
                )
            token = item.strip().lower()
            if token:
                cleaned.append(token)
        filters[area] = cleaned
    return filters


def _load_flat_block(name: str, key: str) -> list[str]:
    """
    Load a flat-list ALLOWLIST block (a sibling of ``document``) — the loader
    behind the single-axis genomics blocks ``genes:`` and ``gene_sets:``.

    The block is a LIST of tokens:

        <key>: [token, ...]

    Returns ``[tokens]`` lower-cased and stripped.  A missing block, or a file
    that is a bare list, returns ``[]`` (no filtering).  Validates that the
    block is a list of strings; a mapping is the rejected per-area shape.
    """
    data = _load_raw(name)
    if not isinstance(data, dict):
        return []
    raw = data.get(key)
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(
            f"template {name!r}: {key!r} must be a list of names, "
            f"got {type(raw).__name__}"
        )
    cleaned: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise ValueError(
                f"template {name!r}: every entry in {key} must be a string, "
                f"got {type(item).__name__}: {item!r}"
            )
        token = item.strip().lower()
        if token:
            cleaned.append(token)
    return cleaned


def load_report_organs(name: str) -> dict[str, list[str]]:
    """
    Load the ``organs`` block — the per-area organ ALLOWLIST.

        organs:
          genomics: [kidney]            # limit the genomics sections to kidney
          organ-weight: [liver, kidney] # limit the organ-weight table/narrative

    Returns ``{area: [tokens]}`` (lower-cased); filtering compares via
    table_builder_common.organ_allowed (component-aware).  See
    _load_per_area_block for the shape rules.
    """
    return _load_per_area_block(name, "organs", REPORT_ORGAN_AREAS,
                                area_noun="organ")


def load_report_sex(name: str) -> dict[str, list[str]]:
    """
    Load the ``sex`` block — the per-area sex ALLOWLIST.

        sex:
          apical: [male]      # show only male columns in the apical tables
          genomics: [male]    # show only male organ×sex genomics sections

    Returns ``{area: [tokens]}`` (lower-cased).  Filtering compares via
    table_builder_common.sex_allowed (exact match).
    """
    return _load_per_area_block(name, "sex", REPORT_SEX_AREAS)


# Sexes a per-sex assay mapping may key on (lower-cased match form).  A closed
# vocabulary so a typo'd sex key fails loudly at load, matching REPORT_*_AREAS.
_VALID_ASSAY_SEXES: frozenset[str] = frozenset({"male", "female"})


def _clean_token_list(tokens, where: str) -> list[str]:
    """Lower-case + strip a list of string tokens, dropping empties.  Raises if
    ``tokens`` is not a list of strings.  ``where`` names the location for the
    error message."""
    if not isinstance(tokens, list):
        raise ValueError(
            f"{where} must be a list of names, got {type(tokens).__name__}"
        )
    cleaned: list[str] = []
    for item in tokens:
        if not isinstance(item, str):
            raise ValueError(
                f"every entry in {where} must be a string, "
                f"got {type(item).__name__}: {item!r}"
            )
        token = item.strip().lower()
        if token:
            cleaned.append(token)
    return cleaned


def load_report_assays(name: str) -> dict[str, list[str] | dict[str, list[str]]]:
    """
    Load the ``assays`` block — the per-area clinical-pathology endpoint
    ALLOWLIST.  Each area's value is EITHER a flat token list (applies to BOTH
    sexes — the original form) OR a per-sex mapping (different endpoints per
    sex, matching the reference's "Select" tables):

        assays:
          clinical-chemistry:            # flat — same endpoints for both sexes
            [albumin, "alanine aminotransferase"]
          hematology:                    # per-sex — the reference selection
            male: ["neutrophil count"]
            female: ["manual hematocrit"]

    Returns ``{area: [tokens]}`` for a flat area, or ``{area: {sex: [tokens]}}``
    for a per-sex area (all tokens lower-cased/stripped).  Filtering compares via
    table_builder_common.assay_allowed (component-aware); apply_apical_filters
    resolves the per-sex shape inside its sex loop.  Areas are the two
    multi-endpoint platforms only (REPORT_ASSAY_AREAS); Hormones is never
    assay-filtered.  A missing block, or a bare-list file, returns ``{}``.

    Validates SHAPE loudly: the block is a mapping; every area is one of
    REPORT_ASSAY_AREAS; each area value is a token list OR a mapping whose keys
    are in {male, female} and whose values are token lists.
    """
    data = _load_raw(name)
    if not isinstance(data, dict):
        return {}
    raw = data.get("assays")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(
            f"template {name!r}: 'assays' must be a mapping of area → "
            f"[token, ...] or area → {{sex: [token, ...]}}, "
            f"got {type(raw).__name__}"
        )

    filters: dict[str, list[str] | dict[str, list[str]]] = {}
    for area, value in raw.items():
        if area not in REPORT_ASSAY_AREAS:
            raise ValueError(
                f"template {name!r}: unknown assays area {area!r}; "
                f"must be one of {sorted(REPORT_ASSAY_AREAS)}"
            )
        if isinstance(value, dict):
            per_sex: dict[str, list[str]] = {}
            for sex, tokens in value.items():
                sex_key = str(sex).strip().lower()
                if sex_key not in _VALID_ASSAY_SEXES:
                    raise ValueError(
                        f"template {name!r}: unknown sex {sex!r} in "
                        f"assays.{area}; must be one of "
                        f"{sorted(_VALID_ASSAY_SEXES)}"
                    )
                per_sex[sex_key] = _clean_token_list(
                    tokens, f"template {name!r}: assays.{area}.{sex_key}"
                )
            filters[area] = per_sex
        else:
            filters[area] = _clean_token_list(
                value, f"template {name!r}: assays.{area}"
            )
    return filters


def load_report_genes(name: str) -> list[str]:
    """
    Load the ``genes`` block — a flat gene-symbol ALLOWLIST (genomics-only).

        genes: [egr1, ddit4]

    Returns ``[tokens]`` (lower-cased).  Filtering compares via
    table_builder_common.gene_allowed.
    """
    return _load_flat_block(name, "genes")


def load_report_gene_sets(name: str) -> list[str]:
    """
    Load the ``gene_sets`` block — a flat gene-set / GO-term ALLOWLIST
    (genomics-only).

        gene_sets: ["GO:1902893", "cell division"]

    Returns ``[tokens]`` (lower-cased — GO accessions are matched
    case-insensitively against the lower-cased go_id).  Filtering compares via
    table_builder_common.gene_set_allowed (go_id OR go_term-component).
    """
    return _load_flat_block(name, "gene_sets")


def load_report_charts(name: str) -> list[str] | None:
    """
    Load the ``charts`` block — an ALLOWLIST of genomics chart TYPE KEYS to
    render (``umap``, ``cluster``, or any data-driven type in ``chart_types``).

        charts: [umap, cluster]   # render only these types
        charts: []                # render NO genomics charts

    Unlike the token allowlists (``genes``/``gene_sets``/``organs``) whose empty
    form means "no filtering", this block ranges over a CLOSED set of chart
    types, so an explicit empty list genuinely means "render none".  The
    distinction is presence:

      - key ABSENT      → ``None`` → no filtering (every chart type renders —
                          the backward-compatible default);
      - key PRESENT     → the (possibly empty) lower-cased list → only those
                          types render.

    Honored identically by both render paths where charts attach
    (genomics_charts.attach_genomics_charts's ``enabled_types``), so the HTML
    preview and the Overleaf export agree on which figures appear.
    """
    data = _load_raw(name)
    if not isinstance(data, dict) or "charts" not in data:
        return None
    raw = data.get("charts")
    if not isinstance(raw, list):
        raise ValueError(
            f"template {name!r}: 'charts' must be a list of chart-type keys, "
            f"got {type(raw).__name__}"
        )
    cleaned: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise ValueError(
                f"template {name!r}: every entry in 'charts' must be a string, "
                f"got {type(item).__name__}: {item!r}"
            )
        token = item.strip().lower()
        if token:
            cleaned.append(token)
    return cleaned


# ---------------------------------------------------------------------------
# Canonical filter representation (unification, Phase 1).
#
# The six load_report_* loaders above return THREE incompatible shapes: flat
# `list` (genes/gene_sets), `{area: list}` (organs/sex), and
# `{area: list | {sex: list}}` (assays).  For per-version report configs and a
# single render-time filter application, callers want ONE shape.
#
# The canonical form is a uniform 3-level nesting:
#     {dimension: {area: {sex_key: [tokens]}}}
# where `sex_key` is "*" (both sexes / not sex-scoped) or "male"/"female".
# Flat dimensions collapse to area "*"; non-per-sex areas collapse to sex "*".
# `charts` is deliberately kept OUT of this structure and carried alongside as
# its own field: it is a CLOSED-vocabulary enable-list (absent=all, []=none),
# semantically unlike the open-token allowlists, and forcing it in would break
# that empty-semantics distinction (see load_report_charts).
# ---------------------------------------------------------------------------

# Dimensions carried in the canonical structure (charts handled separately).
REPORT_FILTER_DIMENSIONS: tuple[str, ...] = (
    "organs", "sex", "assays", "genes", "gene_sets",
)


def _normalize_dimension(raw) -> dict[str, dict[str, list[str]]]:
    """
    Map one loaded dimension's raw result to the canonical
    ``{area: {sex_key: [tokens]}}`` form.  Accepts all three input shapes:

      - flat ``[tokens]``                    → ``{"*": {"*": [tokens]}}``
      - ``{area: [tokens]}``                 → ``{area: {"*": [tokens]}}``
      - ``{area: {sex: [tokens]}}`` (assays) → ``{area: {sex: [tokens]}}``

    Tokens are passed through as-is (the loaders already lower-cased/stripped).
    """
    if raw is None:
        return {}
    if isinstance(raw, list):
        return {"*": {"*": list(raw)}} if raw else {}
    if isinstance(raw, dict):
        out: dict[str, dict[str, list[str]]] = {}
        for area, value in raw.items():
            if isinstance(value, dict):
                out[area] = {str(s).strip().lower(): list(t) for s, t in value.items()}
            else:
                out[area] = {"*": list(value or [])}
        return out
    return {}


def normalize_filters(
    *,
    organs=None,
    sex=None,
    assays=None,
    genes=None,
    gene_sets=None,
) -> dict[str, dict[str, dict[str, list[str]]]]:
    """
    Compose the already-loaded per-dimension results into the canonical
    ``{dimension: {area: {sex_key: [tokens]}}}`` structure.  Pure — takes the
    loader outputs, so it is trivially unit-testable against the three shapes.
    Empty dimensions are omitted.
    """
    raw = {
        "organs": organs, "sex": sex, "assays": assays,
        "genes": genes, "gene_sets": gene_sets,
    }
    out: dict[str, dict[str, dict[str, list[str]]]] = {}
    for dim, value in raw.items():
        norm = _normalize_dimension(value)
        if norm:
            out[dim] = norm
    return out


def normalize_filters_block(filters) -> dict:
    """
    Coerce a raw ``filters`` mapping — as a version file / UI may author it, in
    any of the three legacy per-dimension shapes — into the canonical
    ``{dimension: {area: {sex_key: [tokens]}}}`` structure, validating as it goes.

    This is the save-time guard for per-version filters.  ``resolve_report_allowlist``
    (the render-time consumer) assumes the canonical nesting, so a version stored
    with a non-canonical shape (e.g. ``sex: {apical: [male]}`` instead of
    ``{apical: {"*": [male]}}``) would crash at render (``.get`` on a list).
    Normalizing on save both accepts the friendlier per-area shape and guarantees
    what lands on disk is canonical.

    Raises ValueError on structural errors (unknown dimension, non-list leaf
    tokens, wrong nesting) so a bad version fails loudly at save, not silently at
    render.  Empty/None ⇒ ``{}`` (no filtering).
    """
    if not filters:
        return {}
    if not isinstance(filters, dict):
        raise ValueError(f"'filters' must be a mapping, got {type(filters).__name__}")

    def _tokens(val, where: str) -> list[str]:
        # Tokens must be lower-cased + stripped to match the predicate contract
        # (filter_allows expects a pre-lowered allowlist; only the candidate is
        # folded at match time — see document_model/filters.py).  The load_report_*
        # loaders do this; a version file authors raw tokens, so we do it here too
        # or a mixed-case token (e.g. "GO:0051301") would silently never match.
        if not isinstance(val, list):
            raise ValueError(f"{where}: token allowlist must be a list, got {type(val).__name__}")
        cleaned: list[str] = []
        for t in val:
            if not isinstance(t, str):
                raise ValueError(f"{where}: tokens must be strings, got {type(t).__name__}")
            tok = t.strip().lower()
            if tok:
                cleaned.append(tok)
        return cleaned

    out: dict[str, dict[str, dict[str, list[str]]]] = {}
    for dim, raw in filters.items():
        if dim not in REPORT_FILTER_DIMENSIONS:
            raise ValueError(
                f"unknown filter dimension {dim!r}; must be one of "
                f"{list(REPORT_FILTER_DIMENSIONS)}"
            )
        if raw is None:
            continue
        if isinstance(raw, list):  # flat dimension (genes / gene_sets)
            toks = _tokens(raw, dim)
            if toks:
                out[dim] = {"*": {"*": toks}}
            continue
        if not isinstance(raw, dict):
            raise ValueError(
                f"filter dimension {dim!r} must be a list or an {{area: ...}} "
                f"mapping, got {type(raw).__name__}"
            )
        areas: dict[str, dict[str, list[str]]] = {}
        for area, val in raw.items():
            if isinstance(val, dict):  # per-area-per-sex (assays and canonical)
                areas[area] = {
                    str(s).strip().lower(): _tokens(t, f"{dim}.{area}.{s}")
                    for s, t in val.items()
                }
            else:  # per-area flat → sex "*"
                areas[area] = {"*": _tokens(val, f"{dim}.{area}")}
        if areas:
            out[dim] = areas
    return out


def load_report_filters(name: str) -> dict:
    """
    Load ALL report-level data filters for a template as one canonical object:

        {
          "filters": {dimension: {area: {sex_key: [tokens]}}},  # canonical
          "charts":  [types] | None,                            # closed-vocab
        }

    Composes the existing load_report_* loaders through normalize_filters so a
    single caller (the render/marshal path, per-version config) consumes one
    shape instead of three.  The individual loaders remain for the current
    compute-time call sites; this is the seam the render path will read.
    """
    return {
        "filters": normalize_filters(
            organs=load_report_organs(name),
            sex=load_report_sex(name),
            assays=load_report_assays(name),
            genes=load_report_genes(name),
            gene_sets=load_report_gene_sets(name),
        ),
        "charts": load_report_charts(name),
    }


def resolve_report_allowlist(
    filters: dict, dimension: str, area: str | None = None, sex: str | None = None
) -> list[str] | None:
    """
    Extract the token allowlist for one (dimension, area, sex) from a canonical
    ``filters`` structure (the ``"filters"`` value of load_report_filters).

    Resolution falls back through the "*" wildcards: an exact ``area``/``sex``
    key wins; otherwise "*" is used.  Returns None when the dimension/area is
    absent (⇒ no filtering, the loaders' empty convention).
    """
    dim = filters.get(dimension)
    if not dim:
        return None
    area_map = dim.get(area) if area is not None else None
    if area_map is None:
        area_map = dim.get("*")
    if not area_map:
        return None
    sex_key = str(sex).strip().lower() if sex else "*"
    tokens = area_map.get(sex_key)
    if tokens is None:
        tokens = area_map.get("*")
    return tokens


def instantiate(template: list[dict]) -> list[DocNode]:
    """
    Instantiate a template into a flat list of DocNode top-level entries.

    Top-level template entries are EITHER region containers
    ({region: "front"|"body"|"back", children: [...]}) — ADR-0004 amendment d
    — OR bare node entries (back-compat for unit-test scaffolding).  Region
    containers set the `region` for their children and descendants; bare
    entries get region=None.  The returned list is flat (regions are unrolled
    so DOCUMENT_TREE shape is unchanged); each node carries `region`.

    Validates each entry against the catalog (type, containment, required
    bindings, capability-gated orientation/caption), derives heading level
    from the catalog's headingless flag + nesting depth, and recurses into
    children.  Positional table/figure numbers are NOT assigned here — the
    caller runs compute_table_numbers() afterward, exactly as before.
    """
    nodes: list[DocNode] = []
    for entry in template:
        if isinstance(entry, dict) and "region" in entry:
            _validate_region_container(entry)
            region = entry["region"]
            for child in entry.get("children", []):
                nodes.append(_instantiate_node(child, depth=1, parent_type=None, region=region))
        else:
            nodes.append(_instantiate_node(entry, depth=1, parent_type=None, region=None))
    return nodes


def build_tree(name: str) -> list[DocNode]:
    """Convenience: load a named template and instantiate it in one call."""
    return instantiate(load_template(name))
