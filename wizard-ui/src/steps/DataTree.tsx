import { useCallback, useEffect, useState } from "react";
import { api, IntegratedTree, TreeExperiment } from "../api";
import { ErrorBox, Spinner, StepProps } from "./shared";

// Group experiments into platform → (sex/organ) → experiment for the tree.
function groupByPlatform(exps: TreeExperiment[]) {
  const byPlatform = new Map<string, TreeExperiment[]>();
  for (const e of exps) {
    const p = e.platform || "Unknown platform";
    if (!byPlatform.has(p)) byPlatform.set(p, []);
    byPlatform.get(p)!.push(e);
  }
  return byPlatform;
}

function ExperimentNode({ exp }: { exp: TreeExperiment }) {
  const [open, setOpen] = useState(false);
  const subtitle = [exp.sex, exp.organ].filter(Boolean).join(" · ");
  return (
    <li className="tree-node">
      <div className="tree-row" onClick={() => setOpen((o) => !o)} role="button">
        <span className="tree-caret">{open ? "▾" : "▸"}</span>
        <code>{exp.name}</code>
        {subtitle && <span className="tree-sub">{subtitle}</span>}
        <span className="tree-count">
          {exp.probe_count} endpoint{exp.probe_count === 1 ? "" : "s"} ·{" "}
          {exp.doses.length} dose{exp.doses.length === 1 ? "" : "s"}
        </span>
      </div>
      {open && (
        <div className="tree-endpoints">
          {exp.doses.length > 0 && (
            <p className="muted" style={{ margin: "0.2rem 0" }}>
              Doses: {exp.doses.join(", ")}
            </p>
          )}
          <ul>
            {exp.endpoints.slice(0, 500).map((ep, i) => (
              <li key={i}>
                <code>{ep}</code>
              </li>
            ))}
          </ul>
          {exp.endpoints.length > 500 && (
            <p className="muted">
              …and {exp.endpoints.length - 500} more (truncated for display).
            </p>
          )}
        </div>
      )}
    </li>
  );
}

function PlatformNode({
  platform,
  exps,
}: {
  platform: string;
  exps: TreeExperiment[];
}) {
  const [open, setOpen] = useState(true);
  const totalEndpoints = exps.reduce((s, e) => s + e.probe_count, 0);
  return (
    <li className="tree-node">
      <div
        className="tree-row platform"
        onClick={() => setOpen((o) => !o)}
        role="button"
      >
        <span className="tree-caret">{open ? "▾" : "▸"}</span>
        <strong>{platform}</strong>
        <span className="tree-count">
          {exps.length} experiment{exps.length === 1 ? "" : "s"} ·{" "}
          {totalEndpoints} endpoints
        </span>
      </div>
      {open && (
        <ul className="tree-children">
          {exps.map((e) => (
            <ExperimentNode key={e.name} exp={e} />
          ))}
        </ul>
      )}
    </li>
  );
}

export function DataTree({ dtxsid, next, back }: StepProps) {
  const [tree, setTree] = useState<IntegratedTree | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!dtxsid) return;
    setLoading(true);
    setError(null);
    try {
      setTree(await api.getIntegratedTree(dtxsid));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [dtxsid]);

  useEffect(() => {
    void load();
  }, [load]);

  const grouped = tree ? groupByPlatform(tree.experiments) : null;

  return (
    <div className="panel">
      <h2>Step 6 · Integrated data tree</h2>
      <p className="help">
        The merged <code>integrated.json</code> — the single source of truth —
        as a structural tree: platform → experiment (sex · organ) → endpoints.
        Loaded slim (names only, no numeric response arrays).
      </p>

      {loading && <Spinner label="Loading tree…" />}
      <ErrorBox error={error} />

      {tree && (
        <>
          <p>
            <span className="badge ok">{tree.experiment_count} experiments</span>{" "}
            <span className="muted">
              {tree.bmd_result_count} BMD results ·{" "}
              {tree.category_analysis_count} category analyses
            </span>
          </p>
          <ul className="tree">
            {grouped &&
              [...grouped.entries()].map(([platform, exps]) => (
                <PlatformNode key={platform} platform={platform} exps={exps} />
              ))}
          </ul>
        </>
      )}

      {tree && tree.experiment_count === 0 && (
        <p className="muted">
          No integrated data yet — run the Integrate step first.
        </p>
      )}

      <div className="actions">
        <button onClick={back}>Back</button>
        <button className="primary" onClick={next}>
          Next: Approve
        </button>
      </div>
    </div>
  );
}
