import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { ErrorBox, Spinner, StepProps } from "./shared";

const BM2_EXT = /\.bm2$/i;
const DATA_EXT = /\.(csv|txt|sidecar\.json)$/i;

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

      {files.length > 0 && (
        <ul className="file-list">
          {files.map((f) => (
            <li key={f.name}>
              <span>{f.name}</span>
              <span className="size">{(f.size / 1024).toFixed(1)} KB</span>
            </li>
          ))}
        </ul>
      )}

      <div className="actions">
        <button onClick={back}>Back</button>
        <button className="primary" disabled={files.length === 0} onClick={next}>
          Next: Validate ({files.length} file{files.length === 1 ? "" : "s"})
        </button>
      </div>
    </div>
  );
}
