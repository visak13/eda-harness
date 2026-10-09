import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router";
import { Icon } from "../components/Icon";
import { isDesktopShell, isExternalHref, openExternal } from "./shell";
import styles from "./DesktopChrome.module.css";

// The desktop window has no browser chrome: WebView2 runs with its accelerator keys off (so no native Alt+Left /
// Alt+Right) and shows no Back/Forward. A browser tab keeps its own, so none of this renders or listens there
// (a second Alt+Left handler would go back twice).

interface NavigationApi { canGoBack?: boolean; canGoForward?: boolean }

function canGo(direction: -1 | 1): boolean {
  const nav = (window as unknown as { navigation?: NavigationApi }).navigation;
  if (!nav) return true; // no Navigation API: offer both, a no-op step is harmless
  return (direction < 0 ? nav.canGoBack : nav.canGoForward) !== false;
}

/** Alt+Left / Alt+Right step through the app's history, and external links go to the system browser (the shell's
 *  navigation guard is the backstop). Desktop shell only. */
export function useDesktopShortcuts(): void {
  const navigate = useNavigate();
  useEffect(() => {
    if (!isDesktopShell()) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || !e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      e.preventDefault();
      navigate(e.key === "ArrowLeft" ? -1 : 1);
    };
    const onClick = (e: MouseEvent) => {
      if (e.defaultPrevented || e.button !== 0 || !(e.target instanceof Element)) return;
      const a = e.target.closest("a[href]");
      const href = a?.getAttribute("href") ?? "";
      if (!a || !isExternalHref(href)) return;
      e.preventDefault();
      const absolute = new URL(href, window.location.href).href;
      void openExternal(absolute).then((ok) => { if (!ok) window.open(absolute, "_blank", "noopener"); });
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("click", onClick);
    return () => { document.removeEventListener("keydown", onKey); document.removeEventListener("click", onClick); };
  }, [navigate]);
}

/** Back / Forward in the rail's brand row, desktop shell only. Disabled at the ends of the history. */
export function HistoryButtons(): React.JSX.Element | null {
  const navigate = useNavigate();
  const location = useLocation();
  const [, setTick] = useState(0);
  useEffect(() => {
    const again = () => setTick((n) => n + 1);
    window.addEventListener("popstate", again);
    return () => window.removeEventListener("popstate", again);
  }, []);
  if (!isDesktopShell()) return null;
  // read on every render: a route change (location) is what moves the history position
  const back = canGo(-1);
  const forward = canGo(1);
  return (
    <div className={styles.history} role="group" aria-label="History" data-testid="history" data-at={location.key}>
      <button type="button" className={styles.step} aria-label="Go back" title="Back (Alt+Left)" disabled={!back}
        data-testid="history-back" onClick={() => navigate(-1)}><Icon name="back" size={18} /></button>
      <button type="button" className={styles.step} aria-label="Go forward" title="Forward (Alt+Right)" disabled={!forward}
        data-testid="history-forward" onClick={() => navigate(1)}><Icon name="forward" size={18} /></button>
    </div>
  );
}
