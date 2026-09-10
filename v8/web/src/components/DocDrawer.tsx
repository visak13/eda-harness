import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { identity } from "../auth/identity";
import { Drawer } from "./Drawer";
import { DocView } from "./DocView";
import styles from "./DocDrawer.module.css";

// §17 "related docs open in place": any doc reference on the ticket/epic/Decisions pages opens
// in the §6 Drawer without the page navigating or losing scroll/draft/composer state. The
// `?doc=<id>` search param drives it, so a refresh or a shared link reopens the drawer; nested
// doc links inside a doc push onto a back-stack capped at depth 3 (deeper → open as page); a
// ticket link closes the drawer and navigates. "Open as page" goes to the kept /doc/:id route.
const MAX_DEPTH = 3;

interface DocDrawerApi {
  openDoc: (id: string) => void;
}
const Ctx = createContext<DocDrawerApi | null>(null);

/** Open a referenced doc in the shared drawer. Throws if used outside <DocDrawerProvider>. */
export function useDocDrawer(): DocDrawerApi {
  const c = useContext(Ctx);
  if (!c) throw new Error("useDocDrawer must be used within DocDrawerProvider");
  return c;
}

export function DocDrawerProvider({ children }: { children: React.ReactNode }): React.JSX.Element {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const [stack, setStack] = useState<string[]>([]);
  const [topVersion, setTopVersion] = useState<number | null>(null); // what the reader shows (finding #2)
  const returnFocus = useRef<HTMLElement | null>(null);

  const urlDoc = params.get("doc");

  // Keep the stack in sync with the URL: a deep link or a browser back that changes ?doc resets
  // the stack to that doc (unless it already matches the top — our own writes).
  useEffect(() => {
    setStack((s) => {
      const top = s[s.length - 1] ?? null;
      if (urlDoc === top) return s;
      return urlDoc ? [urlDoc] : [];
    });
  }, [urlDoc]);

  const setTop = useCallback(
    (next: string[]) => {
      setStack(next);
      const top = next[next.length - 1];
      const p = new URLSearchParams(params);
      if (top) p.set("doc", top);
      else p.delete("doc");
      setParams(p, { replace: true });
    },
    [params, setParams],
  );

  const openDoc = useCallback(
    (id: string) => {
      returnFocus.current = (document.activeElement as HTMLElement) ?? null;
      setStack((s) => {
        if (s.length >= MAX_DEPTH) {
          navigate(`/doc/${encodeURIComponent(id)}`);
          return s;
        }
        const next = [...s, id];
        const p = new URLSearchParams(params);
        p.set("doc", id);
        setParams(p, { replace: true });
        return next;
      });
    },
    [navigate, params, setParams],
  );

  const openTicket = useCallback(
    (id: string) => {
      setTop([]);
      navigate(`/ticket/${encodeURIComponent(id)}`);
    },
    [navigate, setTop],
  );

  const back = useCallback(() => setTop(stack.slice(0, -1)), [setTop, stack]);
  const close = useCallback(() => setTop([]), [setTop]);

  const api = useMemo(() => ({ openDoc }), [openDoc]);
  const top = stack[stack.length - 1] ?? null;

  const title = (
    <div className={styles.title}>
      {stack.length > 1 ? (
        <button type="button" className={styles.back} aria-label="Back" onClick={back}>
          ‹
        </button>
      ) : null}
      <span>Document</span>
      {top ? <span className={styles.id}>{top}</span> : null}
      {top ? (
        <Link
          className={styles.asPage}
          to={`/doc/${encodeURIComponent(top)}?${topVersion != null ? `version=${topVersion}&` : ""}as=${encodeURIComponent(identity())}`}
        >
          Open as page
        </Link>
      ) : null}
    </div>
  );

  return (
    <Ctx.Provider value={api}>
      {children}
      <Drawer
        open={top !== null}
        onClose={close}
        title={title}
        returnFocusTo={returnFocus.current}
      >
        {top ? <DocView docId={top} onOpenDoc={openDoc} onOpenTicket={openTicket} onVersion={setTopVersion} /> : null}
      </Drawer>
    </Ctx.Provider>
  );
}
