import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { ErrorBox, Spinner, StepProps } from "./shared";

// Phase 5 UI — the materialized, docx-default preview.
//
// docx is the canonical deliverable (download button), but docx can't render in
// an iframe, so the on-screen view is the always-materialized preview.html FILE
// (not srcdoc). Other deliverable surfaces (latex, jats) are provisioned in the
// selector but disabled — the visible face of the "unimplemented provision".

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

  return (
    <div className="panel">
      <h2>Preview</h2>
      <p className="help">
        The report is materialized to a file on each update. The frame shows the
        HTML view; the deliverable downloads as {surface.toUpperCase()}.
      </p>

      <div className="field-row">
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
          className="download-link"
          href={downloadUrl}
          {...(SURFACES.find((s) => s.key === surface)?.enabled
            ? {}
            : { onClick: (e) => e.preventDefault() })}
        >
          ⭳ Download {surface}
        </a>
      </div>

      <ErrorBox error={error} />

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
