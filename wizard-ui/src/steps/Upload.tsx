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

export function Upload({ dtxsid, next, back, refresh }: StepProps) {
  const [files, setFiles] = useState<{ name: string; size: number }[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
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
        <code>.txt</code>/<code>.csv</code> tox-study tables (plus{" "}
        <code>.sidecar.json</code> files). They land in this session's{" "}
        <code>files/</code> folder.
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
                          <span className="badge">
                            {roleOf(f.name) === "bm2" ? "BMD result" : "data"}
                          </span>
                        </span>
                        <span className="size">{(f.size / 1024).toFixed(1)} KB</span>
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
