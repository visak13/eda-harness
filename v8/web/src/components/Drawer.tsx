import { useEffect, useRef } from "react";
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
  width = 1112,
  children,
  returnFocusTo,
}: {
  open: boolean;
  onClose: () => void;
  title: React.ReactNode;
  width?: number;
  children: React.ReactNode;
  returnFocusTo?: HTMLElement | null;
}): React.JSX.Element | null {
  const panelRef = useRef<HTMLDivElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);

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
      const target = returnFocusTo ?? openerRef.current;
      // Restore focus after the drawer unmounts (design §6: Esc restores focus).
      target?.focus?.();
    };
  }, [open, returnFocusTo]);

  // Lock body scroll while open (the page beneath keeps its scroll position — §17).
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  // Esc closes; Tab / Shift+Tab is trapped within the panel.
  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      e.stopPropagation();
      onClose();
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

  return (
    <div className={styles.scrim} onMouseDown={onClose} data-testid="drawer-scrim">
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions */}
      <div
        ref={panelRef}
        className={styles.panel}
        style={{ width }}
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === "string" ? title : "Drawer"}
        tabIndex={-1}
        data-testid="drawer-panel"
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={onKeyDown}
      >
        <header className={styles.header}>
          <div className={styles.title}>{title}</div>
          <button type="button" className={styles.close} aria-label="Close" onClick={onClose}>
            <Icon name="close" />
          </button>
        </header>
        <div className={styles.body}>{children}</div>
      </div>
    </div>
  );
}
