import { modelLabel } from "../api/seats";
import { sameOption, type SeatOption } from "../api/endpoints";
import { clampEffort, EFFORTS, effortCap, effortDisabledReason, type Effort, type ModelMetaMap } from "./SeatPicks";
import { roleLabel } from "./iconPaths";
import ui from "./ui.module.css";
import styles from "./SeatOptions.module.css";

// S7 (design-b6a55eed13 §4.E): a role's ORDERED option list — `model:<role>=<id>@<effort>|<id>@<effort>`.
// The first option is the default a spawn runs on; the SeatPickRow above shows it. This component edits
// the rest: change an option's model or effort, make it the default, remove it, add another. Every effort
// is clamped to its model's catalog cap here too, so the list never holds a pick the board would refuse.

export const effortOf = (o: SeatOption): Effort => (EFFORTS as readonly string[]).includes(o.effort) ? o.effort as Effort : "medium";

/** An option normalised: its effort named and clamped to the model's cap. */
export const normOption = (o: SeatOption, meta: ModelMetaMap): SeatOption =>
  ({ model: o.model, effort: clampEffort(o.model, effortOf(o), meta) });

/** The option a role's list can add next: an unused model at medium, else any unused model and effort. */
export function nextOption(list: SeatOption[], catalogIds: string[], meta: ModelMetaMap): SeatOption | undefined {
  return catalogIds.map((m) => normOption({ model: m, effort: "medium" }, meta)).find((o) => !list.some((x) => sameOption(x, o)))
    ?? catalogIds.flatMap((m) => EFFORTS.map((e) => normOption({ model: m, effort: e }, meta))).find((o) => !list.some((x) => sameOption(x, o)));
}

/** S12-ui2 (qa m-da89ef8294 a): "+ Add an option" as an icon button ON the role's row, after the effort select
 *  (SeatPickRow `add`); its words are the tooltip and the accessible name. */
export function AddOptionButton({ role, list, catalogIds, meta, disabled, onChange, testIdPrefix }: {
  role: string;
  list: SeatOption[];
  catalogIds: string[];
  meta?: ModelMetaMap;
  disabled?: boolean;
  onChange: (next: SeatOption[]) => void;
  testIdPrefix: string;
}): React.JSX.Element {
  const addable = nextOption(list, catalogIds, meta);
  const words = addable ? `Add an option for ${roleLabel(role)}` : "Every model and effort in this role's catalog is already an option.";
  return (
    <button type="button" className={styles.add} data-testid={`${testIdPrefix}-addopt-${role}`}
      disabled={disabled || !addable} title={words} aria-label={words}
      onClick={() => addable && onChange([...list, addable])}>
      <span aria-hidden="true">+</span>
    </button>
  );
}

export function RoleOptionList({ role, list, catalogIds, meta, disabled, onChange, testIdPrefix }: {
  role: string;
  /** The role's whole list, default first. */
  list: SeatOption[];
  /** The role's catalog models: what an option may be. */
  catalogIds: string[];
  meta?: ModelMetaMap;
  disabled?: boolean;
  onChange: (next: SeatOption[]) => void;
  testIdPrefix: string;
}): React.JSX.Element {
  const id = (i: number, part: string) => `${testIdPrefix}-opt${i}-${part}-${role}`;
  const set = (i: number, o: SeatOption) => onChange(list.map((x, k) => (k === i ? normOption(o, meta) : x)));
  if (list.length < 2) return <></>;
  return (
    <div className={styles.list} data-testid={`${testIdPrefix}-options-${role}`}>
      {list.slice(1).map((o, j) => {
        const i = j + 1;
        const cap = effortCap(o.model, meta);
        return (
          <div key={i} className={styles.item} data-testid={`${testIdPrefix}-opt${i}-row-${role}`}>
            <span className={styles.tag}>Option {i + 1}</span>
            <select className={ui.select} value={o.model} disabled={disabled} aria-label={`${role} option ${i + 1} model`}
              onChange={(e) => set(i, { model: e.target.value, effort: o.effort })} data-testid={id(i, "model")}>
              {catalogIds.map((m) => <option key={m} value={m}>{modelLabel(m, meta?.[m])}</option>)}
            </select>
            <select className={ui.select} value={effortOf(o)} disabled={disabled} aria-label={`${role} option ${i + 1} effort`}
              onChange={(e) => set(i, { model: o.model, effort: e.target.value })} data-testid={id(i, "effort")}>
              {EFFORTS.map((e) => (
                <option key={e} value={e} disabled={Boolean(effortDisabledReason(e, cap))}>
                  {e}{effortDisabledReason(e, cap) ? " (above cap)" : ""}
                </option>
              ))}
            </select>
            <button type="button" className={styles.add} disabled={disabled} data-testid={id(i, "remove")}
              aria-label={`Remove ${role} option ${i + 1}`} title={`Remove option ${i + 1}`}
              onClick={() => onChange(list.filter((_, k) => k !== i))}><span aria-hidden="true">×</span></button>
            <span className={styles.itemActions}>
              <button type="button" className={styles.textButton} disabled={disabled} data-testid={id(i, "default")}
                onClick={() => onChange([list[i], ...list.filter((_, k) => k !== i)])}>Make default</button>
            </span>
          </div>
        );
      })}
    </div>
  );
}
