import { useCallback, useState } from "react";

// Per-viewer UI preferences (S17: rail, epic header and composer collapse). Stored in localStorage
// under edp8.ui.<viewer>.<key>; every read and write is try/catch'd so a private window, blocked
// storage or a throwing accessor just falls back to the default and the page still renders.
const keyOf = (viewer: string, key: string) => `edp8.ui.${viewer || "anon"}.${key}`;

export function readFlag(viewer: string, key: string, fallback = false): boolean {
  try {
    const v = localStorage.getItem(keyOf(viewer, key));
    return v === null ? fallback : v === "1";
  } catch {
    return fallback;
  }
}

export function writeFlag(viewer: string, key: string, value: boolean): void {
  try {
    localStorage.setItem(keyOf(viewer, key), value ? "1" : "0");
  } catch {
    /* session-only: the toggle still works for this page view */
  }
}

/** A remembered boolean for this viewer; the setter persists (best effort). */
export function useViewerFlag(viewer: string, key: string, fallback = false): [boolean, (next: boolean) => void] {
  const [value, setValue] = useState(() => readFlag(viewer, key, fallback));
  const set = useCallback((next: boolean) => { setValue(next); writeFlag(viewer, key, next); }, [viewer, key]);
  return [value, set];
}
