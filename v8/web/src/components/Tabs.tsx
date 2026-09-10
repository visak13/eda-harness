import styles from "./Tabs.module.css";

export interface Tab {
  key: string;
  label: string;
  count?: number;
  /** Tooltip + aria-describedby props from copyProps() (defect #31). */
  copy?: { title: string; "aria-describedby": string; "data-copy": string };
}

// Underlined tab bar (design §4.2: 3px selected underline in accentink). Roving selection via
// role=tab/tablist so the panel a page renders is driven by `active`. Keyboard: the buttons are
// natural tab stops; ← → move between them.
export function Tabs({
  tabs,
  active,
  onChange,
}: {
  tabs: Tab[];
  active: string;
  onChange: (key: string) => void;
}): React.JSX.Element {
  function onKey(e: React.KeyboardEvent, i: number) {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const next = e.key === "ArrowRight" ? (i + 1) % tabs.length : (i - 1 + tabs.length) % tabs.length;
    onChange(tabs[next].key);
  }
  return (
    <div className={styles.bar} role="tablist" aria-label="Sections">
      {tabs.map((t, i) => (
        <button
          key={t.key}
          role="tab"
          type="button"
          aria-selected={active === t.key}
          tabIndex={active === t.key ? 0 : -1}
          className={`${styles.tab} ${active === t.key ? styles.active : ""}`}
          {...(t.copy ?? {})}
          onClick={() => onChange(t.key)}
          onKeyDown={(e) => onKey(e, i)}
        >
          {t.label}
          {typeof t.count === "number" ? <span className={styles.count}> {t.count}</span> : null}
        </button>
      ))}
    </div>
  );
}
