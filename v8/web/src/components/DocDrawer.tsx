import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";
import type { DocHtml } from "../api/types";
import { identity } from "../auth/identity";
import { Drawer } from "./Drawer";
import { DocView } from "./DocView";
import styles from "./DocDrawer.module.css";
import { Icon } from "./Icon";
import { pendingWork } from "./PendingNavigation";

// §17 "related docs open in place": any doc reference on the ticket/epic/Decisions pages opens
// in the §6 Drawer without the page navigating or losing scroll/draft/composer state. The
// `?doc=<id>` search param drives it, so a refresh or a shared link reopens the drawer; nested
// doc links inside a doc push onto a back-stack capped at depth 3 (deeper → open as page); a
// ticket link closes the drawer and navigates. "Open as page" goes to the kept /doc/:id route.
//
// The Drawer header is the reader's 72px toolbar (Astra ruling #36 item 2): doc type · "Open as
// page" · ONE version menu ("vN · Latest ▾", a <details> labelled "Versions") · the Drawer's close.
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
  const location = useLocation();
  const source = /^\/(?:epic|ticket|records)\/([^/]+)/.exec(location.pathname)?.[1] ?? params.get("source");
  const [stack, setStack] = useState<string[]>([]);
  const [topDoc, setTopDoc] = useState<DocHtml | null>(null); // what the reader shows (toolbar menu)
  // A version picked from the toolbar, keyed by doc so a stale pick never leaks onto the next doc.
  const [picked, setPicked] = useState<{ id: string; v: number } | null>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const menuRef = useRef<HTMLDetailsElement>(null);

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
      if (pendingWork()) return;
      setStack(next);
      const top = next[next.length - 1];
      const p = new URLSearchParams(params);
      if (top) p.set("doc", top);
      else p.delete("doc");
      p.delete("v"); // a version belongs to the doc it was picked on
      setParams(p, { replace: true });
    },
    [params, setParams],
  );

  const openDoc = useCallback(
    (id: string) => {
      if (pendingWork()) return;
      returnFocus.current = (document.activeElement as HTMLElement) ?? null;
      setStack((s) => {
        if (s.length >= MAX_DEPTH) {
          navigate(`/doc/${encodeURIComponent(id)}`);
          return s;
        }
        const next = [...s, id];
        const p = new URLSearchParams(params);
        p.set("doc", id);
        p.delete("v");
        p.delete("view");
        p.delete("compose");
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
    [setTop, navigate],
  );

  const back = useCallback(() => setTop(stack.slice(0, -1)), [setTop, stack]);
  const close = useCallback(() => setTop([]), [setTop]);

  const api = useMemo(() => ({ openDoc }), [openDoc]);
  const top = stack[stack.length - 1] ?? null;
  // The reader reports what it shows; mirroring it into `picked` keeps the toolbar's prop in step
  // with a switch made from the History block, so re-picking the toolbar entry always applies.
  const onVersion = useCallback(
    (v: number) => {
      if (top) setPicked({ id: top, v });
    },
    [top],
  );
  // S22 (consult #6): a chosen version is written to the address as ?v=N (replace — no history
  // entry per click), so reload, copy-link and Open in tab reopen it; no ?v= means latest.
  const pickVersion = useCallback(
    (v: number) => {
      if (!top) return;
      setPicked({ id: top, v });
      const p = new URLSearchParams(params);
      p.set("v", String(v));
      setParams(p, { replace: true });
    },
    [top, params, setParams],
  );
  const shownDoc = topDoc && topDoc.id === top ? topDoc : null;
  const latest = shownDoc ? (shownDoc.versions.length ? Math.max(...shownDoc.versions) : shownDoc.version) : null;
  const pickedVersion = picked && picked.id === top ? picked.v : undefined;

  const tabHref = top ? `/doc/${encodeURIComponent(top)}?${new URLSearchParams({ ...(shownDoc ? { version: String(shownDoc.version) } : {}), ...(source ? { source } : {}), ...(params.get("request") ? { request: params.get("request")! } : {}), as: identity() })}` : undefined;
  // S19 (revision3-clean-review.png): a doc opened from a conversation is a design review — a centred
  // viewer with ONE header drawn by DesignReview (crumb · Open in tab · Close · version menu), not this
  // toolbar stacked above a second review header.
  // Only once the document has loaded: while it is loading or failed, DocView draws no review
  // header, so the toolbar (with its Close) must stay (S19 qa, adversary #4).
  // qa finding 27 (final sweep): a doc that carries the viewer's sign-off criteria is NOT reviewed by
  // DesignReview (DocView keeps the classic reader + SignoffPane, latched like DocView.signoffDoc), so
  // this toolbar must stay or the dialog has no Close and no Open in tab (r1-captures :115).
  const signoffSeen = useRef<string | null>(null);
  if (shownDoc && ((shownDoc.signoff_criteria?.length ?? 0) > 0 || Boolean(shownDoc.signoff_criterion))) signoffSeen.current = shownDoc.id;
  const review = Boolean(source) && shownDoc !== null && signoffSeen.current !== shownDoc.id;
  const title = (
    <div className={styles.toolbar}>
      {stack.length > 1 ? (
        <button type="button" className={styles.back} aria-label="Back" onClick={back}>
          ‹
        </button>
      ) : null}
      <span className={styles.kind}>{shownDoc ? shownDoc.doc_type.replace(/_/g, " ") : "Document"}</span>
      {top ? (
        <Link
          className={styles.asPage}
          target="_blank"
          to={tabHref!}
        >
          Open in tab
        </Link>
      ) : null}
      {shownDoc && top ? (
        <details ref={menuRef} className={styles.versionsMenu} aria-label="Versions" data-testid="doc-versions-menu">
          <summary className={styles.versionsSummary}>
            v{shownDoc.version} · {shownDoc.version === latest ? "Latest" : "Pinned"} <Icon name="chevron" />
          </summary>
          <div className={styles.versionsList}>
            {shownDoc.versions.map((v) => (
              <button
                key={v}
                type="button"
                className={`${styles.versionEntry} ${v === shownDoc.version ? styles.versionActive : ""}`}
                aria-pressed={v === shownDoc.version}
                data-testid="version-entry"
                onClick={() => {
                  if (pendingWork()) return;
                  pickVersion(v);
                  if (menuRef.current) menuRef.current.open = false;
                }}
              >
                v{v}
                {v === latest ? " · latest" : ""}
              </button>
            ))}
          </div>
        </details>
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
        label={shownDoc ? shownDoc.doc_type.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()) : "Document"}
        returnFocusTo={returnFocus.current}
        bare={review}
        centered={review}
      >
        {top ? (
          <DocView
            key={top}
            docId={top}
            version={pickedVersion ?? (params.get("v") ? Number(params.get("v")) : undefined)}
            source={source}
            request={params.get("request")}
            onOpenDoc={openDoc}
            onOpenTicket={openTicket}
            onVersion={onVersion}
            onPick={pickVersion}
            onDoc={setTopDoc}
            tabHref={tabHref}
            onBack={stack.length > 1 ? back : undefined}
            versionsHosted
          />
        ) : null}
      </Drawer>
    </Ctx.Provider>
  );
}
