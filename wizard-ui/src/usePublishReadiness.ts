import { api, PublishReadiness } from "./api";
import { useServerResource } from "./useServerResource";

// Re-export so existing importers of these types from this module keep working
// (the shapes now live in api.ts alongside the fetch).
export type { PublishReadiness, PublishBlocker } from "./api";

// Reads the server-DERIVED report-grain publish gate (Phase 3a currency BLOCK).
// A data reprocess withdraws FINAL from the report's LLM sections and stamps each
// with a `regenerated` reason; publishing is BLOCKED until a human re-accepts
// every one. Rendered ENTIRELY from this — never a client-side guess. Backed by
// the shared reactive query cache keyed `publish:<dtxsid>`, so invalidate(dtxsid)
// after a reprocess or re-accept re-syncs it with no manual refresh chain.
const EMPTY: PublishReadiness = { can_publish: true, blocking: [] };

export function usePublishReadiness(dtxsid: string | null) {
  const { data, loading, error, refresh } = useServerResource<PublishReadiness>(
    dtxsid ? `publish:${dtxsid}` : null,
    () => api.getPublishReadiness(dtxsid as string),
    EMPTY
  );
  return { readiness: data ?? EMPTY, loading, error, refresh };
}
