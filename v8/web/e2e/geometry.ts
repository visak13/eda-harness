// Canonical EXPECTED design geometry — design §4.2 (concepts.md, the measurable bars @ 1440×900).
//
// This module is the single source of the EXPECTED numbers. The fidelity spec measures the LIVE
// DOM (driven by the real CSS) and compares each measurement against a token here. The two are
// INDEPENDENT ON PURPOSE: the CSS does NOT derive from this module. So when a real CSS geometry
// value changes (e.g. sidebar 216→200px), the DOM measurement diverges from the token and the
// check FAILS with a measured-vs-expected message (criterion c-7c51c6b69b). Do not wire the CSS to
// import these values — that would make the check non-load-bearing.

export const GEOMETRY = {
  // Shell (design §4.2): rail x=0 w=216, header x=216 h=72, main x=256 w=1144.
  sidebar: { x: 0, w: 216 },
  header: { x: 216, h: 72 },
  main: { x: 256, w: 1144 },

  // Decisions home split (design §4.2): 744 / 336, gap 64.
  homeGrid: { left: 744, right: 336, gap: 64 },

  // Ruling drawer (design §4.2): 1112px, top 20, radius 12, split 650 / 462; right edge = 1440-20.
  drawer: { w: 1112, top: 20, rightEdge: 1420, radius: 12, splitLeft: 650, splitRight: 462 },

  // Controls (design §4.2): buttons height 40, radius 6.
  button: { h: 40 },

  // Type scale (design §4.2): Georgia page/doc titles 38, Segoe UI body 14/22, Consolas ids 12.
  type: {
    h1: { family: "Georgia", px: 38 },
    body: { px: 14, line: 22 },
    mono: { family: "Consolas", px: 12 },
  },

  // Rules (design §4.2): 3px salmon underline for the active tab; focus ring 2px offset 3px.
  tabUnderline: 3,
  focus: { width: 2, offset: 3 },

  // Pixelmatch bands @ 1440×900 (design §4.2): the two fixed-chrome regions Astra pinned.
  bands: {
    rail: { x: 0, y: 0, w: 216, h: 900 },
    header: { x: 216, y: 0, w: 1224, h: 72 },
  },
} as const;

export type Geometry = typeof GEOMETRY;
