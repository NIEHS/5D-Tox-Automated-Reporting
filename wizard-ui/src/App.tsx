import { useState } from "react";
import { useMemoState } from "./steps/shared";
import { usePhase } from "./usePhase";
import { Phase, ProcessPayload } from "./api";
import { SessionPicker } from "./steps/SessionPicker";
import { Upload } from "./steps/Upload";
import { Validate } from "./steps/Validate";
import { ConfirmMetadata } from "./steps/ConfirmMetadata";
import { Integrate } from "./steps/Integrate";
import { DataTree } from "./steps/DataTree";
import { Approve } from "./steps/Approve";
import { Process } from "./steps/Process";
import { Results } from "./steps/Results";

// The wizard is split into two modes, chosen by URL path:
//   /wizard/         → INGEST: prepare the data pool up through approval.
//   /wizard/report   → REPORT: run the (long) processing + view results.
// Both share the selected session via sessionStorage, so approving in ingest
// mode and following the "Generate report" link lands on the same session.
const INGEST_STEPS = [
  { key: "session", label: "Session" },
  { key: "upload", label: "Upload" },
  { key: "validate", label: "Validate" },
  { key: "confirm", label: "Confirm" },
  { key: "integrate", label: "Integrate" },
  { key: "tree", label: "Data tree" },
  { key: "approve", label: "Approve" },
] as const;

const REPORT_STEPS = [
  { key: "process", label: "Process" },
  { key: "results", label: "Results" },
] as const;

type StepKey =
  | (typeof INGEST_STEPS)[number]["key"]
  | (typeof REPORT_STEPS)[number]["key"];

function isReportMode(): boolean {
  return window.location.pathname.replace(/\/+$/, "").endsWith("/report");
}

// Phase → active step index, per mode. A hint for the stepper; the user can
// still click any chip.
function phaseToStepIndex(phase: Phase | null, report: boolean): number {
  if (report) return 0; // report mode always starts at Process
  switch (phase) {
    case "EMPTY":
      return 1; // Upload
    case "UPLOADED":
    case "VALIDATION_ERRORS":
      return 2; // Validate
    case "VALIDATED":
      return 3; // Confirm
    case "INTEGRATED":
      return 5; // Data tree (view integrated), then Approve
    case "APPROVED":
      return 6; // Approve (done) — offer the report link
    default:
      return 0;
  }
}

export function App() {
  const report = isReportMode();
  const STEPS = report ? REPORT_STEPS : INGEST_STEPS;

  const [dtxsid, setDtxsid] = useMemoState<string | null>("wizard.dtxsid", null);
  const [stepIndex, setStepIndex] = useMemoState<number>(
    report ? "wizard.report.step" : "wizard.step",
    0
  );
  const [processResult, setProcessResult] = useState<ProcessPayload | null>(null);
  const { state, refresh } = usePhase(dtxsid);

  const phase = state?.phase ?? null;
  const suggested = phaseToStepIndex(phase, report);

  function goto(i: number) {
    setStepIndex(Math.max(0, Math.min(STEPS.length - 1, i)));
  }

  async function afterMutation() {
    await refresh();
  }

  const common = {
    dtxsid,
    setDtxsid,
    state,
    refresh: afterMutation,
    next: () => goto(stepIndex + 1),
    back: () => goto(stepIndex - 1),
    processResult,
    setProcessResult,
    gotoReport: () => window.location.assign("/wizard/report"),
    gotoIngest: () => window.location.assign("/wizard/"),
  };

  function renderStep() {
    const key = STEPS[stepIndex].key as StepKey;
    switch (key) {
      case "session":
        return <SessionPicker {...common} />;
      case "upload":
        return <Upload {...common} />;
      case "validate":
        return <Validate {...common} />;
      case "confirm":
        return <ConfirmMetadata {...common} />;
      case "integrate":
        return <Integrate {...common} />;
      case "tree":
        return <DataTree {...common} />;
      case "approve":
        return <Approve {...common} />;
      case "process":
        return <Process {...common} />;
      case "results":
        return <Results {...common} />;
      default:
        return null;
    }
  }

  return (
    <div className="wizard">
      <div className="wizard-header">
        <h1>5D-Tox {report ? "Report" : "Data Prep"} Wizard</h1>
        <span className="session">
          {report && (
            <a href="/wizard/" style={{ marginRight: 12, color: "var(--accent)" }}>
              ← data prep
            </a>
          )}
          {dtxsid || "no session"}
        </span>
      </div>

      <div className="stepper">
        {STEPS.map((s, i) => {
          const cls =
            i === stepIndex
              ? "step-chip active"
              : i < suggested
              ? "step-chip done"
              : "step-chip";
          return (
            <div key={s.key} className={cls} onClick={() => goto(i)} role="button">
              <span className="dot">{i < suggested ? "✓" : i + 1}</span>
              {s.label}
            </div>
          );
        })}
      </div>

      {renderStep()}

      {phase && (
        <p className="muted" style={{ marginTop: "1rem", fontSize: "0.78rem" }}>
          Server phase: <strong>{phase}</strong> · legal:{" "}
          {state?.legal_actions.join(", ") || "—"}
        </p>
      )}
    </div>
  );
}
