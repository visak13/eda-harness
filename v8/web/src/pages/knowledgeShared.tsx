import type { DocStatus } from "../api/types";
import styles from "./Knowledge.module.css";

// Shared by the Library knowledge list and its detail pane: kind labels and the status word
// (every state carries a word, never colour alone).
/** The doc kinds the Library knowledge section lists (schemas.KNOWLEDGE_DOC_TYPES). */
export const KNOWLEDGE_KINDS = ["strategy_hl", "strategy_ll", "domain"] as const;

export const KIND_LABEL: Record<string, string> = {
  strategy_hl: "strategy · high level",
  strategy_ll: "strategy · low level",
  domain: "domain",
  lesson: "lesson",
};
/** S12-ui2 (qa m-da89ef8294 item 6): a title written as "strategy_hl: walking-skeleton" shows as "walking-skeleton";
 *  the kind is the chip beside it, never part of the title. */
export function docTitle(title: string): string {
  const bare = title.replace(/^\s*(strategy_hl|strategy_ll|domain|lesson)\s*:\s*/i, "");
  return bare || title;
}
export const STATUS_WORD: Record<DocStatus, string> = { active: "Active", proposed: "Proposed", retired: "Retired" };

export function StatusWord({ status }: { status: DocStatus }): React.JSX.Element {
  const cls = status === "proposed" ? styles.statusProposed : status === "retired" ? styles.statusRetired : "";
  return <span className={`${styles.status} ${cls}`} data-testid="knowledge-status">{STATUS_WORD[status]}</span>;
}

/** S17 decision 1: every doc write points to the doc-write skill's shape (the board never rejects a layout). */
export const DOC_WRITE_HINT =
  "Write it summary-first (the /doc-write skill): Purpose, the key slot (Rules for a strategy or domain), Keywords, Outline, then Topics. Seats read the first page and the heading map; the rest on demand.";
