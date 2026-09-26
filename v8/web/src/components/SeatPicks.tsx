import { modelLabel } from "../api/seats";
import type { ModelMeta } from "../api/types";
import { Avatar, ProviderIcon } from "./Avatar";
import { roleLabel } from "./iconPaths";
import ui from "./ui.module.css";
import styles from "./SeatPicks.module.css";

// S-UI (owner m-ec5a9b86c5 "the thinking level, will it be global or per role?"): one row per role —
// role glyph, the model select with its provider glyph, and the effort select BESIDE it. Shared by the
// new-epic dialog, the quick-task dialog and Actions → Models…, so the three read the same. S12: each
// catalog entry carries its own harness and effort cap (GET /v1/models `models`); a row disables the
// efforts above its entry's cap and says so, and switching a row clamps the effort to the new cap. The
// model id is never read for routing or caps (no prefix sniffing).

export const EFFORTS = ["low", "medium", "high"] as const;
export type Effort = (typeof EFFORTS)[number];
export type ModelMetaMap = Record<string, ModelMeta> | undefined;

const RANK: Record<Effort, number> = { low: 0, medium: 1, high: 2 };

/** The entry's effort cap from the catalog metadata; null = uncapped (or an entry the board did not describe). */
export function effortCap(model: string | null | undefined, meta: ModelMetaMap): Effort | null {
  const cap = meta?.[model ?? ""]?.effort_cap;
  return (EFFORTS as readonly string[]).includes(cap ?? "") ? cap as Effort : null;
}

/** The effort a row actually runs at: above the entry's cap is clamped to the cap. */
export function clampEffort(model: string | null | undefined, effort: Effort, meta?: ModelMetaMap): Effort {
  const cap = effortCap(model, meta);
  return cap && RANK[effort] > RANK[cap] ? cap : effort;
}

const HARNESS_LABEL: Record<string, string> = { claude: "Claude", codex: "Codex", pi: "Pi" };

/** t-20f0718990 (owner m-3136ceca05 "does anyone understand why any of the model + seat combo is greyed
 *  out?"): why a row's model select is greyed, in words; null when it is not. */
export function modelDisabledReason(options: string[], disabled?: boolean, disabledReason?: string | null): string | null {
  if (disabled) return disabledReason || "Locked here.";
  if (!options.length) return "No model in this role's catalog: add one in Admin → Seats & models → Models per role.";
  return null;
}

/** Why an effort option is greyed (above the entry's cap), for its title and the visible note. */
export function effortDisabledReason(e: Effort, cap: Effort | null): string | null {
  return cap !== null && RANK[e] > RANK[cap] ? `Effort above this model's cap (${cap})` : null;
}

export function SeatPickRow({ role, options, meta, model, effort, disabled, disabledReason, onModel, onEffort, testIdPrefix }: {
  role: string;
  options: string[];
  /** GET /v1/models `models`: each id's harness and effort cap. */
  meta?: ModelMetaMap;
  model: string;
  effort: Effort;
  disabled?: boolean;
  /** Why `disabled` is set, shown next to the row (e.g. "the seat is live"). */
  disabledReason?: string | null;
  onModel: (id: string) => void;
  onEffort: (e: Effort) => void;
  /** data-testid prefix: `<prefix>-model-<role>` and `<prefix>-effort-<role>`. */
  testIdPrefix: string;
}): React.JSX.Element {
  const cap = effortCap(model, meta);
  const harness = meta?.[model]?.harness;
  const modelId = `${testIdPrefix}-model-${role}`;
  const effortId = `${testIdPrefix}-effort-${role}`;
  const whyId = `${testIdPrefix}-why-${role}`;
  const capId = `${testIdPrefix}-cap-${role}`;
  const why = modelDisabledReason(options, disabled, disabledReason);
  const greyed = EFFORTS.filter((e) => effortDisabledReason(e, cap));
  return (
    <div className={styles.row} data-testid={`${testIdPrefix}-row-${role}`}>
      <span className={styles.role}>
        <Avatar id={role} size={24} />
        <span className={styles.roleName}>{roleLabel(role)}</span>
      </span>
      <label className={styles.model} htmlFor={modelId}>
        <span className={styles.srOnly}>{role} model</span>
        <ProviderIcon harness={harness} />
        <select id={modelId} className={ui.select} value={model} disabled={Boolean(why)} title={why ?? undefined} aria-describedby={why ? whyId : undefined}
          onChange={(e) => { onModel(e.target.value); onEffort(clampEffort(e.target.value, effort, meta)); }} data-testid={modelId}>
          {options.map((id) => <option key={id} value={id}>{modelLabel(id)}</option>)}
        </select>
      </label>
      <label className={styles.effort} htmlFor={effortId}>
        <span className={styles.srOnly}>{role} effort</span>
        <select id={effortId} className={ui.select} value={clampEffort(model, effort, meta)} disabled={disabled}
          title={greyed.length ? `${greyed.join(", ")}: ${effortDisabledReason(greyed[0], cap)}` : undefined} aria-describedby={greyed.length ? capId : undefined}
          onChange={(e) => onEffort(e.target.value as Effort)} data-testid={effortId}>
          {EFFORTS.map((e) => (
            <option key={e} value={e} disabled={Boolean(effortDisabledReason(e, cap))} title={effortDisabledReason(e, cap) ?? undefined}>
              {e}{effortDisabledReason(e, cap) ? " (above cap)" : ""}
            </option>
          ))}
        </select>
      </label>
      <span id={capId} className={styles.cap} data-testid={capId}>
        {greyed.length ? `${HARNESS_LABEL[harness ?? ""] ?? harness ?? "This model"}: ${cap} max. ${greyed.join(", ")} greyed: effort above this model's cap.` : ""}
      </span>
      {why ? <span id={whyId} className={styles.why} data-testid={whyId}>{why}</span> : null}
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
