import { useState } from "react";
import { api } from "../api";
import { ErrorBox, Spinner, StepProps } from "./shared";

export function Approve({ dtxsid, state, back, refresh, gotoReport }: StepProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<Record<string, unknown> | null>(null);

  const alreadyApproved =
    state?.artifacts?.hasAnimalReport === true || state?.phase === "APPROVED";

  async function run() {
    if (!dtxsid) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.approve(dtxsid);
      setReport(r);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel">
      <h2>Step 6 · Approve (generate animal report)</h2>
      <p className="help">
        Produces the per-animal traceability report — every animal mapped to
        dose, sex, and selection (core vs biosampling). Its presence advances the
        pool to <code>APPROVED</code>.
      </p>

      <button className="primary" onClick={run} disabled={busy}>
        {busy ? <Spinner label="Generating…" /> : "Generate animal report"}
      </button>

      <ErrorBox error={error} />

      {(report || alreadyApproved) && (
        <p style={{ marginTop: "1rem" }}>
          <span className="badge ok">approved</span>{" "}
          {report && (
            <span className="muted">
              {String(report.total_animals ?? "?")} animals ·{" "}
              {String(report.core_count ?? "?")} core /{" "}
              {String(report.biosampling_count ?? "?")} biosampling
            </span>
          )}
        </p>
      )}

      {(report || alreadyApproved) && (
        <p className="help" style={{ marginTop: "1rem" }}>
          The pool is prepared. Continue to report generation to run the full
          compute and view results.
        </p>
      )}

      <div className="actions">
        <button onClick={back}>Back</button>
        <button
          className="primary"
          disabled={!(report || alreadyApproved)}
          onClick={gotoReport}
        >
          Generate report →
        </button>
      </div>
    </div>
  );
}
