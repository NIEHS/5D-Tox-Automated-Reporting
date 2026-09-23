import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { usePublishReadiness } from "../usePublishReadiness";
import { ErrorBox, Spinner, StepProps, WarningBox } from "./shared";

// Phase 5 UI — the materialized, docx-default preview.
//
// docx is the canonical deliverable (download button), but docx can't render in
// an iframe, so the on-screen view is the always-materialized preview.html FILE
// (not srcdoc). Other deliverable surfaces (latex, jats) are provisioned in the
// selector but disabled — the visible face of the "unimplemented provision".
//
// Publish gate (Phase 3a currency BLOCK): a data reprocess withdraws FINAL from
// the report's LLM sections and stamps each `regenerated`. The DELIVERABLE download
// is the point the report leaves the app, so it is gated on
// usePublishReadiness.can_publish — you can still preview a stale report, but you
// cannot export it until every rewritten LLM section is re-accepted (in Sections).

// Humanize a section_key for the blocker notice (bm2_<slug> / genomics_<organ>_<sex>
// / bare singletons), matching the Sections screen's labeling.
function humanizeKey(key: string): string {
  return key
    .replace(/^bm2_/, "")
    .replace(/^genomics_/, "")
    .replace(/[-_]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

const SURFACES: { key: string; label: string; enabled: boolean }[] = [
  { key: "docx", label: "Word (.docx)", enabled: true },
  { key: "html", label: "HTML", enabled: true },
  { key: "latex", label: "LaTeX (soon)", enabled: false },
  { key: "jats", label: "JATS/BITS (soon)", enabled: false },
];

const VERSION = "default";

export function Preview({ dtxsid, back }: StepProps) {
  const [surface, setSurface] = useState("docx");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Bumped on each rebuild to bust the iframe cache of the materialized file.
  const [nonce, setNonce] = useState(0);
  const [ready, setReady] = useState(false);
  // Report-grain publish gate — the deliverable download is blocked while any LLM
  // section is stale/regenerated-unaccepted. Derived on the server; never guessed.
  const { readiness: publish } = usePublishReadiness(dtxsid);

  const rebuild = useCallback(async () => {
    if (!dtxsid) return;
    setBusy(true);
    setError(null);
    try {
      await api.materializePreview(dtxsid, surface, VERSION);
      setReady(true);
      setNonce((n) => n + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [dtxsid, surface]);

  // Materialize on entry and whenever the deliverable surface changes.
  useEffect(() => {
    void rebuild();
  }, [rebuild]);

  if (!dtxsid) {
    return (
      <div className="panel">
        <h2>Preview</h2>
        <p className="help">Select a session first.</p>
      </div>
    );
  }

  const viewUrl = `${api.previewViewUrl(dtxsid, VERSION, "html")}&_=${nonce}`;
  const downloadUrl = api.previewDownloadUrl(dtxsid, VERSION, surface);

  const surfaceEnabled = SURFACES.find((s) => s.key === surface)?.enabled ?? false;
  // The deliverable download is allowed only when the surface is implemented AND
  // the report passes the publish gate (no stale/regenerated LLM section).
  const downloadBlocked = !surfaceEnabled || !publish.can_publish;
  const publishNotice = publish.can_publish
    ? null
    : "Download is blocked until the rewritten sections are re-accepted (data " +
      "changed since they were approved): " +
      publish.blocking
        .map((b) => `${humanizeKey(b.section_key)} (${b.reason.replace(/_/g, " ")})`)
        .join(", ") +
      ". Re-approve them on the Sections step.";

  return (
    <div className="panel">
      <h2>Preview</h2>
      <p className="help">
        The report is materialized to a file on each update. The frame shows the
        HTML view; the deliverable downloads as {surface.toUpperCase()}.
      </p>

      <div className="field-row preview-toolbar">
        <label>
          Deliverable surface
          <select value={surface} onChange={(e) => setSurface(e.target.value)}>
            {SURFACES.map((s) => (
              <option key={s.key} value={s.key} disabled={!s.enabled}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        <button onClick={rebuild} disabled={busy}>
          {busy ? <Spinner label="Rebuilding…" /> : "Rebuild preview"}
        </button>
        <a
          className={`download-link${downloadBlocked ? " disabled" : ""}`}
          href={downloadBlocked ? undefined : downloadUrl}
          aria-disabled={downloadBlocked}
          title={
            !publish.can_publish
              ? "Blocked: re-accept the rewritten sections before exporting"
              : `Download the ${surface} deliverable`
          }
          {...(downloadBlocked ? { onClick: (e) => e.preventDefault() } : {})}
        >
          ⭳ Download {surface}
        </a>
        <a className="download-link" href={viewUrl} target="_blank" rel="noreferrer" title="Open the paginated HTML view in its own tab">
          ↗ Open in new tab
        </a>
      </div>

      <ErrorBox error={error} />
      <WarningBox warning={publishNotice} />

      {ready ? (
        <iframe className="preview-frame" src={viewUrl} title="Report preview" />
      ) : (
        !error && <Spinner label="Materializing preview…" />
      )}

      <div className="actions">
        <button onClick={back}>Back</button>
      </div>
    </div>
  );
}
