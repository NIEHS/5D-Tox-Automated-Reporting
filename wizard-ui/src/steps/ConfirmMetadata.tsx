import { useCallback, useEffect, useState } from "react";
import { api, Fingerprint } from "../api";
import { ErrorBox, Spinner, StepProps } from "./shared";

// The editable dropdown option sets mirror the legacy UI's confirm panel.
const PLATFORMS = [
  "Body Weight",
  "Clinical Chemistry",
  "Hematology",
  "Hormones",
  "Organ Weight",
  "Clinical",
  "Tissue Concentration",
  "gene_expression",
];
const DATA_TYPES = ["inferred", "tox_study", "gene_expression"];

export function ConfirmMetadata({ dtxsid, next, back, refresh }: StepProps) {
  const [rows, setRows] = useState<Fingerprint[]>([]);
  const [edits, setEdits] = useState<
    Record<string, { platform?: string; data_type?: string }>
  >({});
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const load = useCallback(async () => {
    if (!dtxsid) return;
    setLoading(true);
    setError(null);
    try {
      const r = await api.getFingerprints(dtxsid);
      setRows(r.fingerprints);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [dtxsid]);

  useEffect(() => {
    void load();
  }, [load]);

  function setEdit(fid: string, field: "platform" | "data_type", value: string) {
    setEdits((prev) => ({ ...prev, [fid]: { ...prev[fid], [field]: value } }));
  }

  async function confirm() {
    if (!dtxsid) return;
    setBusy(true);
    setError(null);
    try {
      // Only send files the user actually changed; empty map = accept detection.
      await api.confirmMetadata(dtxsid, edits);
      setDone(true);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel">
      <h2>Step 4 · Confirm metadata</h2>
      <p className="help">
        Review the auto-detected classification. You can override{" "}
        <strong>platform</strong> and <strong>data type</strong> per file; sex is
        auto-detected and read-only. Leave everything unchanged to accept the
        detection (a no-op).
      </p>

      <ErrorBox error={error} />
      {loading ? (
        <Spinner label="Loading detected metadata…" />
      ) : (
        <table>
          <thead>
            <tr>
              <th>File</th>
              <th>Type</th>
              <th>Platform</th>
              <th>Data type</th>
              <th>Sexes</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((fp) => (
              <tr key={fp.file_id}>
                <td>
                  <code>{fp.filename}</code>
                </td>
                <td>{fp.file_type || "?"}</td>
                <td>
                  <select
                    value={edits[fp.file_id]?.platform ?? fp.platform}
                    onChange={(e) =>
                      setEdit(fp.file_id, "platform", e.target.value)
                    }
                  >
                    {[fp.platform, ...PLATFORMS]
                      .filter((v, i, a) => v && a.indexOf(v) === i)
                      .map((p) => (
                        <option key={p} value={p}>
                          {p}
                        </option>
                      ))}
                  </select>
                </td>
                <td>
                  <select
                    value={edits[fp.file_id]?.data_type ?? fp.data_type}
                    onChange={(e) =>
                      setEdit(fp.file_id, "data_type", e.target.value)
                    }
                  >
                    {[fp.data_type, ...DATA_TYPES]
                      .filter((v, i, a) => v && a.indexOf(v) === i)
                      .map((d) => (
                        <option key={d} value={d}>
                          {d}
                        </option>
                      ))}
                  </select>
                </td>
                <td className="muted">{fp.sexes.join(", ") || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div style={{ marginTop: "1rem" }}>
        <button className="primary" onClick={confirm} disabled={busy}>
          {busy ? <Spinner label="Confirming…" /> : "Confirm metadata"}
        </button>
        {done && (
          <span className="badge ok" style={{ marginLeft: 8 }}>
            confirmed
          </span>
        )}
      </div>

      <div className="actions">
        <button onClick={back}>Back</button>
        <button className="primary" disabled={!done} onClick={next}>
          Next: Integrate
        </button>
      </div>
    </div>
  );
}
