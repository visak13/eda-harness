// The table of record for the eight themes (design-dc3a77cbc1 §4.3). `tokens.css` is
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
export type ThemeId = "folio" | "dusk" | "ember" | "folio-hc" | "sage" | "slate" | "midnight" | "obsidian";

export interface Theme {
  id: ThemeId;
  label: string;
  scheme: "light" | "dark";
  tokens: Record<TokenKey, string>;
}

// Original palettes retain their identity; S2 strengthens muted/boundary tokens for wash/rail contrast.
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
      muted: "#716050",
      line: "#D8CABB",
      strongline: "#897764",
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
      strongline: "#806C59",
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
      muted: "#B0A192",
      line: "#3A322E",
      // S2 audits boundaries against rail and wash surfaces too, not only page background.
      strongline: "#958370",
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
  {
    id: "sage", label: "Sage", scheme: "light",
    tokens: {
      bg: "#F1F4ED", panel: "#FCFDF9", rail: "#E1E8DC", ink: "#253126",
      muted: "#4E604E", line: "#C4D0BE", strongline: "#647760",
      accent: "#B9D0AB", accentwash: "#DFEAD7", accentink: "#35512E",
      success: "#35512E", successwash: "#DFEAD7", secondary: "#DAE3D4", buttonink: "#253126",
    },
  },
  {
    id: "slate", label: "Slate", scheme: "light",
    tokens: {
      bg: "#EFF2F5", panel: "#FCFDFE", rail: "#DEE5EB", ink: "#23303D",
      muted: "#4D5E70", line: "#C1CCD7", strongline: "#637588",
      accent: "#BBCFE4", accentwash: "#DCE7F2", accentink: "#314C69",
      success: "#31583D", successwash: "#DDEBDD", secondary: "#D8E1EB", buttonink: "#23303D",
    },
  },
  {
    id: "midnight", label: "Midnight", scheme: "dark",
    tokens: {
      bg: "#141923", panel: "#1C2431", rail: "#232D3D", ink: "#E3E9F2",
      muted: "#B0BDCF", line: "#3C4A60", strongline: "#8595AC",
      accent: "#B3C8EC", accentwash: "#303F59", accentink: "#C2D4F4",
      success: "#B1D6B9", successwash: "#293F35", secondary: "#303D50", buttonink: "#202B3D",
    },
  },
  {
    id: "obsidian", label: "Obsidian", scheme: "dark",
    tokens: {
      bg: "#000000", panel: "#141414", rail: "#1C1C1C", ink: "#E5E5E2",
      muted: "#B5B5B0", line: "#383838", strongline: "#858580",
      accent: "#D2C8B8", accentwash: "#35322E", accentink: "#DDD2C0",
      success: "#B9D0B6", successwash: "#2C362C", secondary: "#303030", buttonink: "#242320",
    },
  },
];

export const DEFAULT_THEME: ThemeId = "folio";
export const THEME_IDS = THEMES.map((t) => t.id);

export function themeById(id: string): Theme | undefined {
  return THEMES.find((t) => t.id === id);
}
