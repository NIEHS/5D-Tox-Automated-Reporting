import { useState } from "react";
import { useMemoState } from "./steps/shared";
import { usePhase } from "./usePhase";
import { invalidate } from "./useServerResource";
import { Phase, ProcessPayload } from "./api";
import { Landing } from "./steps/Landing";
import { Upload } from "./steps/Upload";
import { Validate } from "./steps/Validate";
import { ConfirmMetadata } from "./steps/ConfirmMetadata";
import { IntegrateApprove } from "./steps/IntegrateApprove";
import { Process } from "./steps/Process";
import { Results } from "./steps/Results";
import { Author } from "./steps/Author";
import { Preview } from "./steps/Preview";
import { Query } from "./steps/Query";

// The app has three top-level surfaces, chosen by URL path:
//   /              → LANDING: pick a test article, then a workstream (dispatch).
//   /workflow/     → DATA prep: prepare the data pool up through approval.
//   /workflow/report → DOCUMENT: run the (long) processing + review + author.
// The chooser is step 0 conceptually, but it lives on the landing (NOT part of a
// workflow). The two workflows share the selected session via sessionStorage.
type Mode = "landing" | "data" | "document";

const DATA_STEPS = [
  { key: "upload", label: "Upload" },
  { key: "validate", label: "Validate" },
  { key: "confirm", label: "Confirm" },
  { key: "integrate-approve", label: "Integrate & Approve" },
] as const;

const DOCUMENT_STEPS = [
  { key: "process", label: "Process" },
  { key: "results", label: "Results" },
  { key: "author", label: "Author" },
  { key: "preview", label: "Preview" },
  { key: "query", label: "Query" },
] as const;

// Index of the query console within DOCUMENT_STEPS — the "database view" target.
const DOCUMENT_QUERY_INDEX = DOCUMENT_STEPS.findIndex((s) => s.key === "query");

type StepKey =
  | (typeof DATA_STEPS)[number]["key"]
  | (typeof DOCUMENT_STEPS)[number]["key"];

function currentMode(): Mode {
  const path = window.location.pathname.replace(/\/+$/, "");
  if (path.endsWith("/workflow/report") || path.endsWith("/report")) return "document";
  if (path.endsWith("/workflow")) return "data";
  return "landing";
}

// Phase → active step index within the DATA workflow. A hint for the stepper; the
// user can still click any chip. (DATA_STEPS no longer includes the chooser, so
// indices shift down by one from the old INGEST_STEPS.)
function phaseToDataStep(phase: Phase | null): number {
  switch (phase) {
    case "EMPTY":
      return 0; // Upload
    case "UPLOADED":
    case "VALIDATION_ERRORS":
      return 1; // Validate
    case "VALIDATED":
      return 2; // Confirm
    case "INTEGRATED":
    case "APPROVED":
      return 3; // Integrate & Approve (combined)
    default:
      return 0;
  }
}

export function App() {
  const mode = currentMode();
  const STEPS = mode === "document" ? DOCUMENT_STEPS : DATA_STEPS;

  const [dtxsid, setDtxsid] = useMemoState<string | null>("wizard.dtxsid", null);
  const [stepIndex, setStepIndex] = useMemoState<number>(
    mode === "document" ? "wizard.document.step" : "wizard.data.step",
    0
  );
  const [processResult, setProcessResult] = useState<ProcessPayload | null>(null);
  const { state, refresh } = usePhase(dtxsid);

  const phase = state?.phase ?? null;
  const suggested = mode === "document" ? 0 : phaseToDataStep(phase);

  function goto(i: number) {
    setStepIndex(Math.max(0, Math.min(STEPS.length - 1, i)));
  }

  async function afterMutation() {
    // Any step's mutation re-syncs every resource keyed to this session
    // (phase, readiness, publish, session content) via one declarative
    // invalidate — no step needs to know WHICH resources it affected.
    if (dtxsid) await invalidate(dtxsid);
    else await refresh();
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
    gotoReport: () => window.location.assign("/workflow/report"),
    gotoIngest: () => window.location.assign("/workflow/"),
    gotoLanding: () => window.location.assign("/"),
    // Deep-link to the document-mode query console: pre-seed the document step
    // index (document mode reads it from sessionStorage on load) so the console
    // opens directly instead of landing on Process.
    gotoQuery: () => {
      try {
        sessionStorage.setItem(
          "wizard.document.step",
          JSON.stringify(DOCUMENT_QUERY_INDEX)
        );
      } catch {
        /* sessionStorage unavailable — document mode just starts at Process */
      }
      window.location.assign("/workflow/report");
    },
  };

  // Landing is a standalone surface — no stepper, no per-step chrome. It owns the
  // chooser + workstream pillars and navigates into the two workflows.
  if (mode === "landing") {
    return <Landing {...common} />;
  }

  function renderStep() {
    const key = STEPS[stepIndex].key as StepKey;
    switch (key) {
      case "upload":
        return <Upload {...common} />;
      case "validate":
        return <Validate {...common} />;
      case "confirm":
        return <ConfirmMetadata {...common} />;
      case "integrate-approve":
        return <IntegrateApprove {...common} />;
      case "process":
        return <Process {...common} />;
      case "results":
        return <Results {...common} />;
      case "author":
        return <Author {...common} />;
      case "preview":
        return <Preview {...common} />;
      case "query":
        return <Query {...common} />;
      default:
        return null;
    }
  }

  return (
    <div className="wizard">
      <div className="wizard-header">
        <h1>5D-Tox {mode === "document" ? "Document" : "Data Prep"}</h1>
        <span className="session">
          <a href="/" style={{ marginRight: 12, color: "var(--accent)" }}>
            ← home
          </a>
          {mode === "document" && (
            <a
              href="/workflow/"
              style={{ marginRight: 12, color: "var(--accent)" }}
            >
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
