// Agent avatars (owner m-ff00fad1ec: "curate a better set of icons for agents that match the overall
// theme of the app — check the user icons"). The people avatars are the board's illustrated identities
// (avatars.py human_avatar_svg: a 36×36 rounded square in the warm palette, a torso, a face with two dot
// eyes and a smile). An agent seat is drawn in the SAME language — same square, torso and eye ink — as a
// small robot character, one per role, with one emblem that names the role at a glance:
//   architect  glasses + a drafting square      engineer  hard hat
//   qa         a magnifier badge                adversary  angled brows
//   sme        a mortarboard
// The stroke glyphs in iconPaths.ts stay for the Models dialog and the role pickers.
import type { SeatRole } from "./iconPaths";

const INK = "#3A2B29";
const HEAD = "#F2EDE4";
const HEAD_EDGE = "#C9BFB0";

/** bg, torso, accent — each role its own square in the palette the people avatars use. */
const PALETTE: Record<SeatRole, { bg: string; torso: string; accent: string }> = {
  architect: { bg: "#70BCE8", torso: "#4B252B", accent: "#5865F2" },
  engineer: { bg: "#8DD9B5", torso: "#2E9C64", accent: "#EABF3B" },
  qa: { bg: "#F3B89A", torso: "#8B4A32", accent: "#168B82" },
  adversary: { bg: "#D98C9D", torso: "#17191E", accent: "#C84455" },
  sme: { bg: "#D9A441", torso: "#633A68", accent: "#7C3AED" },
};

function robot(role: SeatRole, emblem: string): string {
  const c = PALETTE[role];
  return [
    `<rect width="36" height="36" rx="8" fill="${c.bg}"/>`,
    // torso, as the people avatars draw it
    `<path d="M4 36c1-9 7-13 14-13s13 4 14 13" fill="${c.torso}"/>`,
    // antenna
    `<path d="M18 9V6" stroke="${INK}" stroke-width="1.4" stroke-linecap="round"/>`,
    `<circle cx="18" cy="5" r="1.5" fill="${c.accent}"/>`,
    // head plate with a soft edge, ear bolts
    `<rect x="10" y="9" width="16" height="15" rx="4.5" fill="${HEAD}" stroke="${HEAD_EDGE}" stroke-width="0.8"/>`,
    `<rect x="7.5" y="14" width="2.5" height="5" rx="1" fill="${HEAD_EDGE}"/>`,
    `<rect x="26" y="14" width="2.5" height="5" rx="1" fill="${HEAD_EDGE}"/>`,
    // eyes and smile in the people avatars' ink
    `<circle cx="14.5" cy="16" r="1.3" fill="${INK}"/>`,
    `<circle cx="21.5" cy="16" r="1.3" fill="${INK}"/>`,
    `<path d="M15.5 20.5q2.5 2 5 0" fill="none" stroke="#7D4B42" stroke-width="1.2" stroke-linecap="round"/>`,
    emblem,
  ].join("");
}

export const AGENT_AVATARS: Record<SeatRole, string> = {
  architect: robot("architect",
    // round glasses and a drafting square on the torso
    `<circle cx="14.5" cy="16" r="3" fill="none" stroke="#5865F2" stroke-width="1.1"/>` +
    `<circle cx="21.5" cy="16" r="3" fill="none" stroke="#5865F2" stroke-width="1.1"/>` +
    `<path d="M17.5 16h1" stroke="#5865F2" stroke-width="1.1"/>` +
    `<path d="M22 27l6 6h-6z" fill="#F2EDE4"/>`),
  engineer: robot("engineer",
    // hard hat
    `<path d="M11 10c0-5 14-5 14 0v1H11z" fill="#EABF3B"/>` +
    `<rect x="9" y="10.5" width="18" height="2" rx="1" fill="#D9A441"/>`),
  qa: robot("qa",
    // magnifier badge, bottom right
    `<circle cx="27" cy="27" r="4.2" fill="#F2EDE4" stroke="#168B82" stroke-width="1.6"/>` +
    `<path d="M30 30l3.5 3.5" stroke="#168B82" stroke-width="2" stroke-linecap="round"/>`),
  adversary: robot("adversary",
    // angled brows
    `<path d="M12 12.5l4 1.5M24 12.5l-4 1.5" stroke="#C84455" stroke-width="1.4" stroke-linecap="round"/>`),
  sme: robot("sme",
    // mortarboard
    `<path d="M8 10l10-4 10 4-10 4z" fill="#24212B"/>` +
    `<path d="M13 12v3c0 2.5 10 2.5 10 0v-3" fill="none" stroke="#24212B" stroke-width="1.6"/>` +
    `<path d="M28 10v5" stroke="#24212B" stroke-width="1.2" stroke-linecap="round"/>`),
};

/** The inline SVG markup of an agent seat's avatar at `size` px (36×36 viewBox, like the people avatars). */
export function agentAvatarSvg(role: SeatRole, size: number): string {
  return `<svg width="${size}" height="${size}" viewBox="0 0 36 36" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">${AGENT_AVATARS[role]}</svg>`;
}
