import { useCallback, useEffect, useState } from "react";
import { api, IntegratedTree, TreeExperiment } from "../api";
import { ErrorBox, IdentityBox, Spinner, StepProps } from "./shared";

// One combined data-prep step: merge the pool (Integrate), review what merged
// (the integrated data tree, inline), then accept it (generate the animal report
// → APPROVED). Previously three separate pages; folded into one because it is a
// single act — "merge, look, accept".

// ── Integrated-tree view (lifted from the old DataTree step) ───────────────
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

export function IntegrateApprove({
  dtxsid,
  state,
  back,
  refresh,
  gotoReport,
  gotoQuery,
}: StepProps) {
  const [name, setName] = useState("");
  const [casrn, setCasrn] = useState("");

  const [integrating, setIntegrating] = useState(false);
  const [integrateSummary, setIntegrateSummary] =
    useState<Record<string, unknown> | null>(null);

  const [tree, setTree] = useState<IntegratedTree | null>(null);
  const [treeLoading, setTreeLoading] = useState(false);

  const [approving, setApproving] = useState(false);
  const [approveReport, setApproveReport] =
    useState<Record<string, unknown> | null>(null);

  const [error, setError] = useState<string | null>(null);

  const hasIntegrated =
    state?.artifacts?.hasIntegrated === true ||
    integrateSummary !== null ||
    state?.phase === "INTEGRATED" ||
    state?.phase === "APPROVED";
  const alreadyApproved =
    state?.artifacts?.hasAnimalReport === true || state?.phase === "APPROVED";
  const hasQuerySubstrate = state?.artifacts?.hasQuerySubstrate === true;

  const loadTree = useCallback(async () => {
    if (!dtxsid) return;
    setTreeLoading(true);
    try {
      setTree(await api.getIntegratedTree(dtxsid));
    } catch (e) {
      // Tree is a review aid — a load failure shouldn't block the step.
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setTreeLoading(false);
    }
  }, [dtxsid]);

  // Load the tree on mount if the pool is already integrated (re-entered session).
  useEffect(() => {
    if (hasIntegrated) void loadTree();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dtxsid]);

  async function runIntegrate() {
    if (!dtxsid) return;
    setIntegrating(true);
    setError(null);
    try {
      const s = await api.integrate(dtxsid, {
        name: name.trim() || dtxsid,
        casrn: casrn.trim(),
        dtxsid,
      });
      setIntegrateSummary(s);
      await refresh();
      await loadTree(); // populate the review region inline, no page change
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setIntegrating(false);
    }
  }

  async function runApprove() {
    if (!dtxsid) return;
    setApproving(true);
    setError(null);
    try {
      const r = await api.approve(dtxsid);
      setApproveReport(r);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setApproving(false);
    }
  }

  const grouped = tree ? groupByPlatform(tree.experiments) : null;

  return (
    <div className="panel">
      <h2>Step 5 · Integrate &amp; Approve</h2>
      <p className="help">
        Merge the validated pool into one <code>integrated.json</code> — the
        single source of truth — then review what merged and accept it.
      </p>

      <IdentityBox dtxsid={dtxsid} />

      <ErrorBox error={error} />

      {/* ── Integrate region ─────────────────────────────────────────── */}
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

      <button className="primary" onClick={runIntegrate} disabled={integrating}>
        {integrating ? (
          <Spinner label="Integrating… (1–2 min)" />
        ) : hasIntegrated ? (
          "Re-run integration"
        ) : (
          "Run integration"
        )}
      </button>
      {integrating && (
        <p className="long-note">
          This is a long, blocking step — keep this tab open until it finishes.
        </p>
      )}

      {hasIntegrated && (
        <p style={{ marginTop: "1rem" }}>
          <span className="badge ok">integrated</span>{" "}
          {integrateSummary && (
            <span className="muted">
              {String(integrateSummary.experiment_count ?? "?")} experiments ·{" "}
              {String(integrateSummary.bmd_result_count ?? "?")} BMD results ·{" "}
              {String(integrateSummary.category_analysis_count ?? "?")} category
              analyses
            </span>
          )}
        </p>
      )}

      {/* ── Review region (inline data tree) ─────────────────────────── */}
      {hasIntegrated && (
        <div style={{ marginTop: "1.25rem" }}>
          <h3 className="group-heading">Review integrated data</h3>
          <p className="help" style={{ marginTop: 0 }}>
            The merged data as a structural tree: platform → experiment
            (sex · organ) → endpoints. Loaded slim (names only).
          </p>
          {treeLoading && <Spinner label="Loading tree…" />}
          {tree && (
            <>
              <p>
                <span className="badge ok">
                  {tree.experiment_count} experiments
                </span>{" "}
                <span className="muted">
                  {tree.bmd_result_count} BMD results ·{" "}
                  {tree.category_analysis_count} category analyses
                </span>
              </p>
              <ul className="tree">
                {grouped &&
                  [...grouped.entries()].map(([platform, exps]) => (
                    <PlatformNode
                      key={platform}
                      platform={platform}
                      exps={exps}
                    />
                  ))}
              </ul>
            </>
          )}
        </div>
      )}

      {/* ── Approve region ───────────────────────────────────────────── */}
      {hasIntegrated && (
        <div style={{ marginTop: "1.25rem" }}>
          <h3 className="group-heading">Approve</h3>
          <p className="help" style={{ marginTop: 0 }}>
            Generate the per-animal traceability report — every animal mapped to
            dose, sex, and selection (core vs biosampling). Its presence advances
            the pool to <code>APPROVED</code>.
          </p>
          <button
            className="primary"
            onClick={runApprove}
            disabled={approving || alreadyApproved}
          >
            {approving ? (
              <Spinner label="Generating…" />
            ) : alreadyApproved ? (
              "Animal report generated"
            ) : (
              "Generate animal report"
            )}
          </button>
          {(approveReport || alreadyApproved) && (
            <p style={{ marginTop: "1rem" }}>
              <span className="badge ok">approved</span>{" "}
              {approveReport && (
                <span className="muted">
                  {String(approveReport.total_animals ?? "?")} animals ·{" "}
                  {String(approveReport.core_count ?? "?")} core /{" "}
                  {String(approveReport.biosampling_count ?? "?")} biosampling
                </span>
              )}
            </p>
          )}
        </div>
      )}

      {/* ── Footer actions ───────────────────────────────────────────── */}
      <div className="actions">
        <button onClick={back}>Back</button>
        <button
          onClick={gotoQuery}
          disabled={!hasQuerySubstrate}
          title={
            hasQuerySubstrate
              ? "Open the queryable database console for this session"
              : "Run Process first to build the queryable database."
          }
        >
          Database view
        </button>
        <button
          className="primary"
          disabled={!alreadyApproved}
          onClick={gotoReport}
        >
          Generate report →
        </button>
      </div>
    </div>
  );
}
