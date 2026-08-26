import { useState } from "react";
import { ProcessPayload, WorkflowState } from "../api";

// Props every step receives from the App shell.
export interface StepProps {
  dtxsid: string | null;
  setDtxsid: (id: string | null) => void;
  state: WorkflowState | null;
  refresh: () => Promise<void>;
  next: () => void;
  back: () => void;
  // The processed payload is large (base64 chart PNGs); it is held in App memory
  // rather than serialized to storage, and passed between Process and Results.
  processResult: ProcessPayload | null;
  setProcessResult: (p: ProcessPayload | null) => void;
  // Navigate between the two wizard modes (data-prep ↔ report).
  gotoReport: () => void;
  gotoIngest: () => void;
}

// useState backed by sessionStorage so a page reload keeps the wizard position
// and selected session (the actual pool state lives on the server; this is just
// UI convenience).
export function useMemoState<T>(
  key: string,
  initial: T
): [T, (v: T | ((p: T) => T)) => void] {
  const [val, setVal] = useState<T>(() => {
    try {
      const raw = sessionStorage.getItem(key);
      return raw !== null ? (JSON.parse(raw) as T) : initial;
    } catch {
      return initial;
    }
  });
  const set = (v: T | ((p: T) => T)) => {
    setVal((prev) => {
      const nextVal = typeof v === "function" ? (v as (p: T) => T)(prev) : v;
      try {
        sessionStorage.setItem(key, JSON.stringify(nextVal));
      } catch {
        // ignore quota/serialization issues
      }
      return nextVal;
    });
  };
  return [val, set];
}

export function ErrorBox({ error }: { error: string | null }) {
  if (!error) return null;
  return <div className="error-box">{error}</div>;
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span>
      <span className="spinner" /> {label}
    </span>
  );
}
