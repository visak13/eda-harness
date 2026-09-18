import { useContext, useEffect } from "react";
import { UNSAFE_DataRouterContext, useBlocker } from "react-router";
/** Pending operations own their mounted draft. A URL/version switch must not orphan them. */
export function pendingWork(): boolean { return Boolean(document.querySelector('[data-busy="true"]')); }
function DataNavigationGuard(): React.JSX.Element | null {
  const blocker = useBlocker(() => pendingWork());
  useEffect(() => {
    if (blocker.state !== "blocked") return;
    // Stay on the source, not a surprise delayed navigation when a send finishes.
    const timer = window.setInterval(() => { if (!pendingWork()) blocker.reset(); }, 250);
    return () => window.clearInterval(timer);
  }, [blocker]);
  return blocker.state === "blocked" ? <p role="status">Wait for the pending upload or send before navigating. <button onClick={() => blocker.reset()}>Stay here</button></p> : null;
}
export function PendingNavigation(): React.JSX.Element | null {
  const router = useContext(UNSAFE_DataRouterContext);
  return router ? <DataNavigationGuard /> : null;
}
