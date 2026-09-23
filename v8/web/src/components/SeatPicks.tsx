import { modelLabel } from "../api/seats";
import { Avatar, ProviderIcon } from "./Avatar";
import { modelProvider } from "./iconPaths";
import ui from "./ui.module.css";
import styles from "./SeatPicks.module.css";

// S-UI (owner m-ec5a9b86c5 "the thinking level, will it be global or per role?"): one row per role —
// role glyph, the model select with its provider glyph, and the effort select BESIDE it. Shared by the
// new-epic dialog, the quick-task dialog and Actions → Models…, so the three read the same. Claude seats
// are capped at medium fleet-wide (ruling 2026-08-04): on a Claude row "high" is disabled and the row
// says so; switching a row to Claude clamps a high effort to medium.

export const EFFORTS = ["low", "medium", "high"] as const;
export type Effort = (typeof EFFORTS)[number];
export const CLAUDE_EFFORT_CAP: Effort = "medium";

/** A model that runs on a Claude seat (capped at medium); GPT/codex seats may run high. */
export function isClaudeModel(model: string | null | undefined): boolean {
  return modelProvider(model) !== "gpt";
}

/** The effort a row actually runs at: high on a Claude model is capped at medium. */
export function clampEffort(model: string | null | undefined, effort: Effort): Effort {
  return effort === "high" && isClaudeModel(model) ? CLAUDE_EFFORT_CAP : effort;
}

export function SeatPickRow({ role, options, model, effort, disabled, onModel, onEffort, testIdPrefix }: {
  role: string;
  options: string[];
  model: string;
  effort: Effort;
  disabled?: boolean;
  onModel: (id: string) => void;
  onEffort: (e: Effort) => void;
  /** data-testid prefix: `<prefix>-model-<role>` and `<prefix>-effort-<role>`. */
  testIdPrefix: string;
}): React.JSX.Element {
  const claude = isClaudeModel(model);
  const modelId = `${testIdPrefix}-model-${role}`;
  const effortId = `${testIdPrefix}-effort-${role}`;
  return (
    <div className={styles.row} data-testid={`${testIdPrefix}-row-${role}`}>
      <span className={styles.role}>
        <Avatar id={role} size={24} />
        <span className={styles.roleName}>{role}</span>
      </span>
      <label className={styles.model} htmlFor={modelId}>
        <span className={styles.srOnly}>{role} model</span>
        <ProviderIcon model={model} />
        <select id={modelId} className={ui.select} value={model} disabled={disabled || !options.length}
          onChange={(e) => { onModel(e.target.value); onEffort(clampEffort(e.target.value, effort)); }} data-testid={modelId}>
          {options.map((id) => <option key={id} value={id}>{modelLabel(id)}</option>)}
        </select>
      </label>
      <label className={styles.effort} htmlFor={effortId}>
        <span className={styles.srOnly}>{role} effort</span>
        <select id={effortId} className={ui.select} value={clampEffort(model, effort)} disabled={disabled}
          onChange={(e) => onEffort(e.target.value as Effort)} data-testid={effortId}>
          {EFFORTS.map((e) => (
            <option key={e} value={e} disabled={e === "high" && claude}>{e}</option>
          ))}
        </select>
      </label>
      <span className={styles.cap} data-testid={`${testIdPrefix}-cap-${role}`}>{claude ? "Claude: medium max" : ""}</span>
    </div>
  );
}

/** The header over a stack of rows. */
export function SeatPickHead(): React.JSX.Element {
  return (
    <div className={styles.head} aria-hidden="true">
      <span>Role</span><span>Model</span><span>Effort</span><span />
    </div>
  );
}
