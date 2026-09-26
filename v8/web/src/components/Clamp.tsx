import { useLayoutEffect, useRef, useState } from "react";
import { Markdown } from "./Markdown";
import styles from "./Clamp.module.css";

// Long board text (a ticket description, a steer) is clamped to a few lines with a "Show all"
// toggle instead of a wall of text pushing the page's structure below the fold (human report
// "spacing broken", 2026-09-10). Nothing is hidden for good: one click shows every word.
// t-994970028d: with `html` (a board-rendered markdown body) the content renders through
// <Markdown> and is clamped by HEIGHT (lines × line-height) — line-clamp does not count lines
// across the paragraphs and lists of rendered markdown.
export function Clamp({
  text,
  html,
  lines = 4,
  className,
  testId,
}: {
  text: string;
  html?: string | null;
  lines?: number;
  className?: string;
  testId?: string;
}): React.JSX.Element {
  const [open, setOpen] = useState(false);
  const [overflows, setOverflows] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const rich = !!html;
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setOverflows(el.scrollHeight > el.clientHeight + 1);
  }, [text, html, lines]);
  const clampStyle = rich
    ? ({ maxHeight: `calc(${lines} * 1lh)` } as React.CSSProperties)
    : ({ WebkitLineClamp: lines } as React.CSSProperties);
  return (
    <div className={className} data-testid={testId}>
      <div
        ref={ref}
        className={open ? undefined : rich ? styles.clampedHeight : styles.clamped}
        style={open ? undefined : clampStyle}
      >
        {rich ? <Markdown html={html} className={styles.rich} /> : text}
      </div>
      {overflows || open ? (
        <button type="button" className={styles.toggle} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          {open ? "Show less" : "Show all"}
        </button>
      ) : null}
    </div>
  );
}
