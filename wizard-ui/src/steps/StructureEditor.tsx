import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, CatalogType, DocEntry, DocumentCatalog } from "../api";
import { invalidate } from "../useServerResource";
import { ErrorBox, Spinner, WarningBox } from "./shared";

// Visual editor for a session's document structure (Configure step).
//
// The on-disk truth is YAML; this component edits its PARSED shape (a node
// tree) and round-trips through the server's own parser/dumper, so what the
// tree shows is exactly what will be saved. Every structural rule comes from
// the component catalog served by /api/document-catalog — which types may
// nest where, which bindings are required, which options a type supports —
// so nothing about the report's structure is hardcoded here. The server's
// full save-time validation runs (debounced) on every change and pins its
// message to the offending node; Save is disabled while the document is
// invalid. The "YAML (advanced)" view is the same document as text.

type Path = number[]; // index path from the document root

interface ValidationState {
  ok: boolean;
  error?: string;
  node_id?: string | null;
}

// Bindings the inspector offers per type (in addition to the catalog's
// `requires`). Everything else present on a node is preserved untouched.
const OPTIONAL_KEYS: Record<string, string[]> = {
  narrative: ["methods_key"],
  "heading-only": ["data_key", "methods_key"],
  "narrative+tables": ["narrative_key"],
  "bmd-summary": ["caption"],
  "sample-counts-table": ["caption"],
  table: ["caption"],
  "incidence-table": ["caption"],
  figure: ["caption", "subtype"],
  "freeform-block": ["content_file"],
  "freeform-page": ["content_file"],
  "title-page": ["subtype"],
  cover: ["subtype"],
};

const KEY_LABELS: Record<string, string> = {
  data_key: "Data key",
  platform: "Platform",
  narrative_key: "Narrative key",
  methods_key: "Methods subsection",
  caption: "Caption",
  orientation: "Orientation",
  subtype: "Subtype",
  content_file: "Content file",
};

function slugify(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 48) || "section";
}

function clone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v)) as T;
}

function getAt(doc: DocEntry[], path: Path): DocEntry | null {
  let list: DocEntry[] | undefined = doc;
  let node: DocEntry | null = null;
  for (const i of path) {
    if (!list || !list[i]) return null;
    node = list[i];
    list = node.children;
  }
  return node;
}

function listAt(doc: DocEntry[], path: Path): DocEntry[] {
  // The sibling list that `path` indexes into (path = [] ⇒ root list).
  if (path.length === 0) return doc;
  const parent = getAt(doc, path);
  if (!parent) return doc;
  if (!parent.children) parent.children = [];
  return parent.children;
}

function removeAt(doc: DocEntry[], path: Path): DocEntry | null {
  const parentPath = path.slice(0, -1);
  const list = listAt(doc, parentPath);
  const idx = path[path.length - 1];
  if (idx < 0 || idx >= list.length) return null;
  return list.splice(idx, 1)[0];
}

function isAncestor(a: Path, b: Path): boolean {
  return a.length < b.length && a.every((v, i) => v === b[i]);
}

function allIds(doc: DocEntry[], out: Set<string> = new Set()): Set<string> {
  for (const e of doc) {
    if (typeof e.id === "string") out.add(e.id);
    if (e.children) allIds(e.children, out);
  }
  return out;
}

function typeLabel(type: string | undefined, region: string | undefined): string {
  if (!type && region) return `${region} matter`;
  return type ?? "node";
}

export function StructureEditor({ dtxsid }: { dtxsid: string }) {
  const [catalog, setCatalog] = useState<DocumentCatalog | null>(null);
  const [doc, setDoc] = useState<DocEntry[] | null>(null);
  const [isDefault, setIsDefault] = useState(true);
  const [selected, setSelected] = useState<Path | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [validation, setValidation] = useState<ValidationState>({ ok: true });
  const [validating, setValidating] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"tree" | "yaml">("tree");
  const [yamlText, setYamlText] = useState("");
  const [dragging, setDragging] = useState<Path | null>(null);
  const [dropHint, setDropHint] = useState<string | null>(null);
  const history = useRef<{ past: DocEntry[][]; future: DocEntry[][] }>({ past: [], future: [] });
  const loadedYaml = useRef("");

  // ---- load ------------------------------------------------------------
  const load = useCallback(
    async (loadDefault = false) => {
      setError(null);
      try {
        const [cat, cfg] = await Promise.all([
          catalog ? Promise.resolve(catalog) : api.getDocumentCatalog(),
          api.getDocumentConfig(dtxsid, loadDefault),
        ]);
        setCatalog(cat);
        const parsed = await api.parseDocumentConfig(cfg.yaml);
        loadedYaml.current = cfg.yaml;
        setDoc(parsed.document);
        setIsDefault(cfg.is_default);
        setDirty(loadDefault); // "Load default" is a pending change until saved
        setSaved(false);
        setSelected(null);
        history.current = { past: [], future: [] };
        // Expand the region containers and top-level groups by default.
        const ex = new Set<string>();
        parsed.document.forEach((e, i) => {
          ex.add(String(i));
          (e.children ?? []).forEach((_, j) => ex.add(`${i}.${j}`));
        });
        setExpanded(ex);
        setValidation({ ok: true });
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [dtxsid, catalog]
  );

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dtxsid]);

  // ---- validation (debounced) --------------------------------------------
  useEffect(() => {
    if (!doc || !dirty) return;
    let cancelled = false;
    setValidating(true);
    const t = setTimeout(() => {
      api
        .validateDocumentConfig(doc)
        .then((v) => {
          if (!cancelled) setValidation(v);
        })
        .catch((e) => {
          if (!cancelled) setValidation({ ok: false, error: e instanceof Error ? e.message : String(e) });
        })
        .finally(() => {
          if (!cancelled) setValidating(false);
        });
    }, 350);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [doc, dirty]);

  // ---- mutation helper with undo history ----------------------------------
  const mutate = useCallback(
    (fn: (d: DocEntry[]) => void) => {
      setDoc((prev) => {
        if (!prev) return prev;
        history.current.past.push(clone(prev));
        if (history.current.past.length > 100) history.current.past.shift();
        history.current.future = [];
        const next = clone(prev);
        fn(next);
        return next;
      });
      setDirty(true);
      setSaved(false);
    },
    []
  );

  function undo() {
    const prev = history.current.past.pop();
    if (!prev || !doc) return;
    history.current.future.push(clone(doc));
    setDoc(prev);
    setDirty(true);
    setSelected(null);
  }

  function redo() {
    const next = history.current.future.pop();
    if (!next || !doc) return;
    history.current.past.push(clone(doc));
    setDoc(next);
    setDirty(true);
    setSelected(null);
  }

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) redo();
        else undo();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc]);

  // ---- catalog rules -------------------------------------------------------
  const typeOf = (e: DocEntry | null | undefined): string | null => (e?.type ? String(e.type) : null);

  function allowedChildren(parent: DocEntry | null): string[] {
    if (!catalog) return [];
    if (!parent || (!parent.type && parent.region)) {
      // Root / region container: any type the catalog does not confine to a
      // specific parent. Types that only ever appear as children (tables under
      // narrative+tables, freeform-block under appendix/heading-only) are
      // excluded so a drop there fails the same way the server would.
      const onlyChild = new Set<string>();
      for (const [t, c] of Object.entries(catalog.types)) {
        for (const ch of c.allowed_children) if (ch !== t) onlyChild.add(ch);
      }
      const rootOnly = ["table", "incidence-table", "freeform-block"];
      return Object.keys(catalog.types).filter((t) => !rootOnly.includes(t) || !onlyChild.has(t));
    }
    const ct = catalog.types[typeOf(parent) ?? ""];
    return ct ? ct.allowed_children : [];
  }

  function canPlace(type: string | null, parent: DocEntry | null): boolean {
    if (!type) return false;
    return allowedChildren(parent).includes(type);
  }

  // ---- structural operations ------------------------------------------------
  function move(from: Path, toParent: Path, toIndex: number) {
    if (!doc) return;
    if (isAncestor(from, toParent) || from.join(".") === toParent.join(".")) return;
    const node = getAt(doc, from);
    const parent = toParent.length ? getAt(doc, toParent) : null;
    if (!node || !canPlace(typeOf(node), parent)) return;
    mutate((d) => {
      const moved = removeAt(d, from);
      if (!moved) return;
      // If the removal shifted the destination index (same parent, earlier index), adjust.
      let idx = toIndex;
      const sameParent = from.slice(0, -1).join(".") === toParent.join(".");
      if (sameParent && from[from.length - 1] < toIndex) idx -= 1;
      const list = listAt(d, toParent);
      list.splice(Math.max(0, Math.min(idx, list.length)), 0, moved);
    });
    setSelected(null);
  }

  function shift(path: Path, delta: number) {
    if (!doc) return;
    const parentPath = path.slice(0, -1);
    const idx = path[path.length - 1];
    const list = listAt(doc, parentPath);
    const to = idx + delta;
    if (to < 0 || to >= list.length) return;
    mutate((d) => {
      const l = listAt(d, parentPath);
      const [n] = l.splice(idx, 1);
      l.splice(to, 0, n);
    });
    setSelected([...parentPath, to]);
  }

  function indent(path: Path) {
    // Into the previous sibling (as its last child), if the catalog allows it.
    if (!doc) return;
    const idx = path[path.length - 1];
    if (idx === 0) return;
    const parentPath = path.slice(0, -1);
    const prev = [...parentPath, idx - 1];
    const target = getAt(doc, prev);
    const node = getAt(doc, path);
    if (!target || !node || !canPlace(typeOf(node), target)) return;
    const n = (target.children ?? []).length;
    move(path, prev, n);
    setExpanded((s) => new Set(s).add(prev.join(".")));
  }

  function outdent(path: Path) {
    // After its parent, in the grandparent's list — if allowed there.
    if (!doc || path.length < 2) return;
    const parentPath = path.slice(0, -1);
    const grandPath = parentPath.slice(0, -1);
    const grand = grandPath.length ? getAt(doc, grandPath) : null;
    const node = getAt(doc, path);
    if (!node || !canPlace(typeOf(node), grand)) return;
    move(path, grandPath, parentPath[parentPath.length - 1] + 1);
  }

  function remove(path: Path) {
    mutate((d) => {
      removeAt(d, path);
    });
    setSelected(null);
  }

  function addChild(parentPath: Path, type: string) {
    if (!doc || !catalog) return;
    const ct = catalog.types[type];
    const ids = allIds(doc);
    const base = slugify(type);
    let id = base;
    for (let n = 2; ids.has(id); n++) id = `${base}-${n}`;
    const entry: DocEntry = { id, type, title: type.replace(/[-+]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()) };
    for (const req of ct?.requires ?? []) entry[req] = "";
    mutate((d) => {
      listAt(d, parentPath).push(entry);
    });
    setExpanded((s) => new Set(s).add(parentPath.join(".")));
    // Select the new node.
    const list = listAt(doc, parentPath);
    setSelected([...parentPath, list.length]);
  }

  function updateField(path: Path, key: string, value: string) {
    mutate((d) => {
      const n = getAt(d, path);
      if (!n) return;
      if (value === "") delete n[key];
      else n[key] = value;
    });
  }

  // ---- YAML view ------------------------------------------------------------
  async function showYaml() {
    if (!doc) return;
    try {
      const r = await api.dumpDocumentConfig(doc);
      setYamlText(r.yaml);
      setView("yaml");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function showTree() {
    try {
      const r = await api.parseDocumentConfig(yamlText);
      history.current.past.push(clone(doc ?? []));
      setDoc(r.document);
      setDirty(true);
      setSaved(false);
      setError(null);
      setView("tree");
    } catch (e) {
      setError(`YAML could not be parsed — fix it or discard: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  // ---- save -----------------------------------------------------------------
  async function save() {
    if (!doc) return;
    setSaving(true);
    setError(null);
    try {
      const text = view === "yaml" ? yamlText : (await api.dumpDocumentConfig(doc)).yaml;
      await api.saveDocumentConfig(dtxsid, text);
      loadedYaml.current = text;
      setIsDefault(false);
      setDirty(false);
      setSaved(true);
      await invalidate(dtxsid);
      try {
        await api.materializePreview(dtxsid);
      } catch {
        /* best-effort */
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  // ---- render ---------------------------------------------------------------
  const selectedNode = useMemo(() => (doc && selected ? getAt(doc, selected) : null), [doc, selected]);
  const selectedParent = useMemo(
    () => (doc && selected && selected.length > 1 ? getAt(doc, selected.slice(0, -1)) : null),
    [doc, selected]
  );
  const errorNodeId = validation.ok ? null : validation.node_id ?? null;

  if (!doc || !catalog) return error ? <ErrorBox error={error} /> : <Spinner label="Loading structure…" />;

  return (
    <div className="configure-form">
      <p className="help" style={{ marginTop: 0 }}>
        The report's sections, in order. Drag a section to move it, or use the
        arrows; add sections from the catalog where the rules allow them; select
        one to edit its title and bindings.{" "}
        {isDefault ? (
          <em>Showing the shared default — saving creates this session's own copy.</em>
        ) : (
          <em>This session's saved structure.</em>
        )}
      </p>

      <div className="se-toolbar">
        <div className="mode-toggle">
          <button className={view === "tree" ? "active" : ""} onClick={() => (view === "yaml" ? void showTree() : undefined)}>
            Outline
          </button>
          <button className={view === "yaml" ? "active" : ""} onClick={() => (view === "tree" ? void showYaml() : undefined)}>
            YAML (advanced)
          </button>
        </div>
        <div className="se-actions">
          <button onClick={undo} disabled={history.current.past.length === 0} title="Undo (Ctrl+Z)">↶ Undo</button>
          <button onClick={redo} disabled={history.current.future.length === 0} title="Redo (Ctrl+Shift+Z)">↷ Redo</button>
          <button onClick={() => void load(true)} disabled={saving}>Load default</button>
          <button className="primary" onClick={() => void save()} disabled={saving || !dirty || (!validation.ok && view === "tree")}>
            {saving ? <Spinner label="Saving…" /> : "Save structure"}
          </button>
          {saved && <span className="badge ok">saved</span>}
          {dirty && !saved && <span className="badge warn">unsaved</span>}
        </div>
      </div>

      <ErrorBox error={error} />
      {!validation.ok && (
        <WarningBox warning={`Structure is invalid${validation.node_id ? ` (at "${validation.node_id}")` : ""}: ${validation.error}`} />
      )}
      {validating && <p className="muted se-validating">Validating…</p>}

      {view === "yaml" ? (
        <textarea
          className="query-editor structure-editor"
          value={yamlText}
          spellCheck={false}
          onChange={(e) => {
            setYamlText(e.target.value);
            setDirty(true);
            setSaved(false);
          }}
          rows={26}
        />
      ) : (
        <div className="se-layout">
          <div className="se-tree" onDragOver={(e) => e.preventDefault()}>
            {doc.map((entry, i) => (
              <OutlineNode
                key={`${i}-${entry.id ?? entry.region ?? "n"}`}
                entry={entry}
                path={[i]}
                depth={0}
                parent={null}
                catalog={catalog}
                selected={selected}
                expanded={expanded}
                errorNodeId={errorNodeId}
                dragging={dragging}
                dropHint={dropHint}
                onSelect={setSelected}
                onToggle={(k) =>
                  setExpanded((s) => {
                    const n = new Set(s);
                    if (n.has(k)) n.delete(k);
                    else n.add(k);
                    return n;
                  })
                }
                onShift={shift}
                onIndent={indent}
                onOutdent={outdent}
                onRemove={remove}
                onAddChild={addChild}
                canPlace={canPlace}
                allowedChildren={allowedChildren}
                setDragging={setDragging}
                setDropHint={setDropHint}
                onDrop={move}
                doc={doc}
              />
            ))}
          </div>
          <aside className="se-inspector">
            {selectedNode ? (
              <Inspector
                node={selectedNode}
                parent={selectedParent}
                catalog={catalog}
                doc={doc}
                path={selected as Path}
                onChange={(k, v) => updateField(selected as Path, k, v)}
              />
            ) : (
              <p className="muted">Select a section to edit its title and bindings.</p>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Outline rows
// ---------------------------------------------------------------------------

interface OutlineProps {
  entry: DocEntry;
  path: Path;
  depth: number;
  parent: DocEntry | null;
  catalog: DocumentCatalog;
  selected: Path | null;
  expanded: Set<string>;
  errorNodeId: string | null;
  dragging: Path | null;
  dropHint: string | null;
  doc: DocEntry[];
  onSelect: (p: Path) => void;
  onToggle: (key: string) => void;
  onShift: (p: Path, delta: number) => void;
  onIndent: (p: Path) => void;
  onOutdent: (p: Path) => void;
  onRemove: (p: Path) => void;
  onAddChild: (parent: Path, type: string) => void;
  canPlace: (type: string | null, parent: DocEntry | null) => boolean;
  allowedChildren: (parent: DocEntry | null) => string[];
  setDragging: (p: Path | null) => void;
  setDropHint: (k: string | null) => void;
  onDrop: (from: Path, toParent: Path, toIndex: number) => void;
}

function OutlineNode(props: OutlineProps) {
  const { entry, path, depth, parent, selected, expanded, errorNodeId, dragging, dropHint, doc } = props;
  const key = path.join(".");
  const isRegion = !entry.type && !!entry.region;
  const isSelected = selected?.join(".") === key;
  const isOpen = expanded.has(key);
  const children = entry.children ?? [];
  const canHaveChildren = isRegion || (props.allowedChildren(entry).length > 0);
  const hasError = !!entry.id && entry.id === errorNodeId;
  const [addOpen, setAddOpen] = useState(false);
  const draggedNode = dragging ? getAt(doc, dragging) : null;
  const draggedType = draggedNode?.type ? String(draggedNode.type) : null;
  const acceptsDrop = !!dragging && !isAncestor(dragging, path) && dragging.join(".") !== key;
  const canDropInto = acceptsDrop && canHaveChildren && props.canPlace(draggedType, entry);
  const canDropBefore = acceptsDrop && props.canPlace(draggedType, parent);
  const parentPath = path.slice(0, -1);
  const idx = path[path.length - 1];
  const siblings = listAt(doc, parentPath).length;

  return (
    <div className={"se-node" + (isRegion ? " region" : "")}>
      {/* drop zone: before this node */}
      {!isRegion && (
        <div
          className={"se-drop" + (dropHint === `before:${key}` ? " on" : "") + (dragging && !canDropBefore ? " no" : "")}
          onDragOver={(e) => {
            if (canDropBefore) {
              e.preventDefault();
              props.setDropHint(`before:${key}`);
            }
          }}
          onDragLeave={() => props.setDropHint(null)}
          onDrop={(e) => {
            e.preventDefault();
            props.setDropHint(null);
            if (dragging && canDropBefore) props.onDrop(dragging, parentPath, idx);
            props.setDragging(null);
          }}
        />
      )}
      <div
        className={
          "se-row" +
          (isSelected ? " selected" : "") +
          (hasError ? " error" : "") +
          (dropHint === `into:${key}` ? " drop-into" : "")
        }
        style={{ paddingLeft: `${0.4 + depth * 1.1}rem` }}
        draggable={!isRegion}
        onDragStart={(e) => {
          if (isRegion) return;
          e.dataTransfer.effectAllowed = "move";
          props.setDragging(path);
        }}
        onDragEnd={() => {
          props.setDragging(null);
          props.setDropHint(null);
        }}
        onDragOver={(e) => {
          if (canDropInto) {
            e.preventDefault();
            props.setDropHint(`into:${key}`);
          }
        }}
        onDragLeave={() => {
          if (dropHint === `into:${key}`) props.setDropHint(null);
        }}
        onDrop={(e) => {
          e.preventDefault();
          props.setDropHint(null);
          if (dragging && canDropInto) props.onDrop(dragging, path, children.length);
          props.setDragging(null);
        }}
        onClick={() => !isRegion && props.onSelect(path)}
      >
        <button
          className="se-twisty"
          onClick={(e) => {
            e.stopPropagation();
            props.onToggle(key);
          }}
          disabled={!canHaveChildren && children.length === 0}
          title={isOpen ? "Collapse" : "Expand"}
        >
          {children.length > 0 || canHaveChildren ? (isOpen ? "▾" : "▸") : "·"}
        </button>
        {!isRegion && <span className="se-handle" title="Drag to move">⋮⋮</span>}
        <span className={"se-type" + (isRegion ? " region" : "")}>{typeLabel(entry.type as string | undefined, entry.region as string | undefined)}</span>
        <span className="se-title">{isRegion ? "" : String(entry.title ?? entry.id ?? "(untitled)")}</span>
        {!isRegion && entry.id && <span className="muted se-id">{String(entry.id)}</span>}
        {hasError && <span className="badge err">invalid</span>}
        {!isRegion && (
          <span className="se-btns" onClick={(e) => e.stopPropagation()}>
            <button title="Move up" disabled={idx === 0} onClick={() => props.onShift(path, -1)}>↑</button>
            <button title="Move down" disabled={idx >= siblings - 1} onClick={() => props.onShift(path, 1)}>↓</button>
            <button title="Outdent (move after parent)" disabled={path.length < 3} onClick={() => props.onOutdent(path)}>⇤</button>
            <button title="Indent (into previous section)" disabled={idx === 0} onClick={() => props.onIndent(path)}>⇥</button>
            <button title="Remove section" className="danger" onClick={() => props.onRemove(path)}>✕</button>
          </span>
        )}
        {canHaveChildren && (
          <span className="se-add" onClick={(e) => e.stopPropagation()}>
            <button className="small" onClick={() => setAddOpen((o) => !o)} title="Add a section here">
              + add
            </button>
            {addOpen && (
              <div className="se-menu">
                {props.allowedChildren(entry).map((t) => (
                  <button
                    key={t}
                    className="link"
                    onClick={() => {
                      setAddOpen(false);
                      props.onAddChild(path, t);
                    }}
                  >
                    {t}
                  </button>
                ))}
              </div>
            )}
          </span>
        )}
      </div>
      {isOpen &&
        children.map((c, i) => (
          <OutlineNode
            key={`${i}-${c.id ?? c.region ?? "n"}`}
            {...props}
            entry={c}
            path={[...path, i]}
            depth={depth + 1}
            parent={entry}
          />
        ))}
      {/* drop zone: append at the end of an open container */}
      {isOpen && canHaveChildren && (
        <div
          className={"se-drop end" + (dropHint === `end:${key}` ? " on" : "") + (dragging && !canDropInto ? " no" : "")}
          style={{ marginLeft: `${1.5 + depth * 1.1}rem` }}
          onDragOver={(e) => {
            if (canDropInto) {
              e.preventDefault();
              props.setDropHint(`end:${key}`);
            }
          }}
          onDragLeave={() => props.setDropHint(null)}
          onDrop={(e) => {
            e.preventDefault();
            props.setDropHint(null);
            if (dragging && canDropInto) props.onDrop(dragging, path, children.length);
            props.setDragging(null);
          }}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Inspector: title + bindings for the selected node
// ---------------------------------------------------------------------------

function Inspector({
  node,
  parent,
  catalog,
  doc,
  path,
  onChange,
}: {
  node: DocEntry;
  parent: DocEntry | null;
  catalog: DocumentCatalog;
  doc: DocEntry[];
  path: Path;
  onChange: (key: string, value: string) => void;
}) {
  const type = node.type ? String(node.type) : "";
  const ct: CatalogType | undefined = catalog.types[type];
  const required = ct?.requires ?? [];
  const optional = [
    ...(OPTIONAL_KEYS[type] ?? []),
    ...(ct?.orientable ? ["orientation"] : []),
  ].filter((k) => !required.includes(k));
  const ids = allIds(doc);
  const idDup = typeof node.id === "string" && [...ids].filter((x) => x === node.id).length > 1;
  const vocabFor = (key: string): string[] => {
    switch (key) {
      case "platform":
        return catalog.vocab.platforms;
      case "data_key":
        return catalog.vocab.data_keys;
      case "narrative_key":
        return catalog.vocab.narrative_keys;
      case "methods_key":
        return catalog.vocab.methods_keys;
      case "subtype":
        return catalog.vocab.subtypes;
      case "orientation":
        return catalog.vocab.orientations;
      default:
        return [];
    }
  };
  const field = (key: string, isRequired: boolean) => {
    const list = vocabFor(key);
    const listId = `se-vocab-${key}`;
    const val = node[key] == null ? "" : String(node[key]);
    return (
      <label key={key} className="se-field">
        <span>
          {KEY_LABELS[key] ?? key}
          {isRequired && <em className="se-req"> required</em>}
        </span>
        {key === "orientation" ? (
          <select id={`se-${path.join("-")}-${key}`} value={val} onChange={(e) => onChange(key, e.target.value)}>
            <option value="">(default)</option>
            {list.map((v) => (
              <option key={v} value={v}>{v}</option>
            ))}
          </select>
        ) : (
          <>
            <input
              id={`se-${path.join("-")}-${key}`}
              list={list.length ? listId : undefined}
              value={val}
              placeholder={isRequired ? "required" : ""}
              onChange={(e) => onChange(key, e.target.value)}
            />
            {list.length > 0 && (
              <datalist id={listId}>
                {list.map((v) => (
                  <option key={v} value={v} />
                ))}
              </datalist>
            )}
          </>
        )}
      </label>
    );
  };

  return (
    <div className="se-inspector-body">
      <div className="se-inspector-head">
        <span className="se-type">{type || "node"}</span>
        {parent && <span className="muted"> in {String(parent.title ?? parent.region ?? parent.id ?? "")}</span>}
      </div>
      <label className="se-field">
        <span>Title</span>
        <input id={`se-${path.join("-")}-title`} value={String(node.title ?? "")} onChange={(e) => onChange("title", e.target.value)} />
      </label>
      <label className="se-field">
        <span>Id <em className="muted">(anchor for cross-references)</em></span>
        <input id={`se-${path.join("-")}-id`} value={String(node.id ?? "")} onChange={(e) => onChange("id", e.target.value)} />
        {idDup && <em className="se-req">duplicate id</em>}
      </label>
      {required.map((k) => field(k, true))}
      {optional.map((k) => field(k, false))}
      {ct && (
        <p className="muted se-caps">
          {ct.orientable ? "orientable · " : ""}
          {ct.breakable ? "may start a new page · " : ""}
          {ct.editable ? "editable prose · " : ""}
          {ct.captionable ? "captioned · " : ""}
          {ct.allowed_children.length ? `may contain: ${ct.allowed_children.join(", ")}` : "no children"}
        </p>
      )}
    </div>
  );
}
