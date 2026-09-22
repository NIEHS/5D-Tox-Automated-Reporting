import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, SectionData, SectionInfo, SessionLoad } from "../api";
import { useSections } from "../useSections";
import { useServerResource, invalidate } from "../useServerResource";
import { ErrorBox, Spinner, StepProps, WarningBox } from "./shared";

// The document workstream's SECTIONS surface (ADR-0018). The app is NOT an editor:
// this is a READ-ONLY status view that GENERATES authored sections (Background,
// M&M) once their dependencies are satisfied and MATERIALIZES the apical result
// sections from the Process cache. Human editing happens EXTERNALLY (Word/Overleaf)
// after handoff — there are no editors, no accept/revise here. It feeds Preview.
//
// The row set is DERIVED from the tree-driven section catalog
// (GET /api/workflow/{id}/sections via useSections), NOT a hardcoded list: a
// section added to the template surfaces here automatically. Grouping and controls
// come from each entry's catalog metadata — `instance_of` (bm2/genomics family),
// `kind` (llm/programmatic/derived/authored), and `approvable`.

// Fixed display copy for the singleton content sections. Keyed by catalog key;
// a section the catalog reports but that is missing here still renders with a
// humanized fallback label, so this is copy-only, not an identity registry.
const SECTION_COPY: Record<string, { label: string; note: string }> = {
  background: { label: "Background", note: "Generated from the test-article identity." },
  methods: { label: "Materials & Methods", note: "Generated from study metadata after Process." },
  summary: { label: "Summary", note: "Synthesizes approved sections." },
  bmd_summary: { label: "Apical BMD Summary", note: "Auto-derived from results (deterministic)." },
  animal_condition: { label: "Animal Condition, Body & Organ Weights", note: "Deterministic narrative from the processed data." },
  clinical_pathology: { label: "Clinical Pathology", note: "Deterministic narrative from the processed data." },
  internal_dose: { label: "Internal Dose Assessment", note: "Deterministic narrative from the processed data." },
};

// The authored singletons that auto-generate on visit (each has a distinct
// generator API call in maybeGenerate). The effect only fires for catalog keys
// present here, so a new llm section without a wired generator is a no-op row.
const GENERATORS: Record<string, true> = {
  background: true,
  methods: true,
  summary: true,
};

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
  const stripped = key
    .replace(/^bm2_/, "")
    .replace(/^genomics_/, "")
    .replace(/[-_]/g, " ");
  return stripped.replace(/\b\w/g, (c) => c.toUpperCase());
}

// Display label for a catalog key: fixed copy for the singletons, humanized
// fallback for instance keys (bm2_<slug>, genomics_<organ>_<sex>).
function sectionLabel(key: string): string {
  return SECTION_COPY[key]?.label ?? humanizeKey(key);
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
  const { sections } = useSections(dtxsid);
  // Index the catalog by key for O(1) per-row lookup (replaces the readiness map).
  const byKey = useMemo(() => {
    const m: Record<string, SectionInfo> = {};
    for (const s of sections) m[s.key] = s;
    return m;
  }, [sections]);
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
    // Auto-generate the authored (LLM) singleton sections once unlocked. Driven
    // by the catalog's `kind`, not a hardcoded list — background/methods/summary
    // are the llm singletons; each is a no-op until its readiness unlocks it.
    for (const s of sections) {
      if (s.kind === "llm" && s.instance_of === null && GENERATORS[s.key]) {
        void maybeGenerate(s.key);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dtxsid, loading, sections, session]);

  async function maybeGenerate(key: string) {
    if (!dtxsid) return;
    const r = byKey[key];
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
    if (!dtxsid || !byKey["bmd_summary"] || session?.bmd_summary) {
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
  }, [dtxsid, byKey, session]);

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

  // Row groups, all DERIVED from the catalog (document order preserved):
  //   front matter   — approvable singletons that are generated (background/methods/summary)
  //   narratives     — programmatic group narratives, display-only (animal_condition, …)
  //   bmdSummary     — the single derived Apical BMD Summary entry, if present
  //   results        — the apical bm2_* instances
  //   genomics       — the genomics_* instances (deterministic, read-only)
  const frontMatter = useMemo(
    () => sections.filter((s) => s.instance_of === null && GENERATORS[s.key]),
    [sections]
  );
  const narratives = useMemo(
    () => sections.filter((s) => s.instance_of === null && s.kind === "programmatic"),
    [sections]
  );
  const bmdSummary = useMemo(
    () => sections.find((s) => s.key === "bmd_summary") ?? null,
    [sections]
  );
  const results = useMemo(
    () => sections.filter((s) => s.instance_of === "bm2").sort((a, b) => a.key.localeCompare(b.key)),
    [sections]
  );
  const genomics = useMemo(
    () => sections.filter((s) => s.instance_of === "genomics").sort((a, b) => a.key.localeCompare(b.key)),
    [sections]
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
      {frontMatter.map((s) => (
        <SectionRow
          key={s.key}
          label={sectionLabel(s.key)}
          note={SECTION_COPY[s.key]?.note}
          enabled={s.enabled}
          approved={s.approved}
          blockedBy={s.blocked_by}
          content={sectionContent(session, s.key)}
          onApprove={() => void approve(s.key)}
          onRevise={() => void revise(s.key)}
          acting={actingKey === s.key}
          busy={busyKey === s.key}
        />
      ))}
      {bmdSummary && (
        <SectionRow
          label={sectionLabel("bmd_summary")}
          note={SECTION_COPY["bmd_summary"]?.note}
          enabled={bmdSummary.enabled}
          approved={bmdSummary.approved}
          blockedBy={bmdSummary.blocked_by}
          content={sectionContent(session, "bmd_summary") ?? bmdDerived}
          unit="endpoint"
          onApprove={() => void approve("bmd_summary")}
          onRevise={() => void revise("bmd_summary")}
          acting={actingKey === "bmd_summary"}
        />
      )}

      {narratives.length > 0 && (
        <>
          <h3 className="group-heading">Result narratives (deterministic)</h3>
          {narratives.map((s) => (
            <SectionRow
              key={s.key}
              label={sectionLabel(s.key)}
              note={SECTION_COPY[s.key]?.note ?? "Deterministic narrative from the processed data."}
              enabled={s.enabled}
              approved={s.approved}
              blockedBy={s.blocked_by}
              content={sectionContent(session, s.key)}
            />
          ))}
        </>
      )}

      <div className="group-heading-row">
        <h3 className="group-heading">Apical results</h3>
        <button onClick={materializeResults} disabled={busyKey === "results"}>
          {busyKey === "results" ? <Spinner label="Materializing…" /> : "Materialize results"}
        </button>
      </div>
      {results.length === 0 ? (
        <p className="muted">
          {processed
            ? "No result sections materialized yet — click Materialize results."
            : "Process the pool first to produce result data."}
        </p>
      ) : (
        results.map((s) => (
          <SectionRow
            key={s.key}
            label={sectionLabel(s.key)}
            enabled={s.enabled}
            approved={s.approved}
            blockedBy={s.blocked_by}
            content={sectionContent(session, s.key)}
            onApprove={() => void approve(s.key)}
            onRevise={() => void revise(s.key)}
            acting={actingKey === s.key}
          />
        ))
      )}

      {genomics.length > 0 && (
        <>
          <h3 className="group-heading">Genomics (deterministic, read-only)</h3>
          {genomics.map((s) => (
            <SectionRow
              key={s.key}
              label={sectionLabel(s.key)}
              note="Deterministic result — not authored."
              enabled={s.enabled}
              approved={false}
              blockedBy={s.blocked_by}
              content={null}
            />
          ))}
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
