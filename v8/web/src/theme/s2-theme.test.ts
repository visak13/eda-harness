import { describe, it, expect, vi, afterEach } from "vitest";
import { readFileSync } from "node:fs";
import { THEMES, TOKEN_KEYS } from "./themes";
import { resolveTheme } from "./resolve";
const html = readFileSync("index.html", "utf8");
const script = html.match(/<script>([\s\S]*?)<\/script>/)![1];
const css = readFileSync("src/theme/tokens.css", "utf8");
afterEach(() => { localStorage.clear(); vi.unstubAllGlobals(); });
describe("eight-theme prepaint/token contract", () => {
  it("enumerates exactly eight complete palettes and true-black Obsidian", () => {
    expect(THEMES).toHaveLength(8);
    expect(THEMES.find((t) => t.id === "obsidian")!.tokens.bg).toBe("#000000");
    for (const theme of THEMES) expect(Object.keys(theme.tokens).sort()).toEqual([...TOKEN_KEYS].sort());
  });
  it.each(THEMES)("$id prepaint and CSS match authoritative tokens", (theme) => {
    localStorage.setItem("edp8.theme", theme.id);
    vi.stubGlobal("matchMedia", () => ({ matches: true }));
    new Function(script)();
    expect(document.documentElement.dataset.theme).toBe(theme.id);
    expect(resolveTheme(theme.id, () => true)).toBe(theme.id);
    const block = css.split(`html[data-theme="${theme.id}"]`)[1]?.split("}")[0] ?? "";
    for (const key of TOKEN_KEYS) expect(block).toContain(`--${key}: ${theme.tokens[key]}`);
  });
  it.each([[false,false,"folio"], [true,false,"folio-hc"], [false,true,"ember"], [true,true,"folio-hc"]] as const)("invalid stored defaults contrast=%s dark=%s", (contrast,dark,id) => {
    localStorage.setItem("edp8.theme", "invalid");
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("contrast") ? contrast : dark }));
    new Function(script)(); expect(document.documentElement.dataset.theme).toBe(id);
  });
});
