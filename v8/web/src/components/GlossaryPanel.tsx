import { useEffect, useRef } from "react";
import { GLOSSARY, type GlossaryCategory } from "../copy/glossary";
import type { TermRef } from "./PageFrame";
import styles from "./GlossaryPanel.module.css";

// "What am I looking at?" (design §15, criterion c-cccc3183db). A panel that explains, in plain
// words, the terms visible on the CURRENT page: the page's framing sentence, then each glossary
// term the page declared, grouped by category. Opened by the header ? button or Ctrl-/, closed by
// Esc or its close button; the opener restores focus (AppShell owns that). When a page declares no
// terms the panel falls back to the full glossary so the reader is never left without help.

const HEADINGS: Record<GlossaryCategory, string> = {
  ticket_status: "Ticket stages",
  message_kind: "Message kinds",
  gate: "Gate kinds",
  role: "Roles",
  check: "Check kinds",
  ticket_kind: "Ticket kinds",
  work_type: "Work types",
  verdict: "Verdicts",
  concept: "Words",
};
// Column/plate order (folio-glossary): stages, gates, checks on the left; message kinds, roles right.
const ORDER: GlossaryCategory[] = [
  "ticket_status", "gate", "check", "ticket_kind", "work_type",
  "message_kind", "role", "verdict",
];

function groups(terms: TermRef[]): Array<[GlossaryCategory, string[]]> {
  // No page-declared terms → show every category in full.
  if (terms.length === 0) {
    return ORDER.map((c) => [c, Object.keys(GLOSSARY[c])] as [GlossaryCategory, string[]]);
  }
  const byCat = new Map<GlossaryCategory, string[]>();
  for (const { category, value } of terms) {
    if (category === "concept") continue; // concept words live in the footer
    const list = byCat.get(category) ?? [];
    if (!list.includes(value)) list.push(value);
    byCat.set(category, list);
  }
  return ORDER.filter((c) => byCat.has(c)).map((c) => [c, byCat.get(c)!]);
}

export function GlossaryPanel({
  open,
  onClose,
  framing,
  terms,
}: {
  open: boolean;
  onClose: () => void;
  framing: string;
  terms: TermRef[];
}): React.JSX.Element | null {
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  const cols = groups(terms);
  const conceptValues = terms.length === 0 ? Object.keys(GLOSSARY.concept)
    : terms.filter((t) => t.category === "concept").map((t) => t.value);

  return (
    <>
      <div className={styles.scrim} onClick={onClose} data-testid="glossary-scrim" aria-hidden="true" />
      <div
        className={styles.panel}
        role="dialog"
        aria-modal="true"
        aria-label="What am I looking at?"
        ref={dialogRef}
      >
        <div className={styles.head}>
          <h2 className={styles.title}>What am I looking at?</h2>
          <button ref={closeRef} type="button" className={styles.close} aria-label="Close" onClick={onClose}>
            ✕
          </button>
        </div>
        <p className={styles.framing}>{framing}</p>

        <div className={styles.cols}>
          {cols.map(([category, values]) => (
            <section key={category} className={styles.group}>
              <h3 className={styles.groupLabel}>{HEADINGS[category]}</h3>
              <dl className={styles.defs}>
                {values.map((value) => (
                  <div key={value} className={styles.def}>
                    <dt className={styles.dt}>{GLOSSARY[category][value].label}</dt>
                    <dd className={styles.dd}>{GLOSSARY[category][value].meaning}</dd>
                  </div>
                ))}
              </dl>
            </section>
          ))}
        </div>

        {conceptValues.length > 0 ? (
          <p className={styles.footer}>
            {conceptValues.map((v, i) => (
              <span key={v}>
                {i > 0 ? " · " : ""}
                <strong>{GLOSSARY.concept[v].label}</strong> = {GLOSSARY.concept[v].meaning}
              </span>
            ))}
          </p>
        ) : null}
      </div>
    </>
  );
}
