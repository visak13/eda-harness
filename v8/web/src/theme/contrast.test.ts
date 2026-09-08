import { describe, it, expect } from "vitest";
import { THEMES, type Theme, type TokenKey } from "./themes";
import { contrastRatio } from "./contrast";

// Data-driven: every real product text/control pair, computed from the shipped
// `themes.ts` values, must clear its threshold on every theme (design §4.3, criterion
// c-e5bed3f6e2). A failure names the exact pair + theme. Thresholds: text ≥4.5:1
// (SC 1.4.3), control boundary + focus ring ≥3:1 (SC 1.4.11), and Folio HC text ≥7:1
// (SC 1.4.6). `buttonink/accent` is the ink-on-salmon primary button (design §4.2).

type Kind = "text" | "nontext";
interface Pair {
  fg: TokenKey;
  bg: TokenKey;
  kind: Kind;
  what: string;
}

const PAIRS: Pair[] = [
  { fg: "ink", bg: "bg", kind: "text", what: "body text on page" },
  { fg: "ink", bg: "panel", kind: "text", what: "body text on panel" },
  { fg: "ink", bg: "rail", kind: "text", what: "text on sidebar rail" },
  { fg: "muted", bg: "bg", kind: "text", what: "muted text on page" },
  { fg: "muted", bg: "panel", kind: "text", what: "muted text on panel" },
  { fg: "accentink", bg: "accentwash", kind: "text", what: "accent text on wash (chip/directive)" },
  { fg: "success", bg: "successwash", kind: "text", what: "success text on wash" },
  { fg: "buttonink", bg: "accent", kind: "text", what: "primary button text on salmon" },
  { fg: "strongline", bg: "bg", kind: "nontext", what: "control boundary on page" },
  { fg: "accentink", bg: "bg", kind: "nontext", what: "focus ring on page" },
];

function threshold(themeId: string, kind: Kind): number {
  if (kind === "nontext") return 3;
  return themeId === "folio-hc" ? 7 : 4.5;
}

/** All threshold violations for a theme, each message naming the pair + theme. */
export function contrastFailures(theme: Theme): string[] {
  const out: string[] = [];
  for (const p of PAIRS) {
    const min = threshold(theme.id, p.kind);
    const r = contrastRatio(theme.tokens[p.fg], theme.tokens[p.bg]);
    if (r < min) {
      out.push(`${theme.id} ${p.fg}/${p.bg} (${p.what}) ${r.toFixed(2)}:1 < ${min}:1`);
    }
  }
  return out;
}

describe.each(THEMES)("contrast · $label", (theme) => {
  it.each(PAIRS)(
    `${theme.id} $fg/$bg ($what) meets its threshold`,
    ({ fg, bg, kind, what }) => {
      const min = threshold(theme.id, kind);
      const r = contrastRatio(theme.tokens[fg], theme.tokens[bg]);
      expect(
        r,
        `${theme.id} ${fg}/${bg} (${what}) is ${r.toFixed(2)}:1, needs ≥ ${min}:1`,
      ).toBeGreaterThanOrEqual(min);
    },
  );

  it(`${theme.id} has zero contrast failures`, () => {
    expect(contrastFailures(theme)).toEqual([]);
  });
});

// Sanity anchors from the delivered audit (strategy_ll §4): Folio ink/bg 12.40:1,
// muted/bg 5.08:1, ink-on-salmon 6.81:1.
describe("sanity anchors (Folio)", () => {
  const folio = THEMES.find((t) => t.id === "folio")!;
  it("ink/bg ≈ 12.4:1", () => {
    expect(contrastRatio(folio.tokens.ink, folio.tokens.bg)).toBeCloseTo(12.4, 1);
  });
  it("muted/bg ≈ 5.08:1", () => {
    expect(contrastRatio(folio.tokens.muted, folio.tokens.bg)).toBeCloseTo(5.08, 1);
  });
  it("buttonink/accent (ink on salmon) ≈ 6.81:1", () => {
    expect(contrastRatio(folio.tokens.buttonink, folio.tokens.accent)).toBeCloseTo(6.81, 1);
  });
});

// The guard proves it: a deliberately broken hex fails, naming the pair and theme.
describe("the contrast guard fails on drift", () => {
  it("a broken ink (= bg) is reported, naming pair + theme", () => {
    const folio = THEMES.find((t) => t.id === "folio")!;
    const broken: Theme = { ...folio, tokens: { ...folio.tokens, ink: folio.tokens.bg } };
    const failures = contrastFailures(broken);
    expect(failures.length).toBeGreaterThan(0);
    expect(failures.some((f) => f.startsWith("folio ink/bg"))).toBe(true);
  });
});
