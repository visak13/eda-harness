import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import styles from "./Drawer.module.css";
import { Icon } from "./Icon";

// The one right-side drawer (design §6/§17): a fixed 1112px panel that hosts three bodies —
// the ruling (G2), the doc reader (DocDrawer, this story) and the expanded composer (G2). It is
// a pure shell: open/close, a title header, focus trap, Esc → onClose, focus restored to
// `returnFocusTo` (or whatever was focused when it opened), and body scroll locked while open.
// Everything domain-specific is `children`.
export function Drawer({
  open,
  onClose,
  title,
  label,
  width = 1112,
  children,
  returnFocusTo,
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
    <div className={styles.scrim} onMouseDown={requestClose} data-testid="drawer-scrim" data-drawer-width={width}>
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions */}
      <div
        ref={panelRef}
        className={styles.panel}
        style={{ width }}
        role="dialog"
        aria-modal="true"
        aria-label={label ?? (typeof title === "string" ? title : "Drawer")}
        tabIndex={-1}
        data-testid="drawer-panel"
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={onKeyDown}
      >
        <header className={styles.header}>
          <div className={styles.title}>{title}</div>
          <button type="button" className={styles.close} aria-label="Close" onClick={requestClose}>
            <Icon name="close" />
          </button>
        </header>
        <div className={styles.body}>{held ? <p role="status">Wait for the pending upload or send before closing. Your draft is kept.</p> : null}{children}</div>
      </div>
    </div>, document.body,
  );
}
