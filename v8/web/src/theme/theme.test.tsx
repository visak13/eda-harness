import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { resolveTheme, THEME_STORAGE_KEY } from "./resolve";
import { ThemeProvider } from "./ThemeProvider";
import { ThemePicker } from "./ThemePicker";
import { THEMES } from "./themes";

const match = (on: string[]) => (q: string) => on.includes(q);

beforeEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});

describe("resolveTheme — OS media default order", () => {
  it("an explicit stored choice always wins", () => {
    expect(resolveTheme("dusk", match(["(prefers-color-scheme: dark)"]))).toBe("dusk");
  });
  it("unset + prefers-contrast:more → folio-hc (beats dark)", () => {
    expect(
      resolveTheme(null, match(["(prefers-contrast: more)", "(prefers-color-scheme: dark)"])),
    ).toBe("folio-hc");
  });
  it("unset + prefers-color-scheme:dark → ember", () => {
    expect(resolveTheme(null, match(["(prefers-color-scheme: dark)"]))).toBe("ember");
  });
  it("unset + no preference → folio", () => {
    expect(resolveTheme(null, match([]))).toBe("folio");
  });
  it("an unknown stored value is ignored (falls through to defaults)", () => {
    expect(resolveTheme("chartreuse", match([]))).toBe("folio");
  });
});

describe("ThemePicker", () => {
  it("is a radiogroup with a text label + radio per theme", () => {
    render(
      <ThemeProvider>
        <ThemePicker />
      </ThemeProvider>,
    );
    const radios = screen.getAllByRole("radio");
    expect(radios).toHaveLength(THEMES.length);
    for (const t of THEMES) expect(screen.getByRole("radio", { name: t.label })).toBeInTheDocument();
  });

  it("picking a theme persists to localStorage and sets html[data-theme]", () => {
    render(
      <ThemeProvider>
        <ThemePicker />
      </ThemeProvider>,
    );
    fireEvent.click(screen.getByRole("radio", { name: "Ember" }));

    expect(document.documentElement.dataset.theme).toBe("ember");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("ember");
  });

  it("reflects the active theme as the checked radio", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "dusk");
    render(
      <ThemeProvider>
        <ThemePicker />
      </ThemeProvider>,
    );
    expect(screen.getByRole("radio", { name: "Dusk" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Folio" })).not.toBeChecked();
  });
});
