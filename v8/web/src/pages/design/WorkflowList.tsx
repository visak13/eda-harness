import type { WorkflowRow } from "../../api/workflows";
import ui from "../../components/ui.module.css";
import styles from "./Design.module.css";

// S14 (§4.14(c)) + t-0c16c00424: every workflow version — presets first, then your own — each with its name, a
// one-line summary, its status (draft / published / in use by N epics) and a preset badge. An admin gets
// Duplicate and Delete (what Delete does is the board's `delete_outcome`); archived versions show on request.

/** The status a person reads: a draft, published and unused, or in use by N epics. */
export function statusOf(r: WorkflowRow): { text: string; kind: "draft" | "published" | "inuse" | "archived" } {
  if (r.archived) return { text: "archived", kind: "archived" };
  if (!r.published) return { text: "draft", kind: "draft" };
  const n = r.pinned_by.length;
  return n ? { text: `in use by ${n} epic${n === 1 ? "" : "s"}`, kind: "inuse" } : { text: "published", kind: "published" };
}

/** One line saying what the workflow is for: its description, else its shape. */
export function summaryOf(r: WorkflowRow): string {
  const d = r.description.trim();
  if (d) return d;
  return `${r.roles} role${r.roles === 1 ? "" : "s"}${r.source ? `, copied from ${r.source}` : ""}.`;
}

export function WorkflowList({ rows, selected, canEdit, onSelect, onDuplicate, onDelete, onRestore, pending, showArchived, onShowArchived, below }: {
  rows: WorkflowRow[]; selected: string | null; canEdit: boolean;
  onSelect: (ref: string) => void; onDuplicate: (ref: string) => void; pending: boolean;
  onDelete?: (ref: string) => void; onRestore?: (ref: string) => void;
  showArchived?: boolean; onShowArchived?: (on: boolean) => void;
  /** A form for this row (Duplicate, Delete confirm), shown right under it. */
  below?: (ref: string) => React.ReactNode;
}): React.JSX.Element {
  const presets = rows.filter((r) => r.builtin);
  const custom = rows.filter((r) => !r.builtin && !r.archived);
  const archived = rows.filter((r) => r.archived);
  const chip = { draft: styles.badgeDraft, published: styles.badgePub, inuse: styles.badgeUse, archived: "" };
  const group = (title: string, hint: string, list: WorkflowRow[], testid: string, empty: string) => (
    <>
      <h2 className={styles.group}>{title}</h2>
      <p className={styles.help}>{hint}</p>
      {list.length === 0 ? <p className={styles.empty} data-testid={`${testid}-empty`}>{empty}</p> : null}
      <ul className={styles.list} data-testid={testid}>
        {list.map((r) => {
          const st = statusOf(r);
          return (
            <li key={r.ref}>
              <div role="button" tabIndex={0} aria-pressed={selected === r.ref}
                className={`${styles.item} ${selected === r.ref ? styles.itemActive : ""}`} data-testid={`wf-row-${r.ref}`}
                onClick={() => onSelect(r.ref)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(r.ref); } }}>
                <span className={styles.itemHead}>
                  <span className={styles.itemName}>{r.name || r.id}</span>
                  {r.builtin ? <span className={styles.badge} data-testid={`wf-preset-${r.ref}`}>preset</span> : null}
                  <span className={`${styles.badge} ${chip[st.kind]}`} data-testid={`wf-status-${r.ref}`}>{st.text}</span>
                </span>
                <span className={styles.itemSummary} data-testid={`wf-summary-${r.ref}`}>{summaryOf(r)}</span>
                <span className={styles.itemMeta}>
                  <span className={styles.mono}>{r.ref}</span>{r.source ? ` · from ${r.source}` : ""}
                </span>
                <span className={styles.itemMeta} data-testid={`wf-pins-${r.ref}`}>
                  {r.pinned_by.length ? `pinned by ${r.pinned_by.length} epic${r.pinned_by.length === 1 ? "" : "s"}: ${r.pinned_by.slice(0, 4).join(", ")}${r.pinned_by.length > 4 ? "…" : ""}` : "no epic pins it"}
                </span>
                {canEdit ? (
                  <span className={styles.row}>
                    {r.archived ? (
                      <button type="button" className={`${ui.button} ${styles.small}`} disabled={pending} data-testid={`wf-restore-${r.ref}`}
                        onClick={(e) => { e.stopPropagation(); onRestore?.(r.ref); }}>Restore</button>
                    ) : (
                      <button type="button" className={`${ui.button} ${styles.small}`} disabled={pending} data-testid={`wf-duplicate-${r.ref}`}
                        onClick={(e) => { e.stopPropagation(); onDuplicate(r.ref); }}>Duplicate to edit</button>
                    )}
                    {!r.builtin && !r.archived && onDelete ? (
                      <button type="button" className={`${ui.button} ${styles.small} ${styles.dangerButton}`} disabled={pending} data-testid={`wf-delete-${r.ref}`}
                        onClick={(e) => { e.stopPropagation(); onDelete(r.ref); }}>Delete</button>
                    ) : null}
                  </span>
                ) : null}
              </div>
              {below?.(r.ref)}
            </li>
          );
        })}
      </ul>
    </>
  );
  return (
    <nav aria-label="Workflows" data-testid="design-list">
      {group("Presets", "Ready to use and never change. Duplicate one to make your own.", presets, "wf-presets", "No presets: the board could not load them. Reload the page.")}
      {group("Your workflows", "Copies you made. A draft can be edited; a published version is fixed.", custom, "wf-custom",
        canEdit ? "None yet. Press Duplicate to edit on a preset to start one." : "None yet. An admin makes one by duplicating a preset.")}
      {onShowArchived ? (
        <label className={`${styles.check} ${styles.archivedToggle}`}>
          <input type="checkbox" checked={Boolean(showArchived)} onChange={(e) => onShowArchived(e.target.checked)} data-testid="wf-show-archived" />
          Show archived versions
        </label>
      ) : null}
      {showArchived ? group("Archived", "Published versions no epic used, set aside. Restore puts one back in the list.", archived, "wf-archived", "Nothing is archived.") : null}
    </nav>
  );
}
