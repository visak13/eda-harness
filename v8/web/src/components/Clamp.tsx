import { useLayoutEffect, useRef, useState } from "react";
import styles from "./Clamp.module.css";

// Long board text (a ticket description, a steer) is clamped to a few lines with a "Show all"
// toggle instead of a wall of text pushing the page's structure below the fold (human report
// "spacing broken", 2026-09-10). Nothing is hidden for good: one click shows every word.
export function Clamp({
  text,
  lines = 4,
  className,
  testId,
}: {
  text: string;
  lines?: number;
  className?: string;
  testId?: string;
}): React.JSX.Element {
  const [open, setOpen] = useState(false);
  const [overflows, setOverflows] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setOverflows(el.scrollHeight > el.clientHeight + 1);
  }, [text, lines]);
  return (
    <div className={className} data-testid={testId}>
      <div
        ref={ref}
        className={open ? undefined : styles.clamped}
        style={open ? undefined : ({ WebkitLineClamp: lines } as React.CSSProperties)}
      >
        {text}
      </div>
      {overflows || open ? (
        <button type="button" className={styles.toggle} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          {open ? "Show less" : "Show all"}
        </button>
      ) : null}
    </div>
  );
}
