import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, SectionData, SessionLoad } from "../api";
import { useSectionReadiness } from "../useSectionReadiness";
import { useServerResource, invalidate } from "../useServerResource";
import { ErrorBox, Spinner, StepProps, WarningBox } from "./shared";

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

// How much prose a section holds, whatever shape it uses: a flat paragraph list
// (background, summary), a `narrative` list (materialized apical results), or
// per-subsection paragraphs (Materials & Methods). Counting only the flat list
// made Methods read as "0 paragraphs" — and, since the auto-generate check used
// the same test, re-called the model on every visit until it was approved.
function paragraphCount(content: SectionData | null): number {
  if (!content) return 0;
  if (content.paragraphs?.length) return content.paragraphs.length;
  if (content.narrative?.length) return content.narrative.length;
  if (content.sections?.length) {
    return content.sections.reduce((n, s) => n + (s.paragraphs?.length ?? 0), 0);
  }
  if (content.endpoints?.length) return content.endpoints.length;
  return 0;
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
  onApprove,
  onRevise,
  acting,
  unit = "paragraph",
}: {
  label: string;
  note?: string;
  enabled: boolean;
  approved: boolean;
  blockedBy: string[];
  content: SectionData | null;
  busy?: boolean;
  // Provisional-approval controls (ADR-0018 / ADR-0015): "Approve" blesses the
  // generated state as known-good (unlocking sections gated on it, e.g. Summary);
  // "Revise" releases it again. Omitted for rows that are not approvable
  // (deterministic genomics results have no authored content to bless).
  onApprove?: () => void;
  onRevise?: () => void;
  acting?: boolean;
  // Noun for the content count ("paragraph" by default; "endpoint" for the
  // derived BMD summary table).
  unit?: string;
}) {
  const paras = paragraphCount(content);
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
          <span className="muted">{paras} {unit}{paras === 1 ? "" : "s"}</span>
        )}
        {!enabled && blockedBy.length > 0 && (
          <span className="muted">needs {blockedBy.join(" or ")}</span>
        )}
        {enabled && !approved && hasContent && onApprove && (
          <button className="small" onClick={onApprove} disabled={acting || busy} title="Provisionally approve this generated section">
            {acting ? "…" : "Approve"}
          </button>
        )}
        {approved && onRevise && (
          <button className="small" onClick={onRevise} disabled={acting} title="Release the approval so the section can be regenerated">
            {acting ? "…" : "Revise"}
          </button>
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
  // Citation verification notice: unresolved Background / genomics citations
  // the author should look at (non-blocking). Refreshed whenever the session
  // reloads, i.e. after every generate/approve mutation.
  const [citationWarning, setCitationWarning] = useState<string | null>(null);
  useEffect(() => {
    if (!dtxsid) return;
    let cancelled = false;
    api
      .getCitationWarnings(dtxsid)
      .then((w) => {
        if (cancelled) return;
        if (!w.count) {
          setCitationWarning(null);
          return;
        }
        const lines: string[] = [];
        for (const b of w.background) {
          lines.push(`Background ${b.token} (${b.issue.replace(/_/g, " ")}): ${b.sentence}`);
        }
        for (const g of w.genomics) {
          const who = `${g.organ}${g.sex ? "/" + g.sex : ""} ${g.kind}`;
          const first = g.sentences && g.sentences.length ? " — " + g.sentences[0] : "";
          lines.push(`Genomics ${who} (${g.issue.replace(/_/g, " ")}): [${g.tokens.join(", ")}]${first}`);
        }
        setCitationWarning(`${w.count} unresolved citation(s) need review:\n` + lines.join("\n"));
      })
      .catch(() => {
        if (!cancelled) setCitationWarning(null);
      });
    return () => {
      cancelled = true;
    };
  }, [dtxsid, session]);

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
    void maybeGenerate("summary"); // no-op until readiness unlocks it
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dtxsid, loading, readiness, session]);

  async function maybeGenerate(key: string) {
    if (!dtxsid) return;
    const r = readiness[key];
    const content = sectionContent(session, key);
    const empty = paragraphCount(content) === 0;
    if (!r?.enabled || r?.approved || !empty || fired.current.has(key)) return;
    fired.current.add(key);
    setBusyKey(key);
    try {
      if (key === "background") {
        const { identity } = await api.getIdentity(dtxsid);
        const res = await api.generateBackground(identity);
        const paragraphs = (res.paragraphs as string[]) ?? [];
        if (paragraphs.length) {
          await api.saveSection(dtxsid, "background", {
            paragraphs,
            references: res.references ?? [],
            // Persist the verification record so the citation-warnings route
            // (and the notice below) can show unresolved citations after reload.
            citation_report: res.citation_report ?? null,
          });
          await afterMutation();
        }
      } else if (key === "methods") {
        const { identity } = await api.getIdentity(dtxsid);
        const res = await api.generateMethods(dtxsid, identity);
        if (res) await afterMutation();
      } else if (key === "summary") {
        // Synthesizes the APPROVED sections; readiness gates this on an approved
        // Background or result, so it never runs on an empty session.
        const { identity } = await api.getIdentity(dtxsid);
        const res = await api.generateSummary(dtxsid, identity);
        if (res.paragraphs?.length) {
          await api.saveSection(dtxsid, "summary", { paragraphs: res.paragraphs, model_used: res.model_used ?? "" });
          await afterMutation();
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      fired.current.delete(key); // allow retry
    } finally {
      setBusyKey((k) => (k === key ? null : k));
    }
  }

  // Map a readiness key to the approve/unapprove API's (section_type, extra).
  // Singletons map to themselves; apical results are `bm2_<slug>`; genomics
  // instances are deterministic and not offered for approval here.
  function approvalTarget(key: string): { sectionType: string; extra: { bm2_slug?: string } } | null {
    if (key.startsWith("bm2_")) return { sectionType: "bm2", extra: { bm2_slug: key.slice("bm2_".length) } };
    if (["background", "methods", "bmd_summary", "summary"].includes(key)) return { sectionType: key, extra: {} };
    return null;
  }

  const [actingKey, setActingKey] = useState<string | null>(null);

  // Apical BMD Summary is DERIVED from the bm2_* results until it is approved
  // (which persists it as bmd_summary.json). Fetch the derivation so the row
  // shows its endpoint count and can be approved; once persisted, the session
  // payload wins.
  const [bmdDerived, setBmdDerived] = useState<SectionData | null>(null);
  useEffect(() => {
    if (!dtxsid || !readiness["bmd_summary"] || session?.bmd_summary) {
      setBmdDerived(null);
      return;
    }
    let cancelled = false;
    api
      .getBmdSummary(dtxsid)
      .then((d) => {
        if (!cancelled) setBmdDerived(d.endpoints?.length ? { endpoints: d.endpoints, ...(d.sorted_by ? { sorted_by: d.sorted_by } : {}) } as SectionData : null);
      })
      .catch(() => {
        if (!cancelled) setBmdDerived(null);
      });
    return () => {
      cancelled = true;
    };
  }, [dtxsid, readiness, session]);

  async function approve(key: string) {
    if (!dtxsid) return;
    const target = approvalTarget(key);
    const content = key === "bmd_summary" ? sectionContent(session, key) ?? bmdDerived : sectionContent(session, key);
    if (!target || !content) return;
    setActingKey(key);
    setError(null);
    try {
      // The approve route re-saves the section's CURRENT content with the
      // blessed marker; we send exactly what the session holds today.
      await api.approveSection(dtxsid, target.sectionType, content as Record<string, unknown>, target.extra);
      await afterMutation();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setActingKey(null);
    }
  }

  async function revise(key: string) {
    if (!dtxsid) return;
    const target = approvalTarget(key);
    if (!target) return;
    setActingKey(key);
    setError(null);
    try {
      await api.unapproveSection(dtxsid, target.sectionType, "", target.extra);
      await afterMutation();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setActingKey(null);
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
      <WarningBox warning={citationWarning} />
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
            onApprove={() => void approve(fm.key)}
            onRevise={() => void revise(fm.key)}
            acting={actingKey === fm.key}
            busy={busyKey === fm.key}
          />
        );
      })}
      {readiness["bmd_summary"] && (
        <SectionRow
          label="Apical BMD Summary"
          note="Auto-derived from results (deterministic)."
          enabled
          approved={readiness["bmd_summary"]?.approved ?? false}
          blockedBy={[]}
          content={sectionContent(session, "bmd_summary") ?? bmdDerived}
          unit="endpoint"
          onApprove={() => void approve("bmd_summary")}
          onRevise={() => void revise("bmd_summary")}
          acting={actingKey === "bmd_summary"}
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
              onApprove={() => void approve(key)}
              onRevise={() => void revise(key)}
              acting={actingKey === key}
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
