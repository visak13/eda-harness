import { ICON_PATHS, type IconName } from "./iconPaths";
export type { IconName } from "./iconPaths";

/** Approved S1 contextual family. Decorative: the enclosing control supplies its name. */
export function Icon({ name, size = 18 }: { name: IconName; size?: 16 | 18 | 24 }): React.JSX.Element {
  return <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor"
    strokeWidth="1.85" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false"
    style={{ flexShrink: 0, verticalAlign: "middle" }} data-icon={name}>
    <path d={ICON_PATHS[name]} />
  </svg>;
}
