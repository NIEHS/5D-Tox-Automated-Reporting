"""
document_config.py — per-session document STRUCTURE overrides (ADR-0007 follow-on).

The document tree is normally a single global built once at import from
``templates/niehs-5day-report.yaml`` (see document_tree.DOCUMENT_TREE).  This
module lets a single report (keyed by DTXSID) carry its OWN ``document:``
structure — sections, ordering, titles, orientation, freeform content — without
touching the global default template or re-integrating the study data.

Scope is deliberately STRUCTURE ONLY: the per-session file holds just the
``document:`` block.  The data-filter / chart blocks (organs, sex, assays,
genes, charts) stay global, because those feed the integration pipeline and
editing them would require a reprocess — the opposite of this feature's promise.

Storage: ``sessions/<dtxsid>/document.yaml``.  Absent ⇒ the caller falls back to
the global DOCUMENT_TREE (build_session_tree returns None), so an untouched
session renders byte-identically to today.

The file may be EITHER a bare YAML list of node entries or a mapping with a
``document:`` key — the same dual shape document_template.load_template accepts —
so a user can paste either form.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from document_node import DocNode
from document_template import instantiate, load_template
from document_tree import (
    ACTIVE_TEMPLATE,
    build_node_index,
    compute_table_numbers,
)
from session_store import SESSIONS_DIR

_SESSION_DOCUMENT_FILE = "document.yaml"
_SESSION_STYLES_FILE = "styles.yaml"


def session_document_path(dtxsid: str) -> Path:
    """Path to a session's per-session document-structure YAML (may not exist)."""
    return SESSIONS_DIR / dtxsid / _SESSION_DOCUMENT_FILE


def session_styles_path(dtxsid: str) -> Path:
    """Path to a session's per-session layout-styles YAML (may not exist)."""
    return SESSIONS_DIR / dtxsid / _SESSION_STYLES_FILE


def _parse_document_yaml(text: str) -> list[dict]:
    """
    Parse a document-structure YAML STRING into the node-entry list.

    Mirrors document_template.load_template's dual-shape acceptance (a bare list,
    or a mapping with a ``document:`` key), but from a string rather than a named
    file.  Raises ValueError if the shape is neither, or if the YAML is invalid.
    """
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ValueError(f"invalid YAML: {e}") from e
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "document" in data:
        doc = data["document"]
        if not isinstance(doc, list):
            raise ValueError(
                f"'document' must be a list of node entries, got {type(doc).__name__}"
            )
        return doc
    raise ValueError(
        "document config must be a YAML list of node entries, or a mapping with "
        f"a 'document' key, got {type(data).__name__}"
    )


def _tree_from_document_list(document: list[dict]) -> list[DocNode]:
    """
    Instantiate + finalize a tree from a parsed document list.

    Runs the full validation the global tree gets: instantiate() validates every
    entry against the catalog (type, containment, required bindings, capability-
    gated orientation/caption, freeform rules), and build_node_index() enforces
    globally-unique ids.  Both raise ValueError on bad input.  compute_table_numbers
    assigns positional table numbers on the fresh tree (in place).
    """
    tree = instantiate(document)
    compute_table_numbers(tree)
    build_node_index(tree)  # raises on duplicate ids; return value not needed here
    return tree


def default_document_yaml() -> str:
    """
    The global default ``document:`` structure, serialized to YAML text.

    Shown in the config editor when a session has no per-session override yet, so
    the user starts from the real active structure.  Re-dumped from the parsed
    block (comments in the source file are not carried), wrapped under a
    ``document:`` key to match the canonical file shape.
    """
    document = load_template(ACTIVE_TEMPLATE)
    return yaml.safe_dump({"document": document}, sort_keys=False, allow_unicode=True)


def load_session_document_yaml(dtxsid: str) -> str | None:
    """Raw per-session document YAML text, or None if the session has no override."""
    path = session_document_path(dtxsid)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def build_session_tree(dtxsid: str) -> list[DocNode] | None:
    """
    Build a per-session DocNode tree from the session's document.yaml.

    Returns None when the session has no per-session override, so callers fall
    back to the global DOCUMENT_TREE.  Raises ValueError if a stored file is
    somehow invalid (it shouldn't be — save validates before writing).
    """
    text = load_session_document_yaml(dtxsid)
    if text is None:
        return None
    return _tree_from_document_list(_parse_document_yaml(text))


def save_session_document_yaml(dtxsid: str, text: str) -> None:
    """
    Validate then persist a session's document-structure YAML.

    Validation is a full tree build (_tree_from_document_list): any parse error,
    catalog violation, missing required binding, bad orientation/caption, freeform
    rule breach, or duplicate id raises ValueError BEFORE anything is written — so
    an invalid edit never lands on disk and the previous structure stays intact.
    """
    _tree_from_document_list(_parse_document_yaml(text))  # validate; raises on failure
    path = session_document_path(dtxsid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Per-session layout STYLES override (the typography/flow analog of the
# per-session document structure above).  Unlike the data/chart blocks the
# module header warns off, styles are pure PRESENTATION — they do not feed the
# integration pipeline, so a per-session override is safe and cheap (re-renders
# with no reprocess, exactly like the structure override).  Stored as
# ``sessions/<dtxsid>/styles.yaml``; absent ⇒ None ⇒ caller uses the global
# template `styles:` block (or nothing).
# ---------------------------------------------------------------------------

def _parse_styles_yaml(text: str) -> dict:
    """
    Parse + VALIDATE a layout-styles YAML string into the ``styles`` mapping.

    Accepts either a bare mapping (``defaults:``/``types:``/``instances:`` at the
    top level) or a mapping nested under a ``styles:`` key — the same dual shape
    the template file uses — so a user can paste either form.  Runs the identical
    loud validation as document_template.load_layout_style (enum/length/color
    value checks, real-catalog-type keys), raising ValueError before any write.
    """
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ValueError(f"invalid YAML: {e}") from e
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(
            f"styles config must be a YAML mapping, got {type(data).__name__}"
        )
    cfg = data.get("styles", data)
    if not isinstance(cfg, dict):
        raise ValueError(
            f"'styles' must be a mapping, got {type(cfg).__name__}"
        )
    _validate_styles_cfg(cfg)
    return cfg


def _validate_styles_cfg(cfg: dict) -> None:
    """
    Loud shape/value validation for a ``styles`` mapping — the same rules
    document_template.load_layout_style enforces on the template block, factored
    here so the per-session path validates identically.  Raises ValueError.
    """
    import layout_style
    from document_template import COMPONENT_CATALOG

    for sub in ("defaults", "types", "instances"):
        if sub in cfg and not isinstance(cfg[sub], dict):
            raise ValueError(
                f"styles.{sub} must be a mapping, got {type(cfg[sub]).__name__}"
            )
    for node_type in (cfg.get("types") or {}):
        if node_type not in COMPONENT_CATALOG:
            raise ValueError(
                f"styles.types.{node_type!r} is not a catalog content type"
            )
    layers: list[tuple[str, dict]] = []
    if isinstance(cfg.get("defaults"), dict):
        layers.append(("defaults", cfg["defaults"]))
    for k, v in (cfg.get("types") or {}).items():
        if isinstance(v, dict):
            layers.append((f"types.{k}", v))
    for k, v in (cfg.get("instances") or {}).items():
        if isinstance(v, dict):
            layers.append((f"instances.{k}", v))
    for where, style in layers:
        errors = layout_style.validate_style(style)
        if errors:
            raise ValueError(
                f"styles.{where} has invalid value(s): {'; '.join(errors)}"
            )


def load_session_layout_style(dtxsid: str) -> dict | None:
    """
    The session's per-session ``styles`` override as a mapping, or None when the
    session has no override (caller falls back to the global template block).
    """
    path = session_styles_path(dtxsid)
    if not path.exists():
        return None
    return _parse_styles_yaml(path.read_text(encoding="utf-8"))


def save_session_layout_style(dtxsid: str, text: str) -> None:
    """
    Validate then persist a session's layout-styles YAML (validate-before-write,
    same discipline as save_session_document_yaml).  A bad value never lands on
    disk, so a broken style can't reach the renderers.
    """
    _parse_styles_yaml(text)  # validate; raises on failure
    path = session_styles_path(dtxsid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Default (global template) editor — edits templates/<ACTIVE_TEMPLATE>.yaml,
# the git-tracked structure EVERY report inherits when it has no per-session
# override.  Unlike the per-session file, a default edit must apply live to the
# in-process tree and keep the golden-tree guard green.
# ---------------------------------------------------------------------------

def _template_path() -> Path:
    """Path to the active template file (the git-tracked default structure)."""
    from document_template import TEMPLATES_DIR
    return TEMPLATES_DIR / f"{ACTIVE_TEMPLATE}.yaml"


# The golden fixture the document-template test pins the tree to; regenerated on
# a valid default save so a UI edit doesn't red the guard (matches the exact
# serialization tests/unit/test_document_template.py uses).
_GOLDEN_FIXTURE = (
    Path(__file__).resolve().parent
    / "tests" / "unit" / "fixtures" / "document_tree_golden.json"
)


def load_default_document_yaml() -> str:
    """The default (template) document structure as YAML — the default editor's
    initial content.  Same text default_document_yaml() produces."""
    return default_document_yaml()


def _regenerate_golden_fixture() -> None:
    """
    Rewrite the golden document-tree fixture from the current global tree, using
    the exact serialization the golden test compares against
    (json.dumps(serialize_tree(...), sort_keys=True, indent=2, ensure_ascii=False)
    + newline).  Keeps the guard green after an intentional UI default-edit.
    """
    import json
    from document_tree import DOCUMENT_TREE, serialize_tree, compute_table_numbers
    compute_table_numbers(DOCUMENT_TREE)
    serialized = json.dumps(
        serialize_tree(DOCUMENT_TREE), sort_keys=True, indent=2, ensure_ascii=False
    ) + "\n"
    if _GOLDEN_FIXTURE.exists():   # only regen where the fixture actually lives
        _GOLDEN_FIXTURE.write_text(serialized, encoding="utf-8")


def save_default_document_yaml(text: str) -> None:
    """
    Validate, persist, and LIVE-APPLY an edit to the default (template) structure.

    Steps (validate-before-write, same guard as the per-session save):
      1. Parse + full tree build — raises ValueError on any invalid edit BEFORE
         touching disk, so a bad edit never corrupts the template.
      2. Rewrite ONLY the template's ``document:`` block, preserving its sibling
         blocks (organs/assays/charts/...) — load the whole file, replace the
         document list, dump back.  (safe_dump does not preserve YAML comments;
         the author reviews the git diff before committing.)
      3. rebuild_document_tree() — re-instantiate the in-process global tree in
         place so renderers/nav/preview reflect the edit with no restart.
      4. Refresh the served serialized-tree singleton + regenerate the golden
         fixture so the browser and the dev guard both track the new default.
    """
    document = _parse_document_yaml(text)
    _tree_from_document_list(document)  # validate; raises on failure

    path = _template_path()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw["document"] = document      # preserve organs/assays/charts siblings
        new_text = yaml.safe_dump(raw, sort_keys=False, allow_unicode=True)
    else:
        # Legacy bare-list template (no siblings) — dump the document list alone.
        new_text = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    path.write_text(new_text, encoding="utf-8")

    # Apply live + keep the browser and the golden guard in sync.
    from document_tree import rebuild_document_tree
    rebuild_document_tree()
    try:
        import background_server
        background_server.refresh_serialized_tree()
    except Exception:
        # The served singleton refresh is best-effort (e.g. background_server not
        # imported in a unit-test context); the tree rebuild above is what matters.
        pass
    _regenerate_golden_fixture()


# ---------------------------------------------------------------------------
# Default (global template) layout STYLES editor — edits the template's
# ``styles:`` sibling block, the typography/flow EVERY report inherits without a
# per-session styles override.  Simpler than the structure default above: styles
# do NOT feed the tree, so there is no tree rebuild and no golden fixture to keep
# green — the render path re-reads load_layout_style() live per request.
# ---------------------------------------------------------------------------

def default_layout_style_yaml() -> str:
    """
    The global default ``styles:`` block as YAML text — the default styles
    editor's initial content.  Empty ``styles: {}`` when the template has none
    (the no-styling baseline), so the editor opens on a valid, editable stub.
    """
    from document_template import load_layout_style
    cfg = load_layout_style(ACTIVE_TEMPLATE)
    return yaml.safe_dump({"styles": cfg or {}}, sort_keys=False, allow_unicode=True)


def default_layout_style_config() -> dict:
    """
    The global default ``styles:`` block as a mapping — the visual builder's
    initial state when a session has no override (the JSON-only sibling of
    default_layout_style_yaml).  ``{}`` when the template declares no styles.
    """
    from document_template import load_layout_style
    return load_layout_style(ACTIVE_TEMPLATE) or {}


def save_default_layout_style(text: str) -> None:
    """
    Validate + persist an edit to the DEFAULT (template) ``styles:`` block.

    Validate-before-write (same discipline as the structure default): the parse
    runs the loud enum/length/color + catalog-type checks and raises ValueError
    on any bad value BEFORE touching disk.  On success ONLY the ``styles:``
    sibling is rewritten (document/organs/assays/charts preserved); no tree
    rebuild is needed because styles are pure presentation — the next render
    re-reads the block via load_layout_style().
    """
    cfg = _parse_styles_yaml(text)  # validate; raises on failure

    path = _template_path()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        # Legacy bare-list template — promote to a mapping so styles can attach.
        raw = {"document": raw if isinstance(raw, list) else []}
    if cfg:
        raw["styles"] = cfg
    else:
        raw.pop("styles", None)  # empty edit clears the block rather than storing {}
    path.write_text(
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
