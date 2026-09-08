import { DEFAULT_THEME, THEME_IDS, type ThemeId } from "./themes";

export const THEME_STORAGE_KEY = "edp8.theme";

type MatchFn = (query: string) => boolean;

const defaultMatch: MatchFn = (q) =>
  typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia(q).matches
    : false;

function isThemeId(v: string | null): v is ThemeId {
  return v !== null && (THEME_IDS as string[]).includes(v);
}

/**
 * The single source of truth for which theme applies, given a stored value and the OS
 * media queries. Order (design §4.3, criterion c-250f85164e): an explicit stored choice
 * wins; else prefers-contrast:more → folio-hc; else prefers-color-scheme:dark → ember;
 * else folio. The inline pre-paint script in index.html MUST mirror this exactly.
 */
export function resolveTheme(stored: string | null, match: MatchFn = defaultMatch): ThemeId {
  if (isThemeId(stored)) return stored;
  if (match("(prefers-contrast: more)")) return "folio-hc";
  if (match("(prefers-color-scheme: dark)")) return "ember";
  return DEFAULT_THEME;
}

/** Read the persisted choice (null when unset or storage is unavailable). */
export function storedTheme(): string | null {
  try {
    return localStorage.getItem(THEME_STORAGE_KEY);
  } catch {
    return null;
  }
}

/** Apply a theme to <html> (data-theme drives the token overrides in tokens.css). */
export function applyTheme(id: ThemeId): void {
  document.documentElement.dataset.theme = id;
}

/** Persist + apply. Storage failures never block the visual switch. */
export function persistTheme(id: ThemeId): void {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, id);
  } catch {
    /* private mode / disabled storage — apply anyway */
  }
  applyTheme(id);
}
