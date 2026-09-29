import { useEffect, useState } from "react";
import { api, ProcessPayload, WorkflowState } from "../api";

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
  // Navigate between the surfaces (landing ↔ data-prep ↔ document).
  gotoReport: () => void;
  gotoIngest: () => void;
  gotoLanding: () => void;
  gotoConfigure: () => void;
  gotoKnowledgeGraph: () => void;
  gotoCorpus: () => void;
  // Jump straight to the document-mode query console (the database view).
  gotoQuery: () => void;
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

// Non-blocking notice (amber): something the author must look at but that does
// not stop the step — e.g. citations the verification layer could not resolve.
export function WarningBox({ warning }: { warning: string | null }) {
  if (!warning) return null;
  return <div className="warning-box">{warning}</div>;
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span>
      <span className="spinner" /> {label}
    </span>
  );
}

// Read-only display of a compound's cross-identifiers (name / CASRN / DTXSID /
// PubChem CID / EC number / IUPAC name). Renders only the identifiers actually
// present in identity.json, in a stable order. Shown on the session picker and
// the Integrate & Approve step so the operator can confirm which compound they
// are working with. Purely informational — never editable.
const IDENTITY_FIELDS: { key: string; label: string }[] = [
  { key: "name", label: "Name" },
  { key: "casrn", label: "CASRN" },
  { key: "dtxsid", label: "DTXSID" },
  { key: "pubchem_cid", label: "PubChem CID" },
  { key: "ec_number", label: "EC number" },
  { key: "iupac_name", label: "IUPAC name" },
];

export function IdentityBox({ dtxsid }: { dtxsid: string | null }) {
  const [identity, setIdentity] = useState<Record<string, string> | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!dtxsid) {
      setIdentity(null);
      return;
    }
    api
      .getIdentity(dtxsid)
      .then((r) => {
        if (!cancelled) setIdentity(r.identity || {});
      })
      .catch(() => {
        if (!cancelled) setIdentity({});
      });
    return () => {
      cancelled = true;
    };
  }, [dtxsid]);

  if (!dtxsid || !identity) return null;

  const rows = IDENTITY_FIELDS.filter(
    (f) => identity[f.key] != null && String(identity[f.key]).trim() !== ""
  );
  if (rows.length === 0) return null;

  return (
    <div className="identity-box">
      <div className="identity-box-head">Compound identifiers</div>
      <dl>
        {rows.map((f) => (
          <div key={f.key} className="identity-row">
            <dt>{f.label}</dt>
            <dd>
              <code>{String(identity[f.key])}</code>
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
