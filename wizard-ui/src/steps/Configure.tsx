import { useCallback, useEffect, useState } from "react";
import {
  api,
  FrontMatter,
  FrontMatterAuthor,
  FrontMatterContributor,
  ReportView,
} from "../api";
import { invalidate } from "../useServerResource";
import { ErrorBox, Spinner, StepProps } from "./shared";
import { StructureEditor } from "./StructureEditor";

// The document configurator: edits per-report human-set FRONT-MATTER METADATA
// (authors, contributors, publication overrides) that the study pipeline can't
// derive, the DOCUMENT STRUCTURE (the session's document YAML), and the DATA
// FILTERS (which sexes/organs/assays/genes/charts appear — a render-time lens,
// no reprocess). Three tabs over one surface. Saving re-materializes the preview
// so the change is reflected.

type Tab = "front-matter" | "structure" | "filters";

export function Configure({ dtxsid, back }: StepProps) {
  const [tab, setTab] = useState<Tab>("front-matter");

  if (!dtxsid) {
    return (
      <div className="panel">
        <h2>Configure</h2>
        <p className="help">Select a session first.</p>
      </div>
    );
  }

  return (
    <div className="panel">
      <h2>Configure the report</h2>
      <p className="help">
        Set the report's authors and publication details, and adjust its document
        structure. These are the parts a person decides — not derived from the study
        data.
      </p>

      <div className="mode-toggle" style={{ marginBottom: "1rem" }}>
        <button
          className={tab === "front-matter" ? "active" : ""}
          onClick={() => setTab("front-matter")}
        >
          Front matter
        </button>
        <button
          className={tab === "structure" ? "active" : ""}
          onClick={() => setTab("structure")}
        >
          Document structure
        </button>
        <button
          className={tab === "filters" ? "active" : ""}
          onClick={() => setTab("filters")}
        >
          Data filters
        </button>
      </div>

      {tab === "front-matter" && <FrontMatterEditor dtxsid={dtxsid} />}
      {tab === "structure" && <StructureEditor dtxsid={dtxsid} />}
      {tab === "filters" && <FiltersEditor dtxsid={dtxsid} />}

      <div className="actions">
        <button onClick={back}>Back</button>
      </div>
    </div>
  );
}

// ── Front-matter: authors roster + contributors + publication overrides ──────
function FrontMatterEditor({ dtxsid }: { dtxsid: string }) {
  const [fm, setFm] = useState<FrontMatter>({
    authors: [],
    contributors: [],
    publication: {},
  });
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .getFrontMatter(dtxsid)
      .then((r) => {
        if (cancelled) return;
        const f = r.front_matter || {};
        setFm({
          authors: f.authors ?? [],
          contributors: f.contributors ?? [],
          publication: f.publication ?? {},
        });
      })
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [dtxsid]);

  const save = useCallback(async () => {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await api.saveFrontMatter(dtxsid, fm);
      await invalidate(dtxsid);
      try {
        await api.materializePreview(dtxsid);
      } catch {
        /* preview rebuild is best-effort */
      }
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }, [dtxsid, fm]);

  // -- authors (ordered roster) --
  const authors = fm.authors ?? [];
  function setAuthor(i: number, patch: Partial<FrontMatterAuthor>) {
    setFm((f) => {
      const next = [...(f.authors ?? [])];
      next[i] = { ...next[i], ...patch };
      return { ...f, authors: next };
    });
  }
  function moveAuthor(i: number, dir: -1 | 1) {
    setFm((f) => {
      const next = [...(f.authors ?? [])];
      const j = i + dir;
      if (j < 0 || j >= next.length) return f;
      [next[i], next[j]] = [next[j], next[i]];
      return { ...f, authors: next };
    });
  }
  function addAuthor() {
    setFm((f) => ({
      ...f,
      authors: [...(f.authors ?? []), { name: "", role: "", affiliation: "" }],
    }));
  }
  function removeAuthor(i: number) {
    setFm((f) => ({ ...f, authors: (f.authors ?? []).filter((_, k) => k !== i) }));
  }

  // -- contributors --
  const contributors = fm.contributors ?? [];
  function setContributor(i: number, patch: Partial<FrontMatterContributor>) {
    setFm((f) => {
      const next = [...(f.contributors ?? [])];
      next[i] = { ...next[i], ...patch };
      return { ...f, contributors: next };
    });
  }
  function addContributor() {
    setFm((f) => ({
      ...f,
      contributors: [...(f.contributors ?? []), { name: "", role: "" }],
    }));
  }
  function removeContributor(i: number) {
    setFm((f) => ({
      ...f,
      contributors: (f.contributors ?? []).filter((_, k) => k !== i),
    }));
  }

  const pub = fm.publication ?? {};
  function setPub(patch: Partial<NonNullable<FrontMatter["publication"]>>) {
    setFm((f) => ({ ...f, publication: { ...(f.publication ?? {}), ...patch } }));
  }

  if (loading) return <Spinner label="Loading front matter…" />;

  return (
    <div className="configure-form">
      <ErrorBox error={error} />

      <section className="config-group">
        <div className="group-heading-row">
          <h3 className="group-heading">Authors</h3>
          <button onClick={addAuthor}>+ Add author</button>
        </div>
        <p className="help" style={{ marginTop: 0 }}>
          Listed in order. Use ↑ ↓ to reorder — the order is the author order on the
          report.
        </p>
        {authors.length === 0 && <p className="muted">No authors yet.</p>}
        {authors.map((a, i) => (
          <div key={i} className="roster-row">
            <span className="roster-pos">{i + 1}</span>
            <input
              placeholder="Full name"
              value={a.name ?? ""}
              onChange={(e) => setAuthor(i, { name: e.target.value })}
            />
            <input
              placeholder="Role (e.g. Study Scientist)"
              value={a.role ?? ""}
              onChange={(e) => setAuthor(i, { role: e.target.value })}
            />
            <input
              placeholder="Affiliation"
              value={a.affiliation ?? ""}
              onChange={(e) => setAuthor(i, { affiliation: e.target.value })}
            />
            <div className="roster-actions">
              <button onClick={() => moveAuthor(i, -1)} disabled={i === 0} title="Move up">
                ↑
              </button>
              <button
                onClick={() => moveAuthor(i, 1)}
                disabled={i === authors.length - 1}
                title="Move down"
              >
                ↓
              </button>
              <button onClick={() => removeAuthor(i)} title="Remove">
                ✕
              </button>
            </div>
          </div>
        ))}
      </section>

      <section className="config-group">
        <div className="group-heading-row">
          <h3 className="group-heading">Contributors</h3>
          <button onClick={addContributor}>+ Add contributor</button>
        </div>
        {contributors.length === 0 && <p className="muted">No contributors yet.</p>}
        {contributors.map((c, i) => (
          <div key={i} className="roster-row">
            <input
              placeholder="Full name"
              value={c.name ?? ""}
              onChange={(e) => setContributor(i, { name: e.target.value })}
            />
            <input
              placeholder="Role (e.g. Peer Reviewer)"
              value={c.role ?? ""}
              onChange={(e) => setContributor(i, { role: e.target.value })}
            />
            <div className="roster-actions">
              <button onClick={() => removeContributor(i)} title="Remove">
                ✕
              </button>
            </div>
          </div>
        ))}
      </section>

      <section className="config-group">
        <h3 className="group-heading">Publication details</h3>
        <p className="help" style={{ marginTop: 0 }}>
          Overrides the "to be assigned" placeholders. Leave blank to keep them.
        </p>
        <div className="field-row">
          <label>
            Report series number
            <input
              value={pub.report_number ?? ""}
              onChange={(e) => setPub({ report_number: e.target.value })}
            />
          </label>
          <label>
            DOI
            <input value={pub.doi ?? ""} onChange={(e) => setPub({ doi: e.target.value })} />
          </label>
          <label>
            Publication date
            <input
              value={pub.report_date ?? ""}
              onChange={(e) => setPub({ report_date: e.target.value })}
            />
          </label>
        </div>
      </section>

      <div className="config-save">
        <button className="primary" onClick={save} disabled={saving}>
          {saving ? <Spinner label="Saving…" /> : "Save front matter"}
        </button>
        {saved && <span className="badge ok">saved</span>}
      </div>
    </div>
  );
}

// ── Document structure: the visual editor lives in ./StructureEditor ──────────

// ── Data filters: per-report VIEWS (session scope) or the template default ────
// Filters are a render-time lens over the one report (no reprocess). Session
// scope edits saved VIEWS via /api/views; default scope edits the template's
// filter blocks via /api/report-filters-default (raw YAML, comments stripped).
type FilterScope = "session" | "default";

// The sex areas + charts vocabulary are CLOSED sets → structured controls; the
// open token lists (organs/assays/genes/gene_sets) are comma-separated inputs
// (the server canonicalizes the friendly {area:[tokens]} / [tokens] shapes).
const SEX_AREAS = ["apical", "genomics"] as const;
const SEXES = ["male", "female"] as const;
const CHART_TYPES = ["umap", "cluster"] as const;
const ORGAN_AREAS = ["genomics", "organ-weight"] as const;
const ASSAY_AREAS = ["clinical-chemistry", "hematology"] as const;

// Comma-separated token list <-> array. Blank ⇒ [] (no filtering for that block).
function tokensToText(tokens: unknown): string {
  return Array.isArray(tokens) ? (tokens as string[]).join(", ") : "";
}
function textToTokens(text: string): string[] {
  return text
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}
// Collapse a canonical per-area block {area: {sex_key: [tokens]}} back to the
// friendly {area: [tokens]} the inputs show (union across sex keys).
function areaTokens(block: unknown, area: string): string[] {
  const areaMap = ((block as Record<string, unknown>) ?? {})[area];
  if (Array.isArray(areaMap)) return areaMap as string[];
  const out = new Set<string>();
  for (const v of Object.values((areaMap ?? {}) as Record<string, unknown>)) {
    for (const t of (v as string[]) ?? []) out.add(String(t));
  }
  return [...out];
}
function flatTokens(block: unknown): string[] {
  if (Array.isArray(block)) return block as string[];
  // canonical {"*": {"*": [tokens]}}
  const star = ((block as Record<string, unknown>) ?? {})["*"];
  if (Array.isArray(star)) return star as string[];
  const inner = ((star as Record<string, unknown>) ?? {})["*"];
  return Array.isArray(inner) ? (inner as string[]) : [];
}

function FiltersEditor({ dtxsid }: { dtxsid: string }) {
  const [scope, setScope] = useState<FilterScope>("session");
  return (
    <div className="configure-form">
      <div className="doc-config-scope" style={{ marginBottom: "1rem" }}>
        <label>
          <input
            type="radio"
            name="filters-scope"
            checked={scope === "session"}
            onChange={() => setScope("session")}
          />{" "}
          This report (views)
        </label>
        <label style={{ marginLeft: "1rem" }}>
          <input
            type="radio"
            name="filters-scope"
            checked={scope === "default"}
            onChange={() => setScope("default")}
          />{" "}
          Default (all reports)
        </label>
      </div>
      {scope === "session" ? (
        <SessionFiltersEditor dtxsid={dtxsid} />
      ) : (
        <DefaultFiltersEditor />
      )}
    </div>
  );
}

// -- Session scope: a named-view manager over /api/views --
function SessionFiltersEditor({ dtxsid }: { dtxsid: string }) {
  const [views, setViews] = useState<string[]>(["default"]);
  const [active, setActive] = useState("default");
  // The active view's filters: closed-vocab (sex/charts) + open-vocab token maps.
  const [sex, setSex] = useState<Record<string, string[]>>({});
  const [charts, setCharts] = useState<string[] | null>(null);
  // Open-vocab blocks as comma-separated text, keyed by area (organs/assays) or
  // "genes"/"gene_sets" (flat lists).
  const [organs, setOrgans] = useState<Record<string, string>>({});
  const [assays, setAssays] = useState<Record<string, string>>({});
  const [genes, setGenes] = useState("");
  const [geneSets, setGeneSets] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const loadViews = useCallback(async () => {
    const r = await api.listViews(dtxsid);
    setViews(r.views);
  }, [dtxsid]);

  const loadView = useCallback(
    async (name: string) => {
      setLoading(true);
      setError(null);
      setSaved(false);
      try {
        const { view } = await api.getView(dtxsid, name);
        const f = (view.filters ?? {}) as Record<string, unknown>;
        // sex: canonical is {area: {sex_key: [tokens]}}; collapse to {area:[sexes]}
        // for the checkboxes (a sex appears if it's allowlisted under any sex_key).
        const sexBlock = (f.sex ?? {}) as Record<string, unknown>;
        const nextSex: Record<string, string[]> = {};
        for (const area of SEX_AREAS) {
          const areaMap = (sexBlock[area] ?? {}) as Record<string, unknown>;
          const present = new Set<string>();
          for (const v of Object.values(areaMap)) {
            for (const t of (v as string[]) ?? []) present.add(String(t).toLowerCase());
          }
          if (present.size) nextSex[area] = [...present];
        }
        setSex(nextSex);
        setCharts(view.charts ?? null);
        // Open-vocab blocks → comma-separated inputs (canonical shapes collapsed).
        const nextOrgans: Record<string, string> = {};
        for (const area of ORGAN_AREAS)
          nextOrgans[area] = tokensToText(areaTokens(f.organs, area));
        setOrgans(nextOrgans);
        const nextAssays: Record<string, string> = {};
        for (const area of ASSAY_AREAS)
          nextAssays[area] = tokensToText(areaTokens(f.assays, area));
        setAssays(nextAssays);
        setGenes(tokensToText(flatTokens(f.genes)));
        setGeneSets(tokensToText(flatTokens(f.gene_sets)));
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    },
    [dtxsid]
  );

  useEffect(() => {
    void loadViews();
  }, [loadViews]);
  useEffect(() => {
    void loadView(active);
  }, [active, loadView]);

  function toggleSex(area: string, s: string) {
    setSex((cur) => {
      const have = new Set(cur[area] ?? []);
      if (have.has(s)) have.delete(s);
      else have.add(s);
      const next = { ...cur };
      if (have.size) next[area] = [...have];
      else delete next[area];
      return next;
    });
  }

  function toggleChart(t: string) {
    setCharts((cur) => {
      // null = "render all". First explicit pick starts an allowlist.
      const have = new Set(cur ?? []);
      if (have.has(t)) have.delete(t);
      else have.add(t);
      return [...have];
    });
  }

  async function save() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      // Compose the friendly filters block from the structured fields; the server
      // canonicalizes + validates it (normalize_filters_block). Empty areas/lists
      // are omitted ⇒ no filtering for that block.
      const filters: Record<string, unknown> = {};

      const sexBlock: Record<string, string[]> = {};
      for (const area of SEX_AREAS) if (sex[area]?.length) sexBlock[area] = sex[area];
      if (Object.keys(sexBlock).length) filters.sex = sexBlock;

      const organBlock: Record<string, string[]> = {};
      for (const area of ORGAN_AREAS) {
        const toks = textToTokens(organs[area] ?? "");
        if (toks.length) organBlock[area] = toks;
      }
      if (Object.keys(organBlock).length) filters.organs = organBlock;

      const assayBlock: Record<string, string[]> = {};
      for (const area of ASSAY_AREAS) {
        const toks = textToTokens(assays[area] ?? "");
        if (toks.length) assayBlock[area] = toks;
      }
      if (Object.keys(assayBlock).length) filters.assays = assayBlock;

      const geneToks = textToTokens(genes);
      if (geneToks.length) filters.genes = geneToks;
      const geneSetToks = textToTokens(geneSets);
      if (geneSetToks.length) filters.gene_sets = geneSetToks;

      const view: ReportView = { filters };
      if (charts !== null) view.charts = charts; // presence-sensitive
      await api.saveView(dtxsid, active, view);
      await invalidate(dtxsid);
      try {
        await api.materializePreview(dtxsid, "docx", active);
      } catch {
        /* preview rebuild is best-effort */
      }
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  async function newView() {
    const name = window.prompt("New view name (e.g. male-only):")?.trim();
    if (!name) return;
    setError(null);
    try {
      await api.saveView(dtxsid, name, { filters: {} });
      await loadViews();
      setActive(name);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function deleteActive() {
    if (active === "default") return;
    if (!window.confirm(`Delete view "${active}"?`)) return;
    setError(null);
    try {
      await api.deleteView(dtxsid, active);
      await loadViews();
      setActive("default");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div>
      <p className="help" style={{ marginTop: 0 }}>
        A <strong>view</strong> is a saved lens over the one report — which sexes,
        organs, assays, genes, and charts appear. Filters apply at render time (no
        reprocess). The <code>default</code> view is what every surface shows unless
        you pick another.
      </p>

      <div className="field-row" style={{ alignItems: "flex-end" }}>
        <label>
          View
          <select value={active} onChange={(e) => setActive(e.target.value)}>
            {views.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <button onClick={newView}>+ New view</button>
        <button onClick={deleteActive} disabled={active === "default"} title="Delete view">
          Delete
        </button>
      </div>

      <ErrorBox error={error} />
      {loading ? (
        <Spinner label="Loading view…" />
      ) : (
        <>
          <section className="config-group">
            <h3 className="group-heading">Sex</h3>
            <p className="help" style={{ marginTop: 0 }}>
              Limit which sexes appear. No box checked ⇒ both (no filtering).
            </p>
            {SEX_AREAS.map((area) => (
              <div key={area} className="field-row">
                <span style={{ minWidth: "6rem", textTransform: "capitalize" }}>
                  {area}
                </span>
                {SEXES.map((s) => (
                  <label key={s} style={{ marginRight: "1rem" }}>
                    <input
                      type="checkbox"
                      checked={(sex[area] ?? []).includes(s)}
                      onChange={() => toggleSex(area, s)}
                    />{" "}
                    {s}
                  </label>
                ))}
              </div>
            ))}
          </section>

          <section className="config-group">
            <h3 className="group-heading">Charts</h3>
            <p className="help" style={{ marginTop: 0 }}>
              {charts === null ? (
                <em>Rendering all produced charts (no allowlist).</em>
              ) : (
                <em>
                  Allowlist active — only checked types render (none checked ⇒ no
                  charts).
                </em>
              )}
            </p>
            {CHART_TYPES.map((t) => (
              <label key={t} style={{ marginRight: "1rem" }}>
                <input
                  type="checkbox"
                  checked={(charts ?? []).includes(t)}
                  onChange={() => toggleChart(t)}
                />{" "}
                {t}
              </label>
            ))}
            {charts !== null && (
              <button
                style={{ marginLeft: "1rem" }}
                onClick={() => setCharts(null)}
                title="Clear the allowlist (render all charts)"
              >
                Reset to all
              </button>
            )}
          </section>

          <section className="config-group">
            <h3 className="group-heading">Organs</h3>
            <p className="help" style={{ marginTop: 0 }}>
              Comma-separated tokens per area. Empty ⇒ no filtering. Matching is
              component-aware (e.g. <code>kidney</code> covers "Kidney-Left").
            </p>
            {ORGAN_AREAS.map((area) => (
              <label key={area} className="field-row" style={{ display: "flex", gap: ".5rem" }}>
                <span style={{ minWidth: "8rem" }}>{area}</span>
                <input
                  style={{ flex: 1 }}
                  placeholder="e.g. liver, kidney"
                  value={organs[area] ?? ""}
                  onChange={(e) => setOrgans((o) => ({ ...o, [area]: e.target.value }))}
                />
              </label>
            ))}
          </section>

          <section className="config-group">
            <h3 className="group-heading">Assays</h3>
            <p className="help" style={{ marginTop: 0 }}>
              Comma-separated endpoint tokens per area (Hormones always shown in
              full). Empty ⇒ no filtering.
            </p>
            {ASSAY_AREAS.map((area) => (
              <label key={area} className="field-row" style={{ display: "flex", gap: ".5rem" }}>
                <span style={{ minWidth: "8rem" }}>{area}</span>
                <input
                  style={{ flex: 1 }}
                  placeholder="e.g. cholesterol, neutrophil count"
                  value={assays[area] ?? ""}
                  onChange={(e) => setAssays((a) => ({ ...a, [area]: e.target.value }))}
                />
              </label>
            ))}
          </section>

          <section className="config-group">
            <h3 className="group-heading">Genes &amp; gene sets</h3>
            <p className="help" style={{ marginTop: 0 }}>
              Comma-separated, genomics only. Empty ⇒ no filtering. Gene sets match a
              GO accession or a term component (<code>cell division</code>).
            </p>
            <label className="field-row" style={{ display: "flex", gap: ".5rem" }}>
              <span style={{ minWidth: "8rem" }}>genes</span>
              <input
                style={{ flex: 1 }}
                placeholder="e.g. egr1, ddit4"
                value={genes}
                onChange={(e) => setGenes(e.target.value)}
              />
            </label>
            <label className="field-row" style={{ display: "flex", gap: ".5rem" }}>
              <span style={{ minWidth: "8rem" }}>gene sets</span>
              <input
                style={{ flex: 1 }}
                placeholder='e.g. GO:0051301, cell division'
                value={geneSets}
                onChange={(e) => setGeneSets(e.target.value)}
              />
            </label>
          </section>

          <div className="config-save">
            <button className="primary" onClick={save} disabled={saving}>
              {saving ? <Spinner label="Saving…" /> : `Save "${active}"`}
            </button>
            {saved && <span className="badge ok">saved</span>}
          </div>
        </>
      )}
    </div>
  );
}

// -- Default scope: raw YAML over the six template filter blocks --
function DefaultFiltersEditor() {
  const [yaml, setYaml] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await api.getReportFiltersDefault();
      setYaml(r.yaml);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function save() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await api.saveReportFiltersDefault(yaml);
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <Spinner label="Loading default filters…" />;

  return (
    <div>
      <p className="help" style={{ marginTop: 0 }}>
        The <strong>template default</strong> filter blocks (organs, sex, assays,
        genes, gene_sets, charts) every report inherits without its own view. Saving
        rewrites the committed template and <em>strips YAML comments</em> — review the
        git diff before committing. Invalid areas/shapes are rejected.
      </p>
      <ErrorBox error={error} />
      <textarea
        className="query-editor structure-editor"
        value={yaml}
        spellCheck={false}
        onChange={(e) => setYaml(e.target.value)}
        rows={20}
      />
      <div className="config-save">
        <button className="primary" onClick={save} disabled={saving}>
          {saving ? <Spinner label="Validating…" /> : "Save default filters"}
        </button>
        <button onClick={() => void load()} disabled={saving}>
          Reload
        </button>
        {saved && <span className="badge ok">saved</span>}
      </div>
    </div>
  );
}
