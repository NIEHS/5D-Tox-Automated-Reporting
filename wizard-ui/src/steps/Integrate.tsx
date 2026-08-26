import { useState } from "react";
import { api } from "../api";
import { ErrorBox, Spinner, StepProps } from "./shared";

export function Integrate({ dtxsid, state, next, back, refresh }: StepProps) {
  const [name, setName] = useState("");
  const [casrn, setCasrn] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<Record<string, unknown> | null>(null);

  const alreadyIntegrated =
    state?.artifacts?.hasIntegrated === true ||
    state?.phase === "INTEGRATED" ||
    state?.phase === "APPROVED";

  async function run() {
    if (!dtxsid) return;
    setBusy(true);
    setError(null);
    try {
      const s = await api.integrate(dtxsid, {
        name: name.trim() || dtxsid,
        casrn: casrn.trim(),
        dtxsid,
      });
      setSummary(s);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel">
      <h2>Step 5 · Integrate</h2>
      <p className="help">
        Merges the whole validated pool into one <code>integrated.json</code> —
        the single source of truth for the report. This runs the BMDExpress Java
        library and takes a minute or two.
      </p>

      <div className="field-row">
        <label>
          Compound name
          <input
            type="text"
            placeholder="Perfluorohexanesulfonamide"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label>
          CASRN
          <input
            type="text"
            placeholder="41997-13-1"
            value={casrn}
            onChange={(e) => setCasrn(e.target.value)}
          />
        </label>
      </div>

      <button className="primary" onClick={run} disabled={busy}>
        {busy ? <Spinner label="Integrating… (1–2 min)" /> : "Run integration"}
      </button>
      {busy && (
        <p className="long-note">
          This is a long, blocking step — keep this tab open until it finishes.
        </p>
      )}

      <ErrorBox error={error} />

      {(summary || alreadyIntegrated) && (
        <p style={{ marginTop: "1rem" }}>
          <span className="badge ok">integrated</span>{" "}
          {summary && (
            <span className="muted">
              {String(summary.experiment_count ?? "?")} experiments ·{" "}
              {String(summary.bmd_result_count ?? "?")} BMD results ·{" "}
              {String(summary.category_analysis_count ?? "?")} category analyses
            </span>
          )}
        </p>
      )}

      <div className="actions">
        <button onClick={back}>Back</button>
        <button
          className="primary"
          disabled={!(summary || alreadyIntegrated)}
          onClick={next}
        >
          Next: Approve
        </button>
      </div>
    </div>
  );
}
