import { useEffect, useRef, type RefObject } from "react";

// The modal contract the page dialogs share (strategy_ll a11y bar: Esc closes and restores focus to the
// opener, focus is trapped, the background is inert): the New epic and Quick task dialogs both open
// over the page with it. `busy` holds Esc while a submit is in flight so a half-done create is never
// abandoned by a stray key.
export function useModalDialog(
  open: boolean,
  panelRef: RefObject<HTMLElement | null>,
  initialFocus: RefObject<HTMLElement | null>,
  busy: RefObject<boolean>,
  onClose: () => void,
): void {
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    const siblings = Array.from(document.body.children).filter((el): el is HTMLElement => el instanceof HTMLElement && !el.contains(panelRef.current));
    const previousInert = siblings.map((el) => el.inert);
    siblings.forEach((el) => { el.inert = true; });
    document.body.style.overflow = "hidden";
    initialFocus.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); if (!busy.current) closeRef.current(); }
      if (e.key !== "Tab") return;
      const items = Array.from(panelRef.current?.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled])') ?? []);
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      siblings.forEach((el, i) => { el.inert = previousInert[i]; });
      document.body.style.overflow = previousOverflow;
      opener?.focus();
    };
  }, [open, panelRef, initialFocus, busy]);
}
