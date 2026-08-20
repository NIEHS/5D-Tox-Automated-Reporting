import { useState } from "react";
import { api, ChartSection } from "../api";
import { ErrorBox, StepProps } from "./shared";
import { SummaryTables } from "./SummaryTables";

export function Results({
  dtxsid,
  back,
  setDtxsid,
  refresh,
  processResult,
  setProcessResult,
}: StepProps) {
  const payload = processResult;
  const [error, setError] = useState<string | null>(null);

  const charts: ChartSection[] = payload?.chart_images || [];
  const sectionCount = Array.isArray(payload?.sections)
    ? payload!.sections!.length
    : 0;

  async function resetPool() {
    if (!dtxsid) return;
    if (!confirm(`Reset the pool for ${dtxsid}? This deletes derived artifacts.`))
      return;
    try {
      await api.reset(dtxsid);
      setProcessResult(null);
      setDtxsid(null);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="panel">
      <h2>Step 8 · Results</h2>
      {!payload ? (
        <p className="help">
          No processed result in this browser session. Go back to{" "}
          <strong>Process</strong> and run it (the payload is large and only kept
          for the current tab).
        </p>
      ) : (
        <>
          <p className="help">
            {sectionCount} apical section{sectionCount === 1 ? "" : "s"} ·{" "}
            {charts.length} genomics chart section
            {charts.length === 1 ? "" : "s"} · BMD stats:{" "}
            {(payload.bmd_stats || []).join(", ") || "—"}
          </p>

          {charts.map((sec, i) => (
            <div className="chart-section" key={i}>
              <h3>{sec.label || `${sec.organ} / ${sec.sex}`}</h3>
              {sec.umap_png && (
                <>
                  <img
                    src={`data:image/png;base64,${sec.umap_png}`}
                    alt={`UMAP ${sec.label}`}
                  />
                  <p className="chart-caption">
                    {sec.umap_caption || "UMAP scatter"}
                  </p>
                </>
              )}
              {sec.cluster_png && (
                <>
                  <img
                    src={`data:image/png;base64,${sec.cluster_png}`}
                    alt={`Cluster ${sec.label}`}
                  />
                  <p className="chart-caption">
                    {sec.cluster_caption || "Cluster scatter"}
                  </p>
                </>
              )}
            </div>
          ))}

          {charts.length === 0 && (
            <p className="muted">
              No genomics chart sections in this payload (the pool may have no
              gene-expression data).
            </p>
          )}

          <SummaryTables
            payload={payload}
            doseUnit={(payload.dose_unit as string) || "mg/kg"}
          />
        </>
      )}

      <ErrorBox error={error} />

      <div className="actions">
        <button onClick={back}>Back</button>
        <button className="danger" onClick={resetPool}>
          Reset pool
        </button>
      </div>
    </div>
  );
}
