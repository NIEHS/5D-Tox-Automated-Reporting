import { useCallback, useRef, useSyncExternalStore } from "react";

// A tiny reactive query cache — the one abstraction behind every "read
// server-derived state and stay in sync with it" hook in the wizard.
//
// WHY this exists: the wizard's UI is a pure function of SERVER truth (phase,
// section readiness, publish gate are all DERIVED on the backend, never guessed
// on the client — the same "derive, never imperatively set" invariant the
// backend enforces). The failure mode was expressing that reactively as manual
// re-pulls: every mutation had to REMEMBER to call refreshPhase() + refreshReadiness()
// + refreshPublish() + materializePreview(), a hand-maintained dependency list
// that silently goes stale when a caller forgets one.
//
// This replaces that with DECLARATIVE invalidation: a resource is keyed (e.g.
// `readiness:DTXSID`), components subscribe by key, and a mutation calls
// invalidate("DTXSID") — which re-pulls EVERY resource whose key contains that
// substring, and re-renders every subscriber. No caller maintains a refresh list.
//
// Deliberately homegrown (no React Query / SWR dependency) — the surface we need
// is small and the "simpler UI library" ethos that chose Alpine over a framework
// applies here too. Built on useSyncExternalStore, so it obeys that hook's
// contract: getSnapshot must return a STABLE reference between changes and a NEW
// reference when the data changes (mutating one object in place would make React
// bail on Object.is and never re-render — the classic pitfall). Each entry
// therefore keeps an immutable `snapshot` that is rebuilt only on a real change.

export interface Snapshot<T> {
  data: T | undefined;
  loading: boolean;
  error: string | null;
}

interface Entry<T> {
  snapshot: Snapshot<T>; // immutable; replaced (new ref) only on a real change
  promise: Promise<void> | null; // in-flight fetch, so N subscribers share ONE request
  fetcher: () => Promise<T>;
  subscribers: Set<() => void>;
}

// Stable snapshot for the "no key / no resource yet" case — a constant reference
// so getSnapshot never returns a fresh object (which would loop useSyncExternalStore).
const NULL_SNAPSHOT: Snapshot<unknown> = { data: undefined, loading: false, error: null };

// One global cache for the app. Keyed by an opaque string the caller chooses.
const cache = new Map<string, Entry<unknown>>();

function getEntry<T>(key: string, fetcher: () => Promise<T>): Entry<T> {
  let entry = cache.get(key) as Entry<T> | undefined;
  if (!entry) {
    entry = {
      snapshot: { data: undefined, loading: false, error: null },
      promise: null,
      fetcher,
      subscribers: new Set(),
    };
    cache.set(key, entry as Entry<unknown>);
  } else {
    // Keep the latest fetcher closure (it may close over fresh props).
    entry.fetcher = fetcher;
  }
  return entry;
}

// Replace the entry's snapshot with a NEW object (so useSyncExternalStore sees a
// change) and notify subscribers to re-read.
function setSnapshot<T>(entry: Entry<T>, patch: Partial<Snapshot<T>>) {
  entry.snapshot = { ...entry.snapshot, ...patch };
  entry.subscribers.forEach((cb) => cb());
}

// Kick off a fetch for an entry unless one is already in flight. Subscribers
// share the single in-flight promise, so mounting three components on the same
// key triggers ONE request, not three.
function load<T>(key: string): Promise<void> {
  const entry = cache.get(key) as Entry<T> | undefined;
  if (!entry) return Promise.resolve();
  if (entry.promise) return entry.promise;

  setSnapshot(entry, { loading: true, error: null });

  const p = entry
    .fetcher()
    .then((data) => {
      setSnapshot(entry, { data, error: null });
    })
    .catch((e: unknown) => {
      setSnapshot(entry, { error: e instanceof Error ? e.message : String(e) });
    })
    .finally(() => {
      entry.promise = null;
      setSnapshot(entry, { loading: false });
    });

  entry.promise = p;
  return p;
}

// Invalidate every cached resource whose key CONTAINS `prefix`, re-pulling each
// that currently has subscribers (an unmounted resource just drops its stale
// data and re-fetches when next mounted). This is the one call a mutation makes:
// invalidate(dtxsid) -> everything derived from that session re-syncs.
export function invalidate(prefix: string): Promise<void> {
  const jobs: Promise<void>[] = [];
  for (const [key, entry] of cache) {
    if (!key.includes(prefix)) continue;
    if (entry.subscribers.size > 0) {
      jobs.push(load(key));
    } else {
      // No live subscriber — drop the stale value so a later mount re-fetches.
      setSnapshot(entry, { data: undefined });
    }
  }
  return Promise.all(jobs).then(() => undefined);
}

export interface ServerResource<T> {
  data: T | undefined;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

// Subscribe a component to a keyed server resource. `key === null` means "no
// resource yet" (e.g. no session selected) — returns empty/idle and fetches
// nothing. The fetcher is only invoked for a non-null key; on first subscribe
// (or after invalidation cleared the data) it auto-loads.
export function useServerResource<T>(
  key: string | null,
  fetcher: () => Promise<T>,
  fallback: T
): ServerResource<T> {
  // Keep the newest fetcher without making it part of the subscription identity.
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const subscribe = useCallback(
    (cb: () => void) => {
      if (key === null) return () => {};
      const entry = getEntry<T>(key, () => fetcherRef.current());
      entry.subscribers.add(cb);
      // Auto-load on first mount or when data was invalidated away.
      if (entry.snapshot.data === undefined && entry.promise === null) {
        void load<T>(key);
      }
      return () => {
        entry.subscribers.delete(cb);
      };
    },
    [key]
  );

  // Returns the entry's immutable snapshot (stable ref between changes, new ref on
  // change) — the useSyncExternalStore contract. The null-key case returns the
  // shared constant so it never churns.
  const getSnapshot = useCallback((): Snapshot<T> => {
    if (key === null) return NULL_SNAPSHOT as Snapshot<T>;
    return getEntry<T>(key, () => fetcherRef.current()).snapshot;
  }, [key]);

  const snap = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  const refresh = useCallback(async () => {
    if (key === null) return;
    // Force a re-pull even if data is present (explicit user/caller refresh).
    const e = cache.get(key);
    if (e) e.promise = null;
    await load<T>(key);
  }, [key]);

  return {
    data: snap.data ?? fallback,
    loading: snap.loading,
    error: snap.error,
    refresh,
  };
}
