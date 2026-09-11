import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, SectionData, SessionLoad } from "../api";
import { useSectionReadiness } from "../useSectionReadiness";
import { useServerResource, invalidate } from "../useServerResource";
import { ErrorBox, Spinner, StepProps } from "./shared";

// The document workstream's SECTIONS surface (ADR-0018). The app is NOT an editor:
// this is a READ-ONLY status view that GENERATES authored sections (Background,
// M&M) once their dependencies are satisfied and MATERIALIZES the apical result
// sections from the Process cache. Human editing happens EXTERNALLY (Word/Overleaf)
// after handoff — there are no editors, no accept/revise here. It feeds Preview.

const FRONT_MATTER: { key: string; label: string; note: string }[] = [
  { key: "background", label: "Background", note: "Generated from the test-article identity." },
  { key: "methods", label: "Materials & Methods", note: "Generated from study metadata after Process." },
  { key: "summary", label: "Summary", note: "Synthesizes approved sections." },
];

function sectionContent(session: SessionLoad | null, key: string): SectionData | null {
  if (!session) return null;
  if (key.startsWith("bm2_")) return session.bm2_sections?.[key.slice("bm2_".length)] ?? null;
  return (session[key] as SectionData | null) ?? null;
}

function humanizeKey(key: string): string {
  if (key.startsWith("bm2_")) {
    return key.slice("bm2_".length).replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  }
  return key.replace(/\b\w/g, (c) => c.toUpperCase());
}

// One read-only section row: shows its derived state as a badge + a paragraph count.
function SectionRow({
  label,
  note,
  enabled,
  approved,
  blockedBy,
  content,
  busy,
}: {
  label: string;
  note?: string;
  enabled: boolean;
  approved: boolean;
  blockedBy: string[];
  content: SectionData | null;
  busy?: boolean;
}) {
  const paras = content?.paragraphs?.length ?? content?.narrative?.length ?? 0;
  const hasContent = paras > 0 || !!content;
  let state: { cls: string; text: string };
  if (busy) state = { cls: "", text: "generating…" };
  else if (!enabled) state = { cls: "", text: "blocked" };
  else if (approved) state = { cls: "ok", text: "approved" };
  else if (hasContent) state = { cls: "ok", text: "generated" };
  else state = { cls: "warn", text: "not generated" };

  return (
    <div className="section-row">
      <div className="section-row-main">
        <strong>{label}</strong>
        {note && <span className="muted section-row-note">{note}</span>}
      </div>
      <div className="section-row-status">
        {busy && <Spinner />}
        <span className={`badge ${state.cls}`}>{state.text}</span>
        {enabled && hasContent && (
          <span className="muted">{paras} paragraph{paras === 1 ? "" : "s"}</span>
        )}
        {!enabled && blockedBy.length > 0 && (
          <span className="muted">needs {blockedBy.join(" or ")}</span>
        )}
      </div>
    </div>
  );
}

export function Sections({ dtxsid, state, next, back }: StepProps) {
  const { readiness } = useSectionReadiness(dtxsid);
  const {
    data: sessionData,
    loading,
    error: loadError,
  } = useServerResource<SessionLoad | null>(
    dtxsid ? `session:${dtxsid}` : null,
    () => api.loadSession(dtxsid as string),
    null
  );
  const session = sessionData ?? null;
  const [error, setError] = useState<string | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);

  const processed = state?.artifacts?.hasProcessed !== false; // best-effort; readiness is authority

  const afterMutation = useCallback(async () => {
    if (!dtxsid) return;
    await invalidate(dtxsid);
    try {
      await api.materializePreview(dtxsid);
    } catch {
      /* preview rebuild is best-effort */
    }
  }, [dtxsid]);

  // --- Auto-generate the authored front-matter sections when generable-empty ---
  // Background (deps: identity) and M&M (deps: processed) both auto-generate once
  // their dependencies are satisfied, mirroring the derived-readiness model. Guarded
  // so a re-pull mid-generation doesn't retrigger.
  const fired = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (!dtxsid || loading) return;
    void maybeGenerate("background");
    void maybeGenerate("methods");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dtxsid, loading, readiness, session]);

  async function maybeGenerate(key: string) {
    if (!dtxsid) return;
    const r = readiness[key];
    const content = sectionContent(session, key);
    const empty = (content?.paragraphs?.length ?? 0) === 0;
    if (!r?.enabled || r?.approved || !empty || fired.current.has(key)) return;
    fired.current.add(key);
    setBusyKey(key);
    try {
      if (key === "background") {
        const { identity } = await api.getIdentity(dtxsid);
        const res = await api.generateBackground(identity);
        const paragraphs = (res.paragraphs as string[]) ?? [];
        if (paragraphs.length) {
          await api.saveSection(dtxsid, "background", { paragraphs, references: res.references ?? [] });
          await afterMutation();
        }
      } else if (key === "methods") {
        const { identity } = await api.getIdentity(dtxsid);
        const res = await api.generateMethods(dtxsid, identity);
        if (res) await afterMutation();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      fired.current.delete(key); // allow retry
    } finally {
      setBusyKey((k) => (k === key ? null : k));
    }
  }

  async function materializeResults() {
    if (!dtxsid) return;
    setBusyKey("results");
    setError(null);
    try {
      await api.materializeSections(dtxsid);
      await afterMutation();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyKey((k) => (k === "results" ? null : k));
    }
  }

  const resultKeys = useMemo(
    () => Object.keys(readiness).filter((k) => k.startsWith("bm2_")).sort(),
    [readiness]
  );
  const genomicsKeys = useMemo(
    () => Object.keys(readiness).filter((k) => k.startsWith("genomics_")).sort(),
    [readiness]
  );

  if (!dtxsid) {
    return (
      <div className="panel">
        <h2>Sections</h2>
        <p className="help">Select a session first.</p>
      </div>
    );
  }

  return (
    <div className="panel">
      <h2>Sections</h2>
      <p className="help">
        The report's sections and their status. Authored sections (Background,
        Materials &amp; Methods) generate automatically once their dependencies are
        met; results are materialized from the processed data. Editing happens
        externally after hand-off — this is a read-only overview.
      </p>

      <ErrorBox error={error ?? loadError} />
      {loading && <Spinner label="Loading sections…" />}

      <h3 className="group-heading">Front matter</h3>
      {FRONT_MATTER.map((fm) => {
        const r = readiness[fm.key];
        return (
          <SectionRow
            key={fm.key}
            label={fm.label}
            note={fm.note}
            enabled={r?.enabled ?? false}
            approved={r?.approved ?? false}
            blockedBy={r?.blocked_by ?? []}
            content={sectionContent(session, fm.key)}
            busy={busyKey === fm.key}
          />
        );
      })}
      {readiness["bmd_summary"] && (
        <SectionRow
          label="Apical BMD Summary"
          note="Auto-derived from results (deterministic)."
          enabled
          approved={false}
          blockedBy={[]}
          content={sectionContent(session, "bmd_summary")}
        />
      )}

      <div className="group-heading-row">
        <h3 className="group-heading">Apical results</h3>
        <button onClick={materializeResults} disabled={busyKey === "results"}>
          {busyKey === "results" ? <Spinner label="Materializing…" /> : "Materialize results"}
        </button>
      </div>
      {resultKeys.length === 0 ? (
        <p className="muted">
          {processed
            ? "No result sections materialized yet — click Materialize results."
            : "Process the pool first to produce result data."}
        </p>
      ) : (
        resultKeys.map((key) => {
          const r = readiness[key];
          return (
            <SectionRow
              key={key}
              label={humanizeKey(key)}
              enabled={r?.enabled ?? true}
              approved={r?.approved ?? false}
              blockedBy={r?.blocked_by ?? []}
              content={sectionContent(session, key)}
            />
          );
        })
      )}

      {genomicsKeys.length > 0 && (
        <>
          <h3 className="group-heading">Genomics (deterministic, read-only)</h3>
          {genomicsKeys.map((key) => {
            const r = readiness[key];
            return (
              <SectionRow
                key={key}
                label={humanizeKey(key)}
                note="Deterministic result — not authored."
                enabled={r?.enabled ?? true}
                approved={false}
                blockedBy={r?.blocked_by ?? []}
                content={null}
              />
            );
          })}
        </>
      )}

      <div className="actions">
        <button onClick={back}>Back</button>
        <button className="primary" onClick={next}>
          Next: Preview
        </button>
      </div>
    </div>
  );
}
