import { useEffect, useMemo, useState } from "react";
import {
  api,
  Comparison,
  ComparisonOutput,
  ComparisonSummary,
  CompareModels,
} from "../api";
import { Spinner, WarningBox } from "./shared";

// Model comparison: run the section's prompt on several models, several times
// each, and have an arbiter — a model that generated nothing — review the
// drafts blind (A1, A2, B1 … in a shuffled order) and recommend one. Every
// comparison is archived per study and numbered; past ones open read-only.
// Which models may see an unpublished study's data is the server's policy
// (narrative/model_policy.yaml); models it refuses are shown but disabled.
export function ModelComparison({ section, study, template, templateLabel, onUse }: {
  section: string;
  study: string;
  template?: string; // the editor's unsaved text; undefined runs the current version
  templateLabel: string;
  onUse: (runId: string) => Promise<void>;
}) {
  const [models, setModels] = useState<CompareModels | null>(null);
  const [filter, setFilter] = useState("");
  const [generators, setGenerators] = useState<string[]>([]);
  const [repetitions, setRepetitions] = useState(2);
  const [arbiter, setArbiter] = useState("");
  const [history, setHistory] = useState<ComparisonSummary[]>([]);
  const [shown, setShown] = useState<Comparison | null>(null);
  const [progress, setProgress] = useState<{ total: number; outputs: ComparisonOutput[]; arbiter: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const allowedIds = useMemo(
    () => (models?.categories ?? []).flatMap((c) => c.models.filter((m) => m.allowed).map((m) => m.id)),
    [models]
  );

  async function loadHistory(open?: string) {
    const { comparisons } = await api.listComparisons(section, study);
    setHistory(comparisons);
    const id = open ?? comparisons[0]?.comparison_id;
    setShown(id ? await api.getComparison(section, study, id) : null);
  }

  useEffect(() => {
    setError(null);
    setShown(null);
    setGenerators([]);
    api.getCompareModels(section, study)
      .then((m) => {
        setModels(m);
        setRepetitions((r) => Math.min(r, m.max_repetitions));
      })
      .catch((e) => setError(String(e)));
    loadHistory().catch((e) => setError(String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [study]);

  // The arbiter must not be a generator; keep it valid as the choice changes.
  useEffect(() => {
    if (!models) return;
    const ok = (m: string) => allowedIds.includes(m) && !generators.includes(m);
    if (!ok(arbiter)) setArbiter(newest(allowedIds.filter((m) => ok(m) && /opus/.test(m))) ?? allowedIds.find(ok) ?? "");
  }, [models, generators, arbiter, allowedIds]);

  function toggle(id: string) {
    setGenerators((g) => (g.includes(id) ? g.filter((x) => x !== id) : [...g, id]));
  }

  async function run() {
    setError(null);
    setProgress({ total: generators.length * repetitions, outputs: [], arbiter: false });
    try {
      const rec = await api.runComparison(
        section,
        { dtxsid: study, generators, repetitions, arbiter, ...(template !== undefined ? { template } : {}) },
        (ev) => {
          if (ev.event === "output")
            setProgress((p) => p && { ...p, outputs: [...p.outputs, ev.data as ComparisonOutput] });
          else if (ev.event === "arbiter") setProgress((p) => p && { ...p, arbiter: true });
        }
      );
      await loadHistory(rec.comparison_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setProgress(null);
    }
  }

  const max = models?.max_generators ?? 6;
  const tooMany = generators.length > max;
  const canRun = !!generators.length && !tooMany && !!arbiter && !progress;
  const q = filter.trim().toLowerCase();

  return (
    <section className="workshop-panel compare">
      <div className="workshop-toolbar">
        <strong>Compare models</strong>
        <span className="muted">
          Run the prompt ({templateLabel}) on several models, several times each, then have an
          arbiter review the drafts blind and recommend one.
        </span>
      </div>
      {error && <div className="error-box">{error}</div>}
      {models && !models.published && (
        <WarningBox
          warning={`Unpublished study: its data may only go to models matching ${models.unpublished_allowed.join(", ")} (narrative/model_policy.yaml). Others are disabled.`}
        />
      )}
      {models?.degraded && <WarningBox warning="The model list could not be fetched from the gateway; showing a fallback list." />}

      <div className="compare-config">
        <div className="compare-models">
          <div className="workshop-toolbar">
            <span>Generating models</span>
            <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="filter…" />
            <span className={tooMany ? "compare-too-many" : "muted"}>{generators.length} of at most {max}</span>
          </div>
          {generators.length > 0 && (
            <div className="compare-chips">
              {generators.map((g) => (
                <button key={g} className="small" onClick={() => toggle(g)} title="Remove">{g} ×</button>
              ))}
            </div>
          )}
          <div className="compare-list">
            {(models?.categories ?? []).map((c) => {
              const ms = c.models.filter((m) => !q || m.id.toLowerCase().includes(q));
              if (!ms.length) return null;
              return (
                <div key={c.name}>
                  <div className="compare-cat">{c.name}</div>
                  {ms.map((m) => (
                    <label key={m.id} className={m.allowed ? "" : "disabled"}
                           title={m.allowed ? "" : "Not allowed for this unpublished study's data"}>
                      <input type="checkbox" disabled={!m.allowed || m.id === arbiter}
                             checked={generators.includes(m.id)} onChange={() => toggle(m.id)} />{" "}
                      {m.id}{m.id === arbiter ? " (arbiter)" : ""}
                    </label>
                  ))}
                </div>
              );
            })}
          </div>
        </div>
        <div className="compare-side">
          <label>
            Runs per model{" "}
            <input type="number" min={1} max={models?.max_repetitions ?? 5} value={repetitions}
                   onChange={(e) => setRepetitions(Math.max(1, Math.min(models?.max_repetitions ?? 5, Number(e.target.value) || 1)))} />
          </label>
          <label>
            Arbiter{" "}
            <select value={arbiter} onChange={(e) => setArbiter(e.target.value)}>
              {allowedIds.filter((m) => !generators.includes(m)).map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </label>
          <p className="muted">The arbiter cannot be one of the generating models.</p>
          <button className="primary" onClick={run} disabled={!canRun}>
            Run comparison ({generators.length * repetitions} drafts + review)
          </button>
          {progress && (
            <div className="compare-progress">
              <Spinner label={progress.arbiter ? `The arbiter (${arbiter}) is reviewing…`
                : `${progress.outputs.length} of ${progress.total} drafts…`} />
              {progress.outputs.map((o, i) => (
                <div key={i} className={o.error ? "compare-err" : "muted"}>
                  {o.error ? "✗" : "✓"} {o.model} run {o.repetition}{o.error ? ` — ${o.error}` : ""}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {history.length > 0 && (
        <div className="workshop-toolbar compare-history">
          <span>Archived comparisons</span>
          <select value={shown?.comparison_id ?? ""} onChange={(e) => loadHistory(e.target.value)}>
            {history.map((h) => (
              <option key={h.comparison_id} value={h.comparison_id}>
                #{h.number} · {h.at.slice(0, 16).replace("T", " ")} ·{" "}
                {h.template_version === null ? "unsaved edit" : `v${h.template_version}`} ·{" "}
                {h.generators.length} model{h.generators.length === 1 ? "" : "s"} × {h.repetitions} · arbiter{" "}
                {h.arbiter_model}{h.recommended_model ? ` · recommends ${h.recommended_model}` : ""}
                {h.status !== "complete" ? ` · ${h.status}` : ""}
              </option>
            ))}
          </select>
        </div>
      )}
      {shown && <ComparisonView c={shown} onUse={onUse} />}
    </section>
  );
}

// The model with the highest version number ("claude-opus-4.8" over "claude-4.1-opus").
function newest(ids: string[]): string | undefined {
  const v = (id: string) => (id.match(/\d+(?:\.\d+)?/g) ?? []).map(Number);
  return [...ids].sort((a, b) => {
    const [x, y] = [v(a), v(b)];
    for (let i = 0; i < Math.max(x.length, y.length); i++) if ((y[i] ?? 0) !== (x[i] ?? 0)) return (y[i] ?? 0) - (x[i] ?? 0);
    return a.localeCompare(b);
  })[0];
}

function ComparisonView({ c, onUse }: { c: Comparison; onUse: (runId: string) => Promise<void> }) {
  const key = c.blinding?.drafts ?? {};
  const letterOf: Record<string, string> = Object.fromEntries(
    Object.entries(c.blinding?.generators ?? {}).map(([l, m]) => [m, l]));
  const first = c.review?.recommendation?.model ?? c.generators[0];
  const [tab, setTab] = useState(first);
  const [used, setUsed] = useState<string | null>(null);
  useEffect(() => setTab(first), [c.comparison_id, first]);
  const name = (draft?: string) => {
    const k = draft ? key[draft] : undefined;
    return k ? `${draft} (${k.model}, run ${k.repetition})` : draft ?? "";
  };
  const r = c.review;
  const rec = r?.recommendation;
  const use = async (runId: string) => {
    await onUse(runId);
    setUsed(runId);
  };
  return (
    <div className="compare-view">
      <div className="muted">
        Comparison #{c.number} · {c.at.slice(0, 16).replace("T", " ")} · template{" "}
        {c.template_version === null ? "unsaved edit" : `v${c.template_version}`} · {c.generators.length} model
        {c.generators.length === 1 ? "" : "s"} × {c.repetitions} · arbiter {c.arbiter_model} · {c.status}
      </div>
      {c.review_error && <div className="error-box">Arbiter: {c.review_error}</div>}
      {r && (
        <div className="compare-review">
          <h4>Arbiter's review <span className="muted">(written blind; names restored here)</span></h4>
          {r.overview && <p>{r.overview}</p>}
          {rec && (
            <div className="compare-rec">
              <strong>Recommends {name(rec.draft)}</strong>
              {rec.unknown_draft && <span className="compare-err"> — not a draft it was shown</span>}
              {rec.reasons && <div>{rec.reasons}</div>}
              {rec.run_id && (
                <button className="small primary" onClick={() => use(rec.run_id!)} disabled={used === rec.run_id}>
                  {used === rec.run_id ? "Saved as the Summary" : "Use this as the Summary"}
                </button>
              )}
            </div>
          )}
          {!!r.fact_problems?.length && (
            <>
              <h5>Factual problems</h5>
              <ul>{r.fact_problems.map((f, i) => <li key={i}><strong>{name(f.draft)}</strong>: {f.problem}</li>)}</ul>
            </>
          )}
          {!!r.agreements?.length && (
            <>
              <h5>Where they agree</h5>
              <ul>{r.agreements.map((a, i) => <li key={i}>{a}</li>)}</ul>
            </>
          )}
          {!!r.differences?.length && (
            <>
              <h5>Where they differ</h5>
              <ul>
                {r.differences.map((d, i) => (
                  <li key={i}>
                    <strong>{d.topic}</strong>: {d.detail}
                    {d.drafts?.length ? <span className="muted"> — {d.drafts.map(name).join("; ")}</span> : null}
                  </li>
                ))}
              </ul>
            </>
          )}
          {!!r.generators?.length && (
            <>
              <h5>Each model</h5>
              <table className="compare-table">
                <thead><tr><th>model</th><th>consistency across its runs</th><th>strengths</th><th>weaknesses</th></tr></thead>
                <tbody>
                  {r.generators.map((g, i) => (
                    <tr key={i}>
                      <td>{g.generator} = {c.blinding?.generators[g.generator ?? ""] ?? "?"}</td>
                      <td>{g.consistency}</td><td>{g.strengths}</td><td>{g.weaknesses}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>
      )}

      <div className="workshop-batch-tabs compare-tabs">
        {[...c.generators].sort((a, b) => (letterOf[a] ?? "~").localeCompare(letterOf[b] ?? "~")).map((m) => {
          const outs = c.outputs.filter((o) => o.model === m);
          const failed = outs.filter((o) => o.error).length;
          const flagged = outs.filter((o) => o.unmatched_numbers.length).length;
          return (
            <button key={m} className={"workshop-batch-tab" + (m === tab ? " active" : "") + (rec?.model === m ? " recommended" : "")}
                    onClick={() => setTab(m)}>
              {letterOf[m] ? `${letterOf[m]} · ` : ""}{m}
              {rec?.model === m ? " ★" : ""}{failed ? ` ✗${failed}` : ""}{flagged ? ` ⚠${flagged}` : ""}
            </button>
          );
        })}
      </div>
      <div className="workshop-columns" style={{ gridTemplateColumns: `repeat(${Math.max(1, c.repetitions)}, minmax(0, 1fr))` }}>
        {c.outputs.filter((o) => o.model === tab).map((o) => {
          const recommended = rec?.run_id && rec.run_id === o.run_id;
          return (
            <div key={o.repetition} className={recommended ? "compare-recommended" : ""}>
              <h4>
                Run {o.repetition}{letterOf[o.model] ? ` (${letterOf[o.model]}${o.repetition})` : ""}
                {recommended ? " — recommended" : ""}
              </h4>
              {o.error && <div className="error-box">{o.error}</div>}
              {o.unmatched_numbers.length > 0 && (
                <WarningBox warning={`Numbers the model was not given: ${o.unmatched_numbers.join(", ")}`} />
              )}
              <div className="workshop-text">{o.paragraphs.map((p, i) => <p key={i}>{p}</p>)}</div>
              {o.run_id && (
                <button className="small" onClick={() => use(o.run_id!)} disabled={used === o.run_id}>
                  {used === o.run_id ? "Saved as the Summary" : "Use this as the Summary"}
                </button>
              )}
            </div>
          );
        })}
      </div>
      {c.arbiter_prompt && (
        <details className="compare-prompt">
          <summary>What the arbiter was given</summary>
          <pre className="workshop-pre">{c.arbiter_prompt.system}{"\n\n"}{c.arbiter_prompt.user}</pre>
        </details>
      )}
    </div>
  );
}
