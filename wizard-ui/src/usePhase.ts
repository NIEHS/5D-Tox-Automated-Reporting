import { api, WorkflowState } from "./api";
import { useServerResource } from "./useServerResource";

// Reads the server-derived workflow state. The wizard never guesses the phase;
// the backend derives it from disk artifacts. Now backed by the shared reactive
// query cache (useServerResource) keyed `phase:<dtxsid>`, so a mutation calling
// invalidate(dtxsid) re-syncs it automatically — no manual refresh chain.
export function usePhase(dtxsid: string | null) {
  const { data, loading, error, refresh } = useServerResource<WorkflowState | null>(
    dtxsid ? `phase:${dtxsid}` : null,
    () => api.getState(dtxsid as string),
    null
  );
  return { state: data ?? null, loading, error, refresh };
}
