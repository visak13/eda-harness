import { createContext, useContext, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import styles from "./Drawer.module.css";
import { Icon } from "./Icon";

// The one right-side drawer (design §6/§17): a fixed 1112px panel that hosts three bodies —
// the ruling (G2), the doc reader (DocDrawer, this story) and the expanded composer (G2). It is
// a pure shell: open/close, a title header, focus trap, Esc → onClose, focus restored to
// `returnFocusTo` (or whatever was focused when it opened), and body scroll locked while open.
// Everything domain-specific is `children`.

/** The open drawer's close (with its busy-hold check) for a body that draws its own header
 *  (`bare`, S19 design review). null outside a drawer. */
const DrawerCloseContext = createContext<(() => void) | null>(null);
export function useDrawerClose(): (() => void) | null { return useContext(DrawerCloseContext); }

export function Drawer({
  open,
  onClose,
  title,
  label,
  width = 1112,
  children,
  returnFocusTo,
  edge = false,
  bare = false,
  centered = false,
}: {
  open: boolean;
  onClose: () => void;
  title: React.ReactNode;
  /** Accessible name when the visible title is not a plain string (e.g. the doc reader's toolbar):
   *  the doc drawer is named by its kind ("Design"), not the generic "Drawer". */
  label?: string;
  width?: number;
  children: React.ReactNode;
  returnFocusTo?: HTMLElement | null;
  /** A flush side sheet (S17 c-f142c65a60, owner: "a gap where information is visible within that
   *  gap if you scroll"): no inset margins, full height, full width below 960px, so no page content
   *  shows around the panel. The inset drawer stays the default (ruling geometry c-03436484b6). */
  edge?: boolean;
  /** No header row: the body draws its own title and close (useDrawerClose). S19: the design
   *  review viewer per revision3-clean-review.png has ONE header (source crumb, Open in tab, Close). */
  bare?: boolean;
  /** A centred modal (revision3-clean-review.png: 1190 wide, 52px from the top and bottom at
   *  1440×900) instead of the right-hand panel. */
  centered?: boolean;
}): React.JSX.Element | null {
  const panelRef = useRef<HTMLDivElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);
  // Read the latest returnFocusTo at close without making it a focus-effect dependency: if it were,
  // a re-render while the drawer is open would re-run the effect and re-capture openerRef as some
  // node INSIDE the drawer, so Esc would then restore focus to a now-unmounted node (→ body). The
  // trigger is captured once, on the closed→open transition (finding 7).
  const returnRef = useRef(returnFocusTo);
  returnRef.current = returnFocusTo;
  const [held, setHeld] = useState(false);
  function requestClose() {
    if (panelRef.current?.querySelector('[data-busy="true"]')) { setHeld(true); return; }
    setHeld(false); onClose();
  }

  useEffect(() => {
    if (!held || !open || !panelRef.current) return;
    const panel = panelRef.current;
    const check = () => { if (!panel.querySelector('[data-busy="true"]')) setHeld(false); };
    const observer = new MutationObserver(check);
    observer.observe(panel, { subtree: true, attributes: true, childList: true, attributeFilter: ["data-busy"] });
    check();
    return () => observer.disconnect();
  }, [held, open]);

  // ORDER MATTERS: this effect is declared BEFORE the focus effect so its cleanup (un-inert the page)
  // runs first. With the reverse order the trigger was still inside an inert subtree when focus was
  // restored, so .focus() was a no-op and Esc landed on <body> in a real browser (qa finding 7;
  // jsdom has no inert, so vitest could not see it; Playwright covers it).
  // Lock body scroll while open (the page beneath keeps its scroll position — §17).
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    const siblings = Array.from(document.body.children).filter((el): el is HTMLElement => el instanceof HTMLElement && !el.contains(panelRef.current));
    const prior = siblings.map((el) => el.inert);
    siblings.forEach((el) => { el.inert = true; });
    document.body.style.overflow = "hidden";
    return () => {
      siblings.forEach((el, i) => { el.inert = prior[i]; });
      document.body.style.overflow = prev;
    };
  }, [open]);

  // Remember what to restore focus to (the element focused at open time), and move focus in.
  useEffect(() => {
    if (!open) return;
    openerRef.current = (document.activeElement as HTMLElement) ?? null;
    const panel = panelRef.current;
    // Focus the first focusable inside, else the panel itself (tabIndex -1).
    const first = panel?.querySelector<HTMLElement>(
      'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])',
    );
    (first ?? panel)?.focus();
    return () => {
      const target = returnRef.current ?? openerRef.current;
      // Restore focus after the drawer unmounts (design §6: Esc restores focus to the trigger).
      target?.focus?.();
    };
  }, [open]);

  // The header can leave while open (`bare` flips once a review document loads, S19 qa): if the
  // focused control unmounted with it, focus fell to <body> and Esc stopped reaching the panel —
  // bring it back to the first focusable, else the panel.
  useEffect(() => {
    if (!open) return;
    const panel = panelRef.current;
    if (!panel || panel.contains(document.activeElement)) return;
    const first = panel.querySelector<HTMLElement>(
      'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])',
    );
    (first ?? panel).focus();
  }, [open, bare]);

  // Esc closes; Tab / Shift+Tab is trapped within the panel.
  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      e.stopPropagation();
      requestClose();
      return;
    }
    if (e.key !== "Tab") return;
    const panel = panelRef.current;
    if (!panel) return;
    const focusables = Array.from(
      panel.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), textarea, input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ),
    ).filter((el) => el.offsetParent !== null || el === document.activeElement);
    if (focusables.length === 0) {
      e.preventDefault();
      panel.focus();
      return;
    }
    const firstEl = focusables[0];
    const lastEl = focusables[focusables.length - 1];
    const active = document.activeElement as HTMLElement;
    if (e.shiftKey && (active === firstEl || active === panel)) {
      e.preventDefault();
      lastEl.focus();
    } else if (!e.shiftKey && active === lastEl) {
      e.preventDefault();
      firstEl.focus();
    }
  }

  if (!open) return null;

  return createPortal(
    <div className={centered ? `${styles.scrim} ${styles.centeredScrim}` : styles.scrim} onMouseDown={requestClose} data-testid="drawer-scrim" data-drawer-width={width}>
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions */}
      <div
        ref={panelRef}
        className={[styles.panel, edge ? styles.edge : "", centered ? styles.centered : "", bare ? styles.bare : ""].filter(Boolean).join(" ")}
        style={{ width }}
        role="dialog"
        aria-modal="true"
        aria-label={label ?? (typeof title === "string" ? title : "Drawer")}
        tabIndex={-1}
        data-testid="drawer-panel"
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={onKeyDown}
      >
        {bare ? null : <header className={styles.header}>
          <div className={styles.title}>{title}</div>
          <button type="button" className={styles.close} aria-label="Close" onClick={requestClose}>
            <Icon name="close" />
          </button>
        </header>}
        <DrawerCloseContext.Provider value={requestClose}>
          <div className={styles.body}>{held ? <p role="status" className={styles.held}>Wait for the pending upload or send before closing. Your draft is kept.</p> : null}{children}</div>
        </DrawerCloseContext.Provider>
      </div>
    </div>, document.body,
  );
}
