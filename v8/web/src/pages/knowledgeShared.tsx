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
export const STATUS_WORD: Record<DocStatus, string> = { active: "Active", proposed: "Proposed", retired: "Retired" };

export function StatusWord({ status }: { status: DocStatus }): React.JSX.Element {
  const cls = status === "proposed" ? styles.statusProposed : status === "retired" ? styles.statusRetired : "";
  return <span className={`${styles.status} ${cls}`} data-testid="knowledge-status">{STATUS_WORD[status]}</span>;
}
