import { useCallback, useEffect, useState } from "react";
import { api, SectionReadinessMap } from "./api";

// Reads the server-DERIVED per-section readiness map. The wizard never guesses
// which sections are unlocked — it calls refresh() after each authoring mutation
// (generate / save / approve / unapprove) and lets the backend recompute
// readiness from what is approved on disk plus the declared dependency table.
// This replaces the legacy imperative ready.methods / ready.summary flags.
export function useSectionReadiness(dtxsid: string | null) {
  const [readiness, setReadiness] = useState<SectionReadinessMap>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!dtxsid) {
      setReadiness({});
      return;
    }
    setLoading(true);
    setError(null);
    try {
      setReadiness(await api.getSectionReadiness(dtxsid));
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
