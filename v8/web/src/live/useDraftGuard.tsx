import { createContext, useCallback, useContext, useEffect, useMemo, useRef } from "react";
import { useQueryClient, type QueryKey } from "@tanstack/react-query";
import { subscribeFeed } from "./feed";
import { affectedBy } from "./affectedQueries";
import { attentionChanged } from "./notificationEvents";

interface DraftGuardValue {
  hasDirty: () => boolean;
  setDirty: (id: string, dirty: boolean, subject?: string) => void;
}
const DraftGuardContext = createContext<DraftGuardValue | null>(null);

/** One view feed and one 250ms window: each delivered event invalidates only the queries it
 * affects, coalesced to one refetch per key per window.
 *
 * S19 (chat freeze, owner m-845b58f25c): a dirty draft NO LONGER holds live refresh. Holding the
 * page query while a draft existed — and drafts persist across reloads and hide inside a collapsed
 * composer — froze the thread until a manual refresh or a send. Drafts are component state keyed by
 * a stable owner (Composer/GateForm/CriterionCard stay mounted through a background refetch), so a
 * refresh never touches their text, caret or focus. The dirty registry stays for leave-page guards
 * (NotificationCenter never navigates away from an unsent draft). */
export function DraftGuardProvider({ children }: { children: React.ReactNode }): React.JSX.Element {
  const qc = useQueryClient();
  const dirty = useRef(new Map<string, string | undefined>());
  const queued = useRef(new Map<string, QueryKey>());
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // S22 (consult #2, refresh storm): invalidating with the default cancelRefetch:true aborted the
  // in-flight refetch every window, so under sustained events (one per 150 ms, 1 s API latency) no
  // refetch ever completed and the page froze until the feed went quiet. Now a key whose refetch is
  // still in flight stays queued for the next window (it is never cancelled), and its trailing
  // refetch after it lands picks up every event that arrived meanwhile — one fetch in flight per key.
  const drain = useCallback(() => {
    timer.current = null;
    for (const [hash, queryKey] of queued.current) {
      if (qc.getQueryCache().get(hash)?.state.fetchStatus === "fetching") continue;
      queued.current.delete(hash);
      void qc.invalidateQueries({ queryKey, exact: true }, { cancelRefetch: false });
    }
    if (queued.current.size) timer.current = setTimeout(drain, 250);
  }, [qc]);
  const setDirty = useCallback((id: string, value: boolean, subject?: string) => {
    if (value) dirty.current.set(id, subject);
    else dirty.current.delete(id);
  }, []);
  useEffect(() => {
    const stop = subscribeFeed((event) => {
      // The view feed carries every event; `why` is set only when it pages this viewer.
      if (event.why && (event.kind === "message_sent" || event.kind === "gate_opened")) attentionChanged();
      const cache = qc.getQueryCache().getAll();
      for (const query of cache) {
        if (affectedBy(event, query, cache)) queued.current.set(query.queryHash, query.queryKey);
      }
      if (!timer.current && queued.current.size) timer.current = setTimeout(drain, 250);
    }, { watch: true });
    // A deferred key refetches the moment its in-flight fetch lands, not at the next window, so the
    // newest event is on screen one API round-trip after the in-flight one (≤ 2 × latency).
    const unwatch = qc.getQueryCache().subscribe((e) => {
      if (e.type !== "updated" || e.query.state.fetchStatus !== "idle") return;
      const queryKey = queued.current.get(e.query.queryHash);
      if (!queryKey) return;
      queued.current.delete(e.query.queryHash);
      void qc.invalidateQueries({ queryKey, exact: true }, { cancelRefetch: false });
    });
    return () => { stop(); unwatch(); if (timer.current) clearTimeout(timer.current); timer.current = null; };
  }, [qc, drain]);
  const hasDirty = useCallback(() => dirty.current.size > 0, []);
  const value = useMemo(() => ({ setDirty, hasDirty }), [setDirty, hasDirty]);
  return <DraftGuardContext.Provider value={value}>{children}</DraftGuardContext.Provider>;
}
export function useDraftGuard(): DraftGuardValue { return useContext(DraftGuardContext) ?? NOOP; }
const NOOP: DraftGuardValue = { hasDirty: () => false, setDirty: () => {} };
export function useDirtyGuard(id: string, isDirty: boolean, subject?: string): void {
  const { setDirty } = useDraftGuard();
  useEffect(() => { setDirty(id, isDirty, subject); }, [id, isDirty, subject, setDirty]);
  useEffect(() => () => setDirty(id, false), [id, setDirty]);
}
