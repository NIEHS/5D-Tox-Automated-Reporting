import { useCallback, useEffect, useState } from "react";
import {
  api,
  FrontMatter,
  FrontMatterAuthor,
  FrontMatterContributor,
} from "../api";
import { invalidate } from "../useServerResource";
import { ErrorBox, Spinner, StepProps } from "./shared";

// The document configurator: edits per-report human-set FRONT-MATTER METADATA
// (authors, contributors, publication overrides) that the study pipeline can't
// derive, and the DOCUMENT STRUCTURE (the session's document YAML). Two tabs over
// one surface. Saving re-materializes the preview so the About This Report /
// Publication Details sections fill.

type Tab = "front-matter" | "structure";

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
      </div>

      {tab === "front-matter" ? (
        <FrontMatterEditor dtxsid={dtxsid} />
      ) : (
        <StructureEditor dtxsid={dtxsid} />
      )}

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

// ── Document structure: session YAML editor over the existing config route ──
function StructureEditor({ dtxsid }: { dtxsid: string }) {
  const [yaml, setYaml] = useState("");
  const [isDefault, setIsDefault] = useState(true);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const load = useCallback(
    async (loadDefault = false) => {
      setLoading(true);
      setError(null);
      try {
        const r = await api.getDocumentConfig(dtxsid, loadDefault);
        setYaml(r.yaml);
        setIsDefault(r.is_default);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    },
    [dtxsid]
  );

  useEffect(() => {
    void load();
  }, [load]);

  async function save() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await api.saveDocumentConfig(dtxsid, yaml);
      setIsDefault(false);
      await invalidate(dtxsid);
      try {
        await api.materializePreview(dtxsid);
      } catch {
        /* best-effort */
      }
      setSaved(true);
    } catch (e) {
      // 422 validation message surfaces here; the previous structure is intact.
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <Spinner label="Loading structure…" />;

  return (
    <div className="configure-form">
      <p className="help" style={{ marginTop: 0 }}>
        The document structure as YAML (sections, order, table numbering).{" "}
        {isDefault ? (
          <em>Showing the shared default — saving creates this session's own copy.</em>
        ) : (
          <em>This session's saved structure.</em>
        )}{" "}
        Invalid edits are rejected with a message; the current structure stays intact.
      </p>
      <ErrorBox error={error} />
      <textarea
        className="query-editor structure-editor"
        value={yaml}
        spellCheck={false}
        onChange={(e) => setYaml(e.target.value)}
        rows={22}
      />
      <div className="config-save">
        <button className="primary" onClick={save} disabled={saving}>
          {saving ? <Spinner label="Validating…" /> : "Save structure"}
        </button>
        <button onClick={() => load(true)} disabled={saving}>
          Load default
        </button>
        {saved && <span className="badge ok">saved</span>}
      </div>
    </div>
  );
}
