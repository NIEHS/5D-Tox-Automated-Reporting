import { useCallback, useEffect, useMemo, useState } from "react";
import { api, SectionData, SectionReadinessMap, SessionLoad } from "../api";
import { useSectionReadiness } from "../useSectionReadiness";
import { usePublishReadiness } from "../usePublishReadiness";
import { useServerResource, invalidate } from "../useServerResource";
import { ErrorBox, Spinner, StepProps } from "./shared";

// Phase 6 — the document-section authoring stage, merged into the React wizard.
//
// Navigation is a TWO-GROUP SPLIT (user decision):
//   • Front matter (ordered, dependency-gated): Background → M&M → Summary.
//     M&M and Summary unlock only once the derived readiness says so
//     (background approved OR ≥1 result approved).
//   • Results (random-access grid): every bm2_* / genomics_* section present on
//     disk, authorable in any order as soon as its data exists.
//
// Enable/lock/blocked-by is rendered ENTIRELY from the server-DERIVED readiness
// map (useSectionReadiness) — never a client-side ready.* flag. After every
// mutation we re-derive readiness AND re-materialize the preview so both stay
// current.

// The section TYPE (what the save/approve routes take) for a bare front-matter key.
const FRONT_MATTER: { key: string; type: string; label: string }[] = [
  { key: "background", type: "background", label: "Background" },
  { key: "methods", type: "methods", label: "Materials & Methods" },
  { key: "summary", type: "summary", label: "Summary" },
];

// Split an on-disk section_key into (section_type, routing extras) for the
// save/approve/unapprove routes (mirrors session_routes._resolve_section_key).
function routeArgs(key: string): {
  type: string;
  extra: { bm2_slug?: string; organ?: string; sex?: string };
} {
  if (key.startsWith("bm2_")) {
    return { type: "bm2", extra: { bm2_slug: key.slice("bm2_".length) } };
  }
  if (key.startsWith("genomics_")) {
    const rest = key.slice("genomics_".length);
    const idx = rest.lastIndexOf("_");
    const organ = idx >= 0 ? rest.slice(0, idx) : rest;
    const sex = idx >= 0 ? rest.slice(idx + 1) : "";
    return { type: "genomics", extra: { organ, sex } };
  }
  return { type: key, extra: {} };
}

function sectionContent(session: SessionLoad | null, key: string): SectionData | null {
  if (!session) return null;
  if (key.startsWith("bm2_")) {
    return session.bm2_sections?.[key.slice("bm2_".length)] ?? null;
  }
  if (key.startsWith("genomics_")) {
    return session.genomics_sections?.[key.slice("genomics_".length)] ?? null;
  }
  return (session[key] as SectionData | null) ?? null;
}

function humanizeKey(key: string): string {
  if (key.startsWith("bm2_")) {
    return key
      .slice("bm2_".length)
      .replace(/-/g, " ")
      .replace(/\b\w/g, (c) => c.toUpperCase());
  }
  if (key.startsWith("genomics_")) {
    return (
      "Genomics — " +
      key
        .slice("genomics_".length)
        .replace(/_/g, " ")
        .replace(/\b\w/g, (c) => c.toUpperCase())
    );
  }
  return key.replace(/\b\w/g, (c) => c.toUpperCase());
}

export function Author({ dtxsid, back, next }: StepProps) {
  const { readiness } = useSectionReadiness(dtxsid);
  const { readiness: publish } = usePublishReadiness(dtxsid);
  // Session content is a keyed server resource too, so a single invalidate(dtxsid)
  // re-pulls it alongside readiness + publish — no per-resource refresh list.
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
  // Errors from a section-level mutation (save/approve) are separate from the
  // session-load error; show whichever is set.
  const [mutationError, setMutationError] = useState<string | null>(null);
  const error = mutationError ?? loadError;

  // section_key -> the currency BLOCK reason ("regenerated because …"), for the
  // per-section "re-accept" cue. Derived from the server publish gate, not guessed.
  const blockedReason = useMemo(() => {
    const m: Record<string, string> = {};
    for (const b of publish.blocking) m[b.section_key] = b.reason;
    return m;
  }, [publish]);

  // After any authoring mutation, invalidate everything keyed to this session
  // (session content + readiness + publish gate all re-pull automatically — the
  // reactive query cache tracks the dependency, no hand-maintained refresh list)
  // and re-materialize the preview so the docx/html files reflect the change.
  const afterMutation = useCallback(async () => {
    if (!dtxsid) return;
    await invalidate(dtxsid);
    try {
      await api.materializePreview(dtxsid);
    } catch {
      // Preview rebuild is best-effort; the Preview step also rebuilds on entry.
    }
  }, [dtxsid]);

  // Result sections = every readiness key that is an instance family.
  const resultKeys = useMemo(
    () =>
      Object.keys(readiness)
        .filter((k) => k.startsWith("bm2_") || k.startsWith("genomics_"))
        .sort(),
    [readiness]
  );

  if (!dtxsid) {
    return (
      <div className="panel">
        <h2>Author</h2>
        <p className="help">Select a session first.</p>
      </div>
    );
  }

  return (
    <div className="panel">
      <h2>Author sections</h2>
      <p className="help">
        Front-matter sections unlock in order (Background → Methods → Summary) as
        their dependencies are approved; result sections can be authored in any
        order. Lock state is derived from the server, not set by the UI.
      </p>

      <ErrorBox error={error} />
      {loading && <Spinner label="Loading session…" />}

      <h3 className="group-heading">Front matter (ordered)</h3>
      {FRONT_MATTER.map((fm, i) => (
        <SectionCard
          key={fm.key}
          index={i + 1}
          sectionKey={fm.key}
          title={fm.label}
          readiness={readiness}
          content={sectionContent(session, fm.key)}
          blockedReason={blockedReason[fm.key]}
          dtxsid={dtxsid}
          onMutated={afterMutation}
          setError={setMutationError}
        />
      ))}
      {/* bmd_summary is auto-derived; show it read-only when present. */}
      {readiness["bmd_summary"] && (
        <p className="muted" style={{ margin: "0.5rem 0" }}>
          Apical BMD Summary — auto-derived from approved results (read-only).
        </p>
      )}

      <h3 className="group-heading">Results (any order)</h3>
      {resultKeys.length === 0 ? (
        <p className="muted">
          No result sections yet — process the pool to produce apical / genomics
          data.
        </p>
      ) : (
        <div className="section-grid">
          {resultKeys.map((key) => (
            <SectionCard
              key={key}
              sectionKey={key}
              title={humanizeKey(key)}
              readiness={readiness}
              content={sectionContent(session, key)}
              blockedReason={blockedReason[key]}
              dtxsid={dtxsid}
              onMutated={afterMutation}
              setError={setMutationError}
              compact
            />
          ))}
        </div>
      )}

      {/* Report-grain publish gate (server-derived currency BLOCK). A data
          reprocess withdraws FINAL from LLM sections and flags them; publishing
          is blocked until each is re-accepted. */}
      {!publish.can_publish && (
        <div className="publish-blocked" role="status">
          <strong>Publishing blocked.</strong> {publish.blocking.length} section
          {publish.blocking.length === 1 ? "" : "s"} were regenerated after a data
          change and need to be re-accepted:
          <ul>
            {publish.blocking.map((b) => (
              <li key={b.section_key}>
                {humanizeKey(b.section_key)} — {b.reason.replace(/_/g, " ")}
              </li>
            ))}
          </ul>
        </div>
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

// One editable section: shows lock/blocked state from the derived readiness,
// lets the user edit paragraph text, save (no approve), approve (lock), or
// unapprove (unlock). Generation is triggered via the existing LLM routes — kept
// minimal here (the deep per-family editors remain in the legacy app for now).
function SectionCard({
  sectionKey,
  title,
  index,
  readiness,
  content,
  blockedReason,
  dtxsid,
  onMutated,
  setError,
  compact,
}: {
  sectionKey: string;
  title: string;
  index?: number;
  readiness: SectionReadinessMap;
  content: SectionData | null;
  blockedReason?: string;
  dtxsid: string;
  onMutated: () => Promise<void>;
  setError: (e: string | null) => void;
  compact?: boolean;
}) {
  const r = readiness[sectionKey];
  const enabled = r?.enabled ?? true;
  const approved = r?.approved ?? false;
  const blockedBy = r?.blocked_by ?? [];
  const stale = content?.stale ?? false;

  const [text, setText] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);

  // Seed the editor from loaded content whenever it changes and the user has no
  // unsaved edits in flight.
  useEffect(() => {
    if (!dirty) setText((content?.paragraphs ?? []).join("\n\n"));
  }, [content, dirty]);

  const { type, extra } = routeArgs(sectionKey);
  const paragraphs = () =>
    text
      .split(/\n{2,}/)
      .map((p) => p.trim())
      .filter(Boolean);

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      setDirty(false);
      await onMutated();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const save = () =>
    run(() =>
      api.saveSection(dtxsid, type, { paragraphs: paragraphs() }, extra)
    );
  const approve = () =>
    run(() =>
      api.approveSection(
        dtxsid,
        type,
        { paragraphs: paragraphs() },
        extra
      )
    );
  const unapprove = () => run(() => api.unapproveSection(dtxsid, type, extra));

  const hasContent = (content?.paragraphs?.length ?? 0) > 0 || text.trim() !== "";

  return (
    <div className={`section-card${compact ? " compact" : ""}`}>
      <div className="section-card-head">
        <strong>
          {index ? `${index}. ` : ""}
          {title}
        </strong>
        <span className="section-badges">
          {approved && <span className="badge ok">approved</span>}
          {/* A publish-blocking (regenerated) section shows WHY + a re-accept
              cue; a plain stale flag without a block reason falls back to "stale". */}
          {blockedReason ? (
            <span className="badge warn" title={`Regenerated (${blockedReason}) — re-accept to publish`}>
              re-accept
            </span>
          ) : (
            stale && <span className="badge warn">stale</span>
          )}
          {!enabled && <span className="badge">locked</span>}
        </span>
      </div>

      {!enabled ? (
        <p className="muted">
          Blocked — unlock by satisfying: {blockedBy.join(" or ") || "a dependency"}.
        </p>
      ) : (
        <>
          <textarea
            className="section-editor"
            value={text}
            disabled={busy || approved}
            placeholder="Paragraph text (blank line between paragraphs)…"
            onChange={(e) => {
              setText(e.target.value);
              setDirty(true);
            }}
          />
          <div className="section-actions">
            {busy && <Spinner label="Working…" />}
            {!approved ? (
              <>
                <button onClick={save} disabled={busy || !hasContent}>
                  Save
                </button>
                <button
                  className="primary"
                  onClick={approve}
                  disabled={busy || !hasContent}
                >
                  Approve
                </button>
              </>
            ) : (
              <button onClick={unapprove} disabled={busy}>
                Unapprove
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
