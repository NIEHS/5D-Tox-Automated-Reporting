import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { ErrorBox, Spinner, StepProps } from "./shared";

const BM2_EXT = /\.bm2$/i;
const DATA_EXT = /\.(csv|txt|xlsx|sidecar\.json)$/i;
const SIDECAR_EXT = /\.sidecar\.json$/i;

// The role each file plays in the pool — distinct from "how it arrived". A
// sidecar is companion metadata that RIDES ALONG with its data file (same stem),
// not a study file the user chose to upload; the list should say so rather than
// present it as a peer upload.
type FileRole = "bm2" | "data" | "sidecar";
function roleOf(name: string): FileRole {
  if (SIDECAR_EXT.test(name)) return "sidecar";
  if (BM2_EXT.test(name)) return "bm2";
  return "data";
}

export function Upload({
  dtxsid,
  setDtxsid,
  next,
  back,
  refresh,
  setProcessResult,
  gotoLanding,
}: StepProps) {
  const [files, setFiles] = useState<{ name: string; size: number }[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [over, setOver] = useState(false);

  const loadFiles = useCallback(async () => {
    if (!dtxsid) return;
    try {
      const r = await api.listFiles(dtxsid);
      setFiles(r.files);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [dtxsid]);

  useEffect(() => {
    void loadFiles();
  }, [loadFiles]);

  async function upload(fileList: File[]) {
    if (!dtxsid || fileList.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      const bm2 = fileList.filter((f) => BM2_EXT.test(f.name));
      const data = fileList.filter((f) => DATA_EXT.test(f.name));
      const skipped = fileList.filter(
        (f) => !BM2_EXT.test(f.name) && !DATA_EXT.test(f.name)
      );
      if (bm2.length) await api.uploadBm2(dtxsid, bm2);
      if (data.length) await api.uploadCsv(dtxsid, data);
      if (skipped.length) {
        setError(
          "Skipped unsupported files: " + skipped.map((f) => f.name).join(", ")
        );
      }
      await loadFiles();
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  // Run a destructive pool action with shared busy/error/notice handling.
  async function act(fn: () => Promise<string | null>) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      setNotice(await fn());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function removeFile(name: string) {
    if (!dtxsid) return;
    const ok = confirm(
      `Remove ${name} from the pool?\n\n` +
        "Its companion metadata (.sidecar.json) goes with it. The file is moved " +
        "to this session's _removed/ folder, not permanently deleted. If the pool " +
        "was already validated or integrated, those results are cleared and must " +
        "be re-run."
    );
    if (!ok) return;
    void act(async () => {
      const r = await api.removeFile(dtxsid, name);
      setProcessResult(null);
      await loadFiles();
      await refresh();
      return (
        `Removed ${r.removed.join(", ")}.` +
        (r.pool_invalidated ? " Validation and integration were cleared; re-run them." : "")
      );
    });
  }

  function resetPool() {
    if (!dtxsid) return;
    const ok = confirm(
      `RESET POOL for ${dtxsid}\n\n` +
        "Permanently deletes: every uploaded file, validation and integration " +
        "results, processing caches, approved report sections, and rendered " +
        "previews.\n\n" +
        "Keeps: the chemical identity, section history, report view settings, " +
        "and the Background section.\n\nThis cannot be undone."
    );
    if (!ok) return;
    void act(async () => {
      await api.reset(dtxsid);
      setProcessResult(null);
      await loadFiles();
      await refresh();
      return "Pool reset. Upload files to start over.";
    });
  }

  function deleteSession() {
    if (!dtxsid) return;
    const typed = prompt(
      `DELETE SESSION ${dtxsid}\n\n` +
        "Permanently deletes EVERYTHING for this chemical: identity, history, " +
        "files, sections and settings. This cannot be undone.\n\n" +
        "Type the DTXSID to confirm:"
    );
    if (typed === null) return;
    if (typed.trim() !== dtxsid) {
      setError("Session not deleted: the DTXSID you typed did not match.");
      return;
    }
    void act(async () => {
      await api.deleteSession(dtxsid);
      setProcessResult(null);
      setDtxsid(null);
      gotoLanding();
      return null;
    });
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setOver(false);
    void upload(Array.from(e.dataTransfer.files));
  }

  return (
    <div className="panel">
      <h2>Step 2 · Upload study files</h2>
      <p className="help">
        Drag in the study's <code>.bm2</code> files and any{" "}
        <code>.txt</code>/<code>.csv</code> tox-study tables. They land in this
        session's <code>files/</code> folder.
      </p>

      <div
        className={over ? "dropzone over" : "dropzone"}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
      >
        {busy ? (
          <Spinner label="Uploading…" />
        ) : (
          <>
            Drop files here, or{" "}
            <label style={{ color: "var(--accent)", cursor: "pointer" }}>
              browse
              <input
                type="file"
                multiple
                style={{ display: "none" }}
                onChange={(e) =>
                  e.target.files && upload(Array.from(e.target.files))
                }
              />
            </label>
          </>
        )}
      </div>

      <ErrorBox error={error} />
      {notice && <p className="help notice">{notice}</p>}

      {files.length > 0 &&
        (() => {
          const uploads = files.filter((f) => roleOf(f.name) !== "sidecar");
          const sidecars = files.filter((f) => roleOf(f.name) === "sidecar");
          return (
            <>
              {uploads.length > 0 && (
                <>
                  <h3 className="group-heading">Uploaded study files</h3>
                  <ul className="file-list">
                    {uploads.map((f) => (
                      <li key={f.name}>
                        <span>
                          {f.name}{" "}
                          <span
                            className={
                              roleOf(f.name) === "bm2"
                                ? "badge bm2"
                                : "badge data"
                            }
                          >
                            {roleOf(f.name) === "bm2" ? "BMD result" : "data"}
                          </span>
                        </span>
                        <span className="file-actions">
                          <span className="size">{(f.size / 1024).toFixed(1)} KB</span>
                          <button
                            className="danger small"
                            disabled={busy}
                            onClick={() => removeFile(f.name)}
                            title={`Remove ${f.name} (and its companion metadata) from the pool`}
                          >
                            Remove
                          </button>
                        </span>
                      </li>
                    ))}
                  </ul>
                </>
              )}

              {sidecars.length > 0 && (
                <>
                  <h3 className="group-heading">Companion metadata (auto-attached)</h3>
                  <p className="help" style={{ marginTop: 0 }}>
                    For each data file, a <code>.sidecar.json</code> file having the
                    same name is created, and rides along in the file pool. Sidecar
                    files maintain metadata that are lost when the precursor data
                    files are pivoted so that they can be used internally as BMD
                    Express input. The sidecar preserves the per-animal detail that
                    has no slot in that pivoted format —{" "}
                    <strong>observation day</strong> (SD0/SD5),{" "}
                    <strong>selection</strong> (Core vs Biosampling animals), the{" "}
                    <strong>terminal</strong> measurement flag, and raw per-animal
                    values — so tables and narratives can recover it.
                  </p>
                  <ul className="file-list">
                    {sidecars.map((f) => (
                      <li key={f.name}>
                        <span className="muted">{f.name}</span>
                        <span className="size">{(f.size / 1024).toFixed(1)} KB</span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </>
          );
        })()}

      {dtxsid && (
        <div className="danger-zone">
          <h3 className="group-heading">Start over</h3>
          <p className="help" style={{ marginTop: 0 }}>
            <strong>Reset pool</strong> clears every file and everything derived from
            them, but keeps this chemical's identity and history.{" "}
            <strong>Delete session</strong> removes the chemical entirely.
          </p>
          <div className="actions" style={{ marginTop: 0 }}>
            <button className="danger" disabled={busy || files.length === 0} onClick={resetPool}>
              Reset pool
            </button>
            <button className="danger" disabled={busy} onClick={deleteSession}>
              Delete session…
            </button>
          </div>
        </div>
      )}

      <div className="actions">
        <button onClick={back}>Back</button>
        <button className="primary" disabled={files.length === 0} onClick={next}>
          Next: Validate (
          {files.filter((f) => roleOf(f.name) !== "sidecar").length} file
          {files.filter((f) => roleOf(f.name) !== "sidecar").length === 1 ? "" : "s"})
        </button>
      </div>
    </div>
  );
}
