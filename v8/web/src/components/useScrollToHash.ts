import { useEffect } from "react";
import { useLocation } from "react-router";

/** Scroll the element named by the URL hash into view once the page has its rows (a Find hit on a
 *  message or criterion lands on that row, human defect #12). `ready` re-runs it when rows arrive. */
export function useScrollToHash(ready: number | boolean): void {
  const { hash } = useLocation();
  useEffect(() => {
    if (!hash) return;
    const el = document.getElementById(hash.slice(1));
    if (el) {
      el.scrollIntoView({ block: "center" });
      el.setAttribute("data-found", "true");
    }
  }, [hash, ready]);
}
