import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { DEFAULT_THEME, type ThemeId } from "./themes";
import { persistTheme, resolveTheme, storedTheme } from "./resolve";

interface ThemeContextValue {
  theme: ThemeId;
  setTheme: (id: ThemeId) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

// The initial value matches what the pre-paint script already stamped on <html>, so the
// first React render agrees with the painted palette (no second flash).
function initialTheme(): ThemeId {
  const painted = document.documentElement.dataset.theme;
  if (painted) return resolveTheme(painted);
  return resolveTheme(storedTheme());
}

export function ThemeProvider({ children }: { children: ReactNode }): React.JSX.Element {
  const [theme, setThemeState] = useState<ThemeId>(initialTheme);

  // Reconcile once on mount in case no pre-paint ran (e.g. tests, SSR).
  useEffect(() => {
    persistTheme(theme);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const setTheme = useCallback((id: ThemeId) => {
    persistTheme(id);
    setThemeState(id);
  }, []);

  return <ThemeContext value={{ theme, setTheme }}>{children}</ThemeContext>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within <ThemeProvider>");
  return ctx;
}

export { DEFAULT_THEME };
