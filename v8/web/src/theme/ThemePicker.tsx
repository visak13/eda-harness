import { THEMES, type ThemeId } from "./themes";
import { useTheme } from "./ThemeProvider";
import styles from "./ThemePicker.module.css";

// A real <fieldset> + native radios: the browser gives us the radiogroup role, arrow-key
// navigation and roving focus for free (design §4.3 "accessible radio-group picker").
// Each option carries a text label (never colour alone) and a swatch preview.
export function ThemePicker(): React.JSX.Element {
  const { theme, setTheme } = useTheme();

  // Header variant (design §4.3 "picker in the header"; human report 2026-09-10: the popover was the
  // only way to the picker and it had scrolled off screen): a labelled native <select>, always visible.
  return (
    <fieldset className={styles.picker}>
      <legend className={styles.legend}>Theme</legend>
      {THEMES.map((t) => (
        <label key={t.id} className={styles.option}>
          <input
            type="radio"
            name="edp8-theme"
            value={t.id}
            checked={theme === t.id}
            onChange={() => setTheme(t.id as ThemeId)}
          />
          <span
            className={styles.swatch}
            aria-hidden="true"
            style={{ background: t.tokens.bg, borderColor: t.tokens.line }}
          >
            <span style={{ background: t.tokens.accent }} />
            <span style={{ background: t.tokens.ink }} />
          </span>
          <span className={styles.label}>{t.label}</span>
        </label>
      ))}
    </fieldset>
  );
}
