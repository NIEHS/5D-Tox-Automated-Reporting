import { useState } from "react";
import { api } from "../api";
import { ErrorBox, Spinner, StepProps } from "./shared";

export function Process({ dtxsid, next, back, processResult, setProcessResult }: StepProps) {
  const [compound, setCompound] = useState("");
  const [doseUnit, setDoseUnit] = useState("mg/kg");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    if (!dtxsid) return;
    setBusy(true);
    setError(null);
    try {
      const p = await api.process(dtxsid, {
        compound_name: compound.trim() || dtxsid,
        dose_unit: doseUnit.trim() || "mg/kg",
        bmd_stats: ["median"],
        go_pct: 5,
        go_min_genes: 20,
        go_max_genes: 500,
        go_min_bmd: 3,
      });
      // Echo the entered dose unit onto the payload (run_process doesn't return
      // it) so the Results tables can label dose columns. Held in App memory —
      // the payload has multi-MB base64 charts, too big for sessionStorage.
      setProcessResult({ ...p, dose_unit: doseUnit.trim() || "mg/kg" });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const payload = processResult;
  const nCharts = payload?.chart_images?.length ?? 0;

  return (
    <div className="panel">
      <h2>Step 7 · Process</h2>
      <p className="help">
        Runs the full compute: NTP statistics, BMDS dose-response modeling,
        genomics extraction, section cards, chart rendering, and LLM narratives.
        This is the long one — up to several minutes.
      </p>

      <div className="field-row">
        <label>
          Compound name
          <input
            type="text"
            placeholder="PFHxSAm"
            value={compound}
            onChange={(e) => setCompound(e.target.value)}
          />
        </label>
        <label>
          Dose unit
          <input
            type="text"
            value={doseUnit}
            onChange={(e) => setDoseUnit(e.target.value)}
          />
        </label>
      </div>

      <button className="primary" onClick={run} disabled={busy}>
        {busy ? <Spinner label="Processing… (may take minutes)" /> : "Run processing"}
      </button>
      {busy && (
        <p className="long-note">
          Blocking step — keep this tab open. BMDS modeling dominates the time.
        </p>
      )}

      <ErrorBox error={error} />

      {payload && (
        <p style={{ marginTop: "1rem" }}>
          <span className="badge ok">processed</span>{" "}
          <span className="muted">
            {nCharts} chart section{nCharts === 1 ? "" : "s"} ·{" "}
            {(payload.bmd_stats || []).join(", ")}
          </span>
        </p>
      )}

      <div className="actions">
        <button onClick={back}>Back</button>
        <button className="primary" disabled={!payload} onClick={next}>
          Next: Results
        </button>
      </div>
    </div>
  );
}
