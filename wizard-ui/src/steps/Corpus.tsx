import { useCallback, useEffect, useState } from "react";
import { api, CorpusOrgan, CorpusTweak } from "../api";
import { ErrorBox, Spinner, StepProps } from "./shared";

// Corpus curation — canonicalize the literature knowledge base's organ vocabulary.
// The frozen bmdx.duckdb is the immutable baseline; each mapping is appended to a
// per-session tweak-log (live history), and a curated working corpus.duckdb is
// materialized on demand by projecting that log onto a copy of the original.
// The narrative's organ signature reads genes.organs, so these mappings are what
// a later "regenerate against the curated corpus" experiment would move.

export function Corpus({ dtxsid, back }: StepProps) {
  const [inventory, setInventory] = useState<CorpusOrgan[]>([]);
  const [canonical, setCanonical] = useState<string[]>([]);
  const [tweaks, setTweaks] = useState<CorpusTweak[]>([]);
  const [isCurated, setIsCurated] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [materializeMsg, setMaterializeMsg] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  // Per-row target-input buffer, keyed by organ term.
  const [targets, setTargets] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    if (!dtxsid) return;
    setLoading(true);
    setError(null);
    try {
      const [org, hist] = await Promise.all([
        api.getCorpusOrgans(dtxsid),
        api.getCorpusHistory(dtxsid),
      ]);
      setInventory(org.inventory);
      setCanonical(org.canonical);
      setIsCurated(org.is_curated);
      setTweaks(hist.tweaks);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [dtxsid]);

  useEffect(() => {
    void load();
  }, [load]);

  async function applyMap(from: string, to: string | null) {
    if (!dtxsid) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.mapCorpusOrgan(dtxsid, from, to);
      // Prepend to the live history immediately (newest-first display).
      setTweaks((prev) => [...prev, r.tweak]);
      // Reflect the net mapping on the inventory row.
      setInventory((prev) =>
        prev.map((row) => (row.organ === from ? { ...row, mapped_to: to } : row))
      );
      setTargets((prev) => ({ ...prev, [from]: "" }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function materialize() {
    if (!dtxsid) return;
    setBusy(true);
    setError(null);
    setMaterializeMsg(null);
    try {
      const r = await api.materializeCorpus(dtxsid);
      setIsCurated(true);
      setMaterializeMsg(
        `Curated corpus built — ${r.counts.distinct_gene_organs} distinct gene organs, ` +
          `${r.counts.paper_organs} paper-organ rows (${r.applied_mappings} mappings applied).`
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    if (!dtxsid) return;
    setBusy(true);
    setError(null);
    setMaterializeMsg(null);
    try {
      await api.resetCorpus(dtxsid);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!dtxsid) {
    return (
      <div className="panel">
        <h2>Corpus curation</h2>
        <p className="help">Select a session first.</p>
      </div>
    );
  }

  const rows = filter
    ? inventory.filter((r) => r.organ.includes(filter.toLowerCase()))
    : inventory;

  return (
    <div className="panel">
      <h2>Corpus curation — organ vocabulary</h2>
      <p className="help">
        The literature knowledge base tags papers and genes with organ terms — many
        noisy (cell types, cancer specimens, vague categories). Canonicalize them here:
        each mapping is recorded in a live history, and a curated working corpus is
        built on demand. The original knowledge base is never modified.
      </p>

      <ErrorBox error={error} />
      {loading ? (
        <Spinner label="Loading organ vocabulary…" />
      ) : (
        <div className="kg-grid">
          <div className="configure-form">
            <div className="group-heading-row">
              <span className="group-heading">
                Organ terms ({inventory.length})
              </span>
              <input
                type="text"
                placeholder="filter…"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                className="corpus-filter"
              />
            </div>

            <div className="corpus-list">
              {rows.map((row) => (
                <div key={row.organ} className="corpus-row">
                  <div className="corpus-term">
                    <span className="corpus-name">{row.organ}</span>
                    <span className="corpus-meta">
                      {row.total}× · {row.sources.join("+")}
                    </span>
                    {row.mapped_to === null && row.organ in netKeys(tweaks) ? (
                      <span className="badge kg-removed">dropped</span>
                    ) : row.mapped_to ? (
                      <span className="badge ok">→ {row.mapped_to}</span>
                    ) : null}
                  </div>
                  <div className="corpus-actions">
                    <input
                      type="text"
                      list="canonical-organs"
                      placeholder="map to…"
                      value={targets[row.organ] ?? ""}
                      onChange={(e) =>
                        setTargets((p) => ({ ...p, [row.organ]: e.target.value }))
                      }
                      disabled={busy}
                    />
                    <button
                      onClick={() => applyMap(row.organ, targets[row.organ]?.trim() || null)}
                      disabled={busy || !targets[row.organ]?.trim()}
                    >
                      Map
                    </button>
                    <button
                      className="danger"
                      onClick={() => applyMap(row.organ, null)}
                      disabled={busy}
                      title="Drop this organ term"
                    >
                      Drop
                    </button>
                  </div>
                </div>
              ))}
            </div>
            <datalist id="canonical-organs">
              {canonical.map((c) => (
                <option key={c} value={c} />
              ))}
            </datalist>
          </div>

          <aside className="kg-changes corpus-history">
            <div className="group-heading">Corpus history</div>
            <p className="help" style={{ marginTop: 0 }}>
              {tweaks.length} tweak{tweaks.length === 1 ? "" : "s"} ·{" "}
              {isCurated ? "curated corpus built" : "not yet materialized"}
            </p>
            <div className="config-save">
              <button className="primary" onClick={materialize} disabled={busy || tweaks.length === 0}>
                {busy ? <Spinner label="Building…" /> : "Materialize curated corpus"}
              </button>
              <button onClick={reset} disabled={busy}>
                Reset to original
              </button>
            </div>
            {materializeMsg && <p className="help kg-added">{materializeMsg}</p>}
            {tweaks.length === 0 ? (
              <p className="help">No curation yet — map or drop a term to begin.</p>
            ) : (
              <ul className="kg-change-list">
                {[...tweaks].reverse().map((t, i) => (
                  <li key={`${t.ts}-${i}`}>
                    <code>{t.from}</code>{" "}
                    {t.to === null ? (
                      <span className="kg-removed">dropped</span>
                    ) : (
                      <>
                        → <strong>{t.to}</strong>
                      </>
                    )}
                    <div className="corpus-ts">{t.ts}</div>
                  </li>
                ))}
              </ul>
            )}
          </aside>
        </div>
      )}

      <div className="actions">
        <button onClick={back}>Back</button>
      </div>
    </div>
  );
}

// Terms that appear as a key in the tweak log (so we can distinguish an explicit
// drop, mapped_to:null, from a term simply never touched).
function netKeys(tweaks: CorpusTweak[]): Record<string, true> {
  const out: Record<string, true> = {};
  for (const t of tweaks) out[t.from] = true;
  return out;
}
