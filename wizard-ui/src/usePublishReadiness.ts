import { useCallback, useEffect, useState } from "react";

// Reads the server-DERIVED report-grain publish gate (Phase 3a currency BLOCK):
//   GET /api/workflow/{dtxsid}/publish-readiness
//     -> { can_publish: boolean, blocking: [{ section_key, reason }] }
//
// A data reprocess stales the report's LLM sections and stamps each with a
// `regenerated` reason; publishing is BLOCKED until a human re-accepts every one.
// The UI renders the Publish action's enabled state and the "regenerated because
// {reason} — re-accept" per-section banners ENTIRELY from this — never a
// client-side guess. Call refresh() after any reprocess or section re-accept.
//
// Self-contained (its own fetch + types) so it composes with the wizard's api.ts
// without depending on edits in flight there; the fetch can later be folded into
// api.ts as `api.getPublishReadiness` to match the section-readiness pattern.

export interface PublishBlocker {
  section_key: string;
  reason: string;
}

export interface PublishReadiness {
  can_publish: boolean;
  blocking: PublishBlocker[];
}

const EMPTY: PublishReadiness = { can_publish: true, blocking: [] };

export function usePublishReadiness(dtxsid: string | null) {
  const [readiness, setReadiness] = useState<PublishReadiness>(EMPTY);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!dtxsid) {
      setReadiness(EMPTY);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch(
        `/api/workflow/${encodeURIComponent(dtxsid)}/publish-readiness`
      );
      if (!resp.ok) throw new Error(`publish-readiness ${resp.status}`);
      setReadiness((await resp.json()) as PublishReadiness);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [dtxsid]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { readiness, loading, error, refresh };
}
