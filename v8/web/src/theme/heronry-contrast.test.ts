import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { THEMES, DEFAULT_THEME, DEFAULT_DARK_THEME, type Theme, type TokenKey } from "./themes";
import { contrastRatio } from "./contrast";

// S7 (design-e963c656f5 §4.12, owner m-0d028cfec7): the Heronry dark and light themes are the
// board's default tokens, and they meet WCAG 2.2 AA. The ratios are RECOMPUTED here from the shipped
// `themes.ts` values (never copied from the art's contrast-report.json): text ≥ 4.5:1 (SC 1.4.3),
// UI parts and borders ≥ 3:1 (SC 1.4.11). The brand table is the source of the shipped values:
// `v8/assets/brand/heronry/palettes.json` must equal them, so a palette edit cannot drift silently.

const heronry = THEMES.find((t) => t.id === "heronry")!;
const heronryDark = THEMES.find((t) => t.id === "heronry-dark")!;

// palettes.json key → theme token key (the brand names the design's §4.12 table uses).
const BRAND_TO_TOKEN: Record<string, TokenKey> = {
  background: "bg",
  surface: "panel",
  text: "ink",
  muted: "muted",
  accent: "accent",
  "button-text": "buttonink",
  success: "success",
  warning: "warning",
  danger: "danger",
  border: "strongline",
};

interface Pair { fg: TokenKey; bg: TokenKey; min: number; what: string }

const TEXT = 4.5;
const UI = 3;
const PAIRS: Pair[] = [
  ...(["bg", "panel"] as TokenKey[]).flatMap((bg): Pair[] => [
    { fg: "ink", bg, min: TEXT, what: "text" },
    { fg: "muted", bg, min: TEXT, what: "muted text" },
    { fg: "success", bg, min: TEXT, what: "success status text" },
    { fg: "warning", bg, min: TEXT, what: "warning status text" },
    { fg: "danger", bg, min: TEXT, what: "danger status text" },
    { fg: "accent", bg, min: UI, what: "accent control fill" },
    { fg: "strongline", bg, min: UI, what: "UI border" },
  ]),
  { fg: "buttonink", bg: "accent", min: TEXT, what: "button text on accent" },
];

function failures(theme: Theme): string[] {
  return PAIRS.flatMap(({ fg, bg, min, what }) => {
    const r = contrastRatio(theme.tokens[fg], theme.tokens[bg]);
    return r < min ? [`${theme.id} ${fg}/${bg} (${what}) ${r.toFixed(2)}:1 < ${min}:1`] : [];
  });
}

describe("Heronry is the board's default theme", () => {
  it("light is the default, dark answers a dark OS preference", () => {
    expect(DEFAULT_THEME).toBe("heronry");
    expect(DEFAULT_DARK_THEME).toBe("heronry-dark");
    expect(heronry.scheme).toBe("light");
    expect(heronryDark.scheme).toBe("dark");
  });

  it("ships exactly the brand palette (assets/brand/heronry/palettes.json)", () => {
    const palettes = JSON.parse(readFileSync("../assets/brand/heronry/palettes.json", "utf8")).heronry;
    for (const [mode, theme] of [["light", heronry], ["dark", heronryDark]] as const) {
      for (const [brandKey, token] of Object.entries(BRAND_TO_TOKEN)) {
        expect(theme.tokens[token].toUpperCase(), `${mode} ${brandKey} → --${token}`).toBe(
          palettes[mode][brandKey].toUpperCase(),
        );
      }
    }
  });
});

describe.each([heronry, heronryDark])("WCAG 2.2 AA · $label", (theme) => {
  it.each(PAIRS)(`${theme.id} $fg/$bg ($what) ≥ $min:1`, ({ fg, bg, min }) => {
    expect(contrastRatio(theme.tokens[fg], theme.tokens[bg])).toBeGreaterThanOrEqual(min);
  });
  it(`${theme.id} has zero failures`, () => {
    expect(failures(theme)).toEqual([]);
  });
});

// The §4.12 figures, recomputed: text/bg 14.43 (dark) and 13.53 (light); muted 7.97 / 5.36;
// button text on accent 7.58 / 5.96.
describe("the design's quoted ratios hold on the shipped tokens", () => {
  it.each([
    [heronryDark, "ink", "bg", 14.43],
    [heronry, "ink", "bg", 13.53],
    [heronryDark, "muted", "bg", 7.97],
    [heronry, "muted", "bg", 5.36],
    [heronryDark, "buttonink", "accent", 7.58],
    [heronry, "buttonink", "accent", 5.96],
  ] as const)("%#: %s", (theme, fg, bg, want) => {
    expect(contrastRatio(theme.tokens[fg], theme.tokens[bg])).toBeCloseTo(want, 1);
  });
});

describe("the guard fails on drift", () => {
  it("a muted text too close to the background is reported, naming pair and theme", () => {
    const broken: Theme = { ...heronry, tokens: { ...heronry.tokens, muted: "#B8A89C" } };
    expect(failures(broken).some((f) => f.startsWith("heronry muted/bg"))).toBe(true);
  });
});
