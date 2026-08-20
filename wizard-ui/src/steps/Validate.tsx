import { useState } from "react";
import { api, ValidationReport } from "../api";
import { ErrorBox, Spinner, StepProps } from "./shared";

export function Validate({ dtxsid, next, back, refresh }: StepProps) {
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    if (!dtxsid) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.validate(dtxsid);
      setReport(r);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const errors = (report?.issues || []).filter((i) => i.severity === "error");
  const warnings = (report?.issues || []).filter((i) => i.severity === "warning");
  const canProceed = report !== null && errors.length === 0;

  return (
    <div className="panel">
      <h2>Step 3 · Validate</h2>
      <p className="help">
        Re-fingerprints every file and runs cross-validation (platform coverage,
        dose-group consistency, animal counts, sex coverage). Error-severity
        issues block integration; warnings do not.
      </p>

      <button className="primary" onClick={run} disabled={busy}>
        {busy ? <Spinner label="Validating…" /> : "Run validation"}
      </button>

      <ErrorBox error={error} />

      {report && (
        <div style={{ marginTop: "1rem" }}>
          <p>
            {report.file_count} files ·{" "}
            {errors.length > 0 ? (
              <span className="badge err">{errors.length} error(s)</span>
            ) : (
              <span className="badge ok">no errors</span>
            )}{" "}
            {warnings.length > 0 && (
              <span className="badge warn">{warnings.length} warning(s)</span>
            )}
          </p>

          {report.issues.length > 0 && (
            <table>
              <thead>
                <tr>
                  <th>Severity</th>
                  <th>Kind</th>
                  <th>Message</th>
                </tr>
              </thead>
              <tbody>
                {report.issues.map((iss, i) => (
                  <tr key={i}>
                    <td>
                      <span
                        className={
                          iss.severity === "error" ? "badge err" : "badge warn"
                        }
                      >
                        {iss.severity}
                      </span>
                    </td>
                    <td>{iss.kind || "—"}</td>
                    <td>{iss.message || JSON.stringify(iss)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      <div className="actions">
        <button onClick={back}>Back</button>
        <button className="primary" disabled={!canProceed} onClick={next}>
          Next: Confirm metadata
        </button>
      </div>
    </div>
  );
}
