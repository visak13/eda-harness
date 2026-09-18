import { useLayoutEffect, useRef, useState, type RefObject } from "react";
import { createPortal } from "react-dom";
import styles from "./AnchoredPanel.module.css";

/** Shared nonmodal preferences/Usage foundation. Mount only while open. */
export function AnchoredPanel({ anchor, label, onClose, children, width = 320, maxHeight = Infinity }: {
  anchor: RefObject<HTMLElement | null>; label: string;
  onClose: () => void; children: React.ReactNode; width?: number; maxHeight?: number;
}): React.JSX.Element {
  const panel = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ left: 12, top: 12 });
  useLayoutEffect(() => {
    const el = panel.current;
    if (!el) return;
    const place = () => {
      const rect = anchor.current?.getBoundingClientRect();
      if (!rect) return;
      const view = window.visualViewport;
      const x = view?.offsetLeft ?? 0, y = view?.offsetTop ?? 0;
      const vw = view?.width ?? innerWidth, vh = view?.height ?? innerHeight;
      el.style.maxHeight = `${Math.max(0, Math.min(maxHeight, vh - 24))}px`;
      el.style.width = `${Math.max(0, Math.min(width, vw - 24))}px`;
      const h = el.getBoundingClientRect().height;
      setPosition({
        left: Math.max(x + 12, Math.min(rect.left, x + vw - el.offsetWidth - 12)),
        top: Math.max(y + 12, Math.min(rect.top - h - 8, y + vh - h - 12)),
      });
    };
    place();
    const observer = new ResizeObserver(place);
    observer.observe(el);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    window.visualViewport?.addEventListener("resize", place);
    window.visualViewport?.addEventListener("scroll", place);
    (el.querySelector<HTMLElement>('[role="radio"][aria-checked="true"], button, input') ?? el).focus();
    const outside = (e: Event) => {
      if (e.target instanceof Node && !el.contains(e.target) && !anchor.current?.contains(e.target)) onClose();
    };
    const key = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault(); e.stopPropagation(); onClose(); anchor.current?.focus();
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("focusin", outside);
    el.addEventListener("keydown", key);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
      window.visualViewport?.removeEventListener("resize", place);
      window.visualViewport?.removeEventListener("scroll", place);
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("focusin", outside);
      el.removeEventListener("keydown", key);
    };
  }, [anchor, onClose, width, maxHeight]);
  return createPortal(<div ref={panel} role="dialog" aria-label={label} tabIndex={-1}
    className={styles.panel} style={position}>
    <div className={styles.heading}><strong>{label}</strong><button type="button" onClick={() => {
      onClose(); anchor.current?.focus();
    }} aria-label={`Close ${label}`}>Close</button></div>
    {children}
  </div>, document.body);
}
