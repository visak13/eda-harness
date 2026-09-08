import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { subscribeFeed } from "./feed";

// SEAM (live plane, draft guard). One feed subscription for the whole app. A feed event
// normally invalidates every server-state query so the lists refresh; but invalidating a list
// UNDER a half-typed reply would wipe the draft and reorder the row the user is answering. So
// while ANY composer is dirty we DEFER: we count the held events and surface "N new — refresh"
// (parity with the legacy live pill), and only flush — invalidate + reset — when the user asks
// or the last dirty composer clears. This is strategy_ll's `useDraftGuard` bar (design §4.2:
// "with a dirty composer show 'N new — refresh' instead of reordering").

interface DraftGuardValue {
  /** Held feed events while a composer was dirty — the "N new" count; 0 when nothing is pending. */
  pending: number;
  /** Invalidate all server-state queries now and reset the pending count (the "refresh" click). */
  flush: () => void;
  /** Register/unregister this composer's dirty state by a stable id. */
  setDirty: (id: string, dirty: boolean) => void;
}

const DraftGuardContext = createContext<DraftGuardValue | null>(null);

export function DraftGuardProvider({ children }: { children: React.ReactNode }): React.JSX.Element {
  const qc = useQueryClient();
  const [pending, setPending] = useState(0);
  // A ref, not state: the feed callback closes over it and must read the LIVE dirty set without
  // being re-created (re-creating the callback would tear down and rebuild the subscription).
  const dirty = useRef<Set<string>>(new Set());

  const flush = useCallback(() => {
    setPending(0);
    void qc.invalidateQueries();
  }, [qc]);

  const setDirty = useCallback(
    (id: string, isDirty: boolean) => {
      if (isDirty) {
        dirty.current.add(id);
        return;
      }
      dirty.current.delete(id);
      // When the last dirty composer clears, deliver whatever was held so the user is never left
      // looking at stale rows with no way to know (they cleared the draft, so nothing is at risk).
      if (dirty.current.size === 0) {
        setPending((n) => {
          if (n > 0) void qc.invalidateQueries();
          return 0;
        });
      }
    },
    [qc],
  );

  useEffect(() => {
    const stop = subscribeFeed(
      () => {
        if (dirty.current.size > 0) {
          setPending((n) => n + 1); // hold — a dirty composer is open; show "N new — refresh"
        } else {
          void qc.invalidateQueries(); // safe to refresh; nothing is being typed
        }
      },
      { onError: () => void 0 },
    );
    return stop;
  }, [qc]);

  const value = useMemo<DraftGuardValue>(() => ({ pending, flush, setDirty }), [pending, flush, setDirty]);
  return <DraftGuardContext.Provider value={value}>{children}</DraftGuardContext.Provider>;
}

/** Read the guard (pending count + flush). Safe outside a provider: returns a no-op guard so a
 *  component (or a test) can render without one — pending stays 0 and flush does nothing. */
export function useDraftGuard(): DraftGuardValue {
  return useContext(DraftGuardContext) ?? NOOP;
}

const NOOP: DraftGuardValue = { pending: 0, flush: () => {}, setDirty: () => {} };

/** A composer calls this with its dirty flag; the guard holds feed refreshes while it is true.
 *  Unmounting clears the flag so a closed composer never keeps the list frozen. */
export function useDirtyGuard(id: string, isDirty: boolean): void {
  const { setDirty } = useDraftGuard();
  useEffect(() => {
    setDirty(id, isDirty);
  }, [id, isDirty, setDirty]);
  useEffect(() => () => setDirty(id, false), [id, setDirty]);
}
