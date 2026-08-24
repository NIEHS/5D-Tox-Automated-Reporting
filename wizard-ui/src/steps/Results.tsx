import { useEffect, useRef, useState } from "react";
import { api, ChartSection } from "../api";
import { ErrorBox, Spinner, StepProps } from "./shared";
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
  const [reloading, setReloading] = useState(false);
  const triedReload = useRef(false);

  // Rehydrate on load: the processed payload is large (multi-MB base64 charts)
  // so it lives only in App memory, not sessionStorage — a page refresh drops
  // it and this step would otherwise be empty, forcing a needless re-run of
  // Process. If the session is already processed (its caches exist), re-fetch
  // the payload from the cache (a ~2s cache-hit), using the compound_name /
  // dose_unit the user persisted in Process. Gated on isProcessed so we never
  // trigger a real multi-minute recompute on an unprocessed session.
  useEffect(() => {
    if (payload || !dtxsid || triedReload.current) return;
    triedReload.current = true;
    (async () => {
      try {
        const { processed } = await api.isProcessed(dtxsid);
        if (!processed) return;
        setReloading(true);
        const compound =
          JSON.parse(sessionStorage.getItem("wizard.compound") || '""') || dtxsid;
        const doseUnit =
          JSON.parse(sessionStorage.getItem("wizard.doseUnit") || '"mg/kg"') ||
          "mg/kg";
        const p = await api.process(dtxsid, {
          compound_name: compound,
          dose_unit: doseUnit,
          bmd_stats: ["median"],
          go_pct: 5,
          go_min_genes: 20,
          go_max_genes: 500,
          go_min_bmd: 3,
        });
        setProcessResult({ ...p, dose_unit: doseUnit });
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setReloading(false);
      }
    })();
  }, [dtxsid, payload, setProcessResult]);

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
        reloading ? (
          <p className="help">
            <Spinner label="Restoring results from the server cache…" />
          </p>
        ) : (
          <p className="help">
            No processed result loaded. Go back to <strong>Process</strong> and
            run it, or if this session was already processed it will restore
            automatically.
          </p>
        )
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
