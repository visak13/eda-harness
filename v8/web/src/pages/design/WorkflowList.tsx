import type { WorkflowRow } from "../../api/workflows";
import ui from "../../components/ui.module.css";
import styles from "./Design.module.css";

// S14 (§4.14(c)): every workflow version — presets first, then custom — with its state, the version it came
// from and the epics that pin it. A preset or a published version is immutable: Duplicate to edit.

export function WorkflowList({ rows, selected, canEdit, onSelect, onDuplicate, pending }: {
  rows: WorkflowRow[]; selected: string | null; canEdit: boolean;
  onSelect: (ref: string) => void; onDuplicate: (ref: string) => void; pending: boolean;
}): React.JSX.Element {
  const presets = rows.filter((r) => r.builtin);
  const custom = rows.filter((r) => !r.builtin);
  const group = (title: string, list: WorkflowRow[], testid: string) => (
    <>
      <h2 className={styles.group}>{title}</h2>
      {list.length === 0 ? <p className={styles.muted} data-testid={`${testid}-empty`}>None yet. Duplicate a preset to make one.</p> : null}
      <ul className={styles.list} data-testid={testid}>
        {list.map((r) => (
          <li key={r.ref}>
            <div role="button" tabIndex={0} aria-pressed={selected === r.ref}
              className={`${styles.item} ${selected === r.ref ? styles.itemActive : ""}`} data-testid={`wf-row-${r.ref}`}
              onClick={() => onSelect(r.ref)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(r.ref); } }}>
              <span className={styles.itemHead}>
                {r.name || r.id} <span className={styles.mono}>{r.ref}</span>
                {r.builtin ? <span className={styles.badge}>preset</span> : null}
                <span className={`${styles.badge} ${r.published ? styles.badgePub : styles.badgeDraft}`}>{r.published ? "published" : "draft"}</span>
              </span>
              <span className={styles.itemMeta}>
                {r.roles} roles{r.source ? ` · from ${r.source}` : ""}
              </span>
              <span className={styles.itemMeta} data-testid={`wf-pins-${r.ref}`}>
                {r.pinned_by.length ? `pinned by ${r.pinned_by.length} epic${r.pinned_by.length === 1 ? "" : "s"}: ${r.pinned_by.slice(0, 4).join(", ")}${r.pinned_by.length > 4 ? "…" : ""}` : "no epic pins it"}
              </span>
              {canEdit ? (
                <span>
                  <button type="button" className={`${ui.button} ${styles.small}`} disabled={pending} data-testid={`wf-duplicate-${r.ref}`}
                    onClick={(e) => { e.stopPropagation(); onDuplicate(r.ref); }}>Duplicate to edit</button>
                </span>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
    </>
  );
  return (
    <nav aria-label="Workflows" data-testid="design-list">
      {group("Presets", presets, "wf-presets")}
      {group("Custom", custom, "wf-custom")}
    </nav>
  );
}
