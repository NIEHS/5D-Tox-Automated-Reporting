import { api, SectionInfo } from "./api";
import { useServerResource } from "./useServerResource";

// Reads the tree-DERIVED section catalog merged with readiness
// (GET /api/workflow/{dtxsid}/sections). The Sections screen renders its row set
// from THIS instead of a hardcoded FRONT_MATTER list + approvable allowlist —
// the section identity (which sections exist, their producer kind, whether they
// are approvable) is derived from the document tree, so adding a section to the
// template surfaces it here with no client change. Shares the reactive query
// cache keyed `sections:<dtxsid>`; invalidate(dtxsid) after an authoring mutation
// re-syncs it, same as useSectionReadiness.
export function useSections(dtxsid: string | null) {
  const { data, loading, error, refresh } = useServerResource<{ sections: SectionInfo[] }>(
    dtxsid ? `sections:${dtxsid}` : null,
    () => api.getSections(dtxsid as string),
    { sections: [] }
  );
  return { sections: data?.sections ?? [], loading, error, refresh };
}
