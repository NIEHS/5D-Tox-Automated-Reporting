import { useCallback, useEffect, useState } from "react";
import { api, WorkflowState } from "./api";

// Reads the server-derived workflow state. The wizard never guesses the phase;
// it calls refresh() after each mutating step and lets the backend tell it where
// the pool actually is (phase is derived from disk artifacts).
export function usePhase(dtxsid: string | null) {
  const [state, setState] = useState<WorkflowState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!dtxsid) {
      setState(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      setState(await api.getState(dtxsid));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [dtxsid]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { state, loading, error, refresh };
}
