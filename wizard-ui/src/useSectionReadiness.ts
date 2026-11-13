import { api, SectionReadinessMap } from "./api";
import { useServerResource } from "./useServerResource";

// Reads the server-DERIVED per-section readiness map. The wizard never guesses
// which sections are unlocked — the backend recomputes readiness from what is
// approved on disk plus the declared dependency table. Backed by the shared
// reactive query cache keyed `readiness:<dtxsid>`, so invalidate(dtxsid) after an
// authoring mutation re-syncs it with no manual refresh chain. Replaces the
// legacy imperative ready.methods / ready.summary flags.
export function useSectionReadiness(dtxsid: string | null) {
  const { data, loading, error, refresh } = useServerResource<SectionReadinessMap>(
    dtxsid ? `readiness:${dtxsid}` : null,
    () => api.getSectionReadiness(dtxsid as string),
    {}
  );
  return { readiness: data ?? {}, loading, error, refresh };
}
