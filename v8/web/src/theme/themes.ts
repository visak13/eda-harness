// The table of record for the four themes (design-dc3a77cbc1 §4.3). `tokens.css` is
// GENERATED from this module by `scripts/emit-tokens.mjs` — never hand-edit the CSS.
//
// Token keys are the Folio set from `board-concepts-r2/source/design.css .folio{}`
// (strategy_ll §4), plus two keys the design implies but its §4.3 table omits:
//   - `secondary`: decorative chip background (design.css `.chip{background:var(--secondary)}`).
//     No contrast criterion gates it; kept in the rail/line family per theme.
//   - `buttonink`: the dark ink used for text on the salmon primary button
//     (design §4.2 "button text is ink on salmon"; design.css `.btn.primary{color:#342B25}`).
//     It equals the theme `ink` for the light themes but must stay dark on Ember, whose
//     `ink` is light — and the criterion's `button-ink/accent` pair must reach ≥7:1 on
//     Folio HC, so it is its own token, not `ink`.

export const TOKEN_KEYS = [
  "bg",
  "panel",
  "rail",
  "ink",
  "muted",
  "line",
  "strongline",
  "accent",
  "accentwash",
  "accentink",
  "success",
  "successwash",
  "secondary",
  "buttonink",
] as const;

export type TokenKey = (typeof TOKEN_KEYS)[number];
export type ThemeId = "folio" | "dusk" | "ember" | "folio-hc";

export interface Theme {
  id: ThemeId;
  label: string;
  scheme: "light" | "dark";
  tokens: Record<TokenKey, string>;
}

// Values are verbatim from design §4.3. `secondary`/`buttonink` are the documented fills above.
export const THEMES: Theme[] = [
  {
    id: "folio",
    label: "Folio",
    scheme: "light",
    tokens: {
      bg: "#F7F2E9",
      panel: "#FFFDF8",
      rail: "#EEE5D8",
      ink: "#342B25",
      muted: "#756454",
      line: "#D8CABB",
      strongline: "#9A8876",
      accent: "#F1A295",
      accentwash: "#F6DDD3",
      accentink: "#873F38",
      success: "#46634B",
      successwash: "#E8EBDD",
      secondary: "#EDE4D8",
      buttonink: "#342B25",
    },
  },
  {
    id: "dusk",
    label: "Dusk",
    scheme: "light",
    tokens: {
      bg: "#EDE4D6",
      panel: "#F4ECE0",
      rail: "#E3D8C8",
      ink: "#2A2320",
      muted: "#6B5A4B",
      line: "#CDBFAE",
      strongline: "#8F7B68",
      accent: "#E89A8C",
      accentwash: "#EED2C7",
      accentink: "#7F3A33",
      success: "#3F5A44",
      successwash: "#E2E6D6",
      secondary: "#DFD4C4",
      buttonink: "#2A2320",
    },
  },
  {
    id: "ember",
    label: "Ember",
    scheme: "dark",
    tokens: {
      bg: "#1E1A17",
      panel: "#262120",
      rail: "#2E2825",
      ink: "#E8DFD2",
      muted: "#A8998A",
      line: "#3A322E",
      // #6E5F54 (§4.3 draft) = 2.82:1 on Ember bg, below the 3:1 control-boundary bar;
      // §4.3 amended to #7C6C5C to clear SC 1.4.11 (architect ruling m-e721a800f0).
      strongline: "#7C6C5C",
      accent: "#F1A295",
      accentwash: "#4C302B",
      accentink: "#F1A295",
      success: "#8FB597",
      successwash: "#2F3A31",
      secondary: "#37302C",
      buttonink: "#342B25",
    },
  },
  {
    id: "folio-hc",
    label: "Folio HC",
    scheme: "light",
    tokens: {
      bg: "#FFFDF8",
      panel: "#FFFFFF",
      rail: "#F7F2E9",
      ink: "#1A1512",
      muted: "#4E4034",
      line: "#C9B9A8",
      strongline: "#8A7868",
      accent: "#F1A295",
      accentwash: "#F6DDD3",
      accentink: "#6E2C26",
      success: "#2F4A35",
      successwash: "#E8EBDD",
      secondary: "#EFE7DA",
      buttonink: "#1A1512",
    },
  },
];

export const DEFAULT_THEME: ThemeId = "folio";
export const THEME_IDS = THEMES.map((t) => t.id);

export function themeById(id: string): Theme | undefined {
  return THEMES.find((t) => t.id === id);
}
