// Agent avatars (owner m-ff00fad1ec: "curate a better set of icons for agents that match the overall
// theme of the app — check the user icons"; m-9bbc0582b6: "remove the bot like aspect"). The people
// avatars are the board's illustrated identities (avatars.py human_avatar_svg: a 36×36 rounded square in
// the warm palette, a torso, a round face with two dot eyes and a smile, a hair shape). An agent seat is
// drawn as one more PERSON in exactly that language — same square, torso, face, eyes and smile — with a
// hair colour per role and one small emblem that names the role at a glance:
//   architect  round glasses                    engineer  hard hat
//   qa         a magnifier badge                adversary  angled brows
//   sme        a mortarboard
// No antenna, plates or bolts: nothing robot-like. The stroke glyphs in iconPaths.ts stay for the Models
// dialog and the role pickers.
import type { SeatRole } from "./iconPaths";

const INK = "#3A2B29";
const SKIN = "#D9A07D";
const MOUTH = "#7D4B42";

/** bg, torso, hair — each role its own square and hair in the palette the people avatars use. */
const PALETTE: Record<SeatRole, { bg: string; torso: string; hair: string }> = {
  architect: { bg: "#70BCE8", torso: "#4B252B", hair: "#2B2B33" },
  engineer: { bg: "#8DD9B5", torso: "#2E9C64", hair: "#6B3F2A" },
  qa: { bg: "#F3B89A", torso: "#8B4A32", hair: "#3A2B29" },
  adversary: { bg: "#D98C9D", torso: "#17191E", hair: "#7A1F2B" },
  sme: { bg: "#D9A441", torso: "#633A68", hair: "#8C8C94" },
};

/** Hair shapes borrowed from the people set (avatars.py hair_shapes), one per role. */
const HAIR: Record<SeatRole, string> = {
  architect: "M10 17V13c1-8 14-9 17-3-6-1-8 5-17 7",
  engineer: "M10 15c2-8 13-9 17-2l-6-2-4 4-7 2",
  qa: "M9 16c2-9 8-10 10-5 4-5 9-1 8 5l-6-3-3 3-4-2-5 4",
  adversary: "M9 15c2-7 5-8 8-7l2 4 8-2v6l-4-2-4 3-5-3-5 3",
  sme: "M10 14c1-7 4-8 6-5 2-4 5-2 5 1 3-3 6 0 5 5",
};

function person(role: SeatRole, emblem: string): string {
  const c = PALETTE[role];
  return [
    `<rect width="36" height="36" rx="8" fill="${c.bg}"/>`,
    // torso, face, hair, eyes and smile exactly as the people avatars draw them
    `<path d="M4 36c1-9 7-13 14-13s13 4 14 13" fill="${c.torso}"/>`,
    `<path d="M11 14c0-9 14-9 14 0v5c0 6-4 8-7 8s-7-2-7-8z" fill="${SKIN}"/>`,
    `<path d="${HAIR[role]}" fill="${c.hair}"/>`,
    `<circle cx="15" cy="18" r="1" fill="${INK}"/>`,
    `<circle cx="22" cy="18" r="1" fill="${INK}"/>`,
    `<path d="M16 22q2 2 4 0" fill="none" stroke="${MOUTH}" stroke-width="1.2" stroke-linecap="round"/>`,
    emblem,
  ].join("");
}

export const AGENT_AVATARS: Record<SeatRole, string> = {
  architect: person("architect",
    // round glasses
    `<circle cx="15" cy="18" r="2.8" fill="none" stroke="#5865F2" stroke-width="1.1"/>` +
    `<circle cx="22" cy="18" r="2.8" fill="none" stroke="#5865F2" stroke-width="1.1"/>` +
    `<path d="M17.8 18h1.4" stroke="#5865F2" stroke-width="1.1"/>`),
  engineer: person("engineer",
    // hard hat over the hair
    `<path d="M11 12c0-6 14-6 14 0v1H11z" fill="#EABF3B"/>` +
    `<rect x="9" y="12.5" width="18" height="2" rx="1" fill="#D9A441"/>`),
  qa: person("qa",
    // magnifier badge, bottom right
    `<circle cx="27" cy="27" r="4.2" fill="#F2EDE4" stroke="#168B82" stroke-width="1.6"/>` +
    `<path d="M30 30l3.5 3.5" stroke="#168B82" stroke-width="2" stroke-linecap="round"/>`),
  adversary: person("adversary",
    // angled brows
    `<path d="M12.5 15l4 1.2M24.5 15l-4 1.2" stroke="#C84455" stroke-width="1.3" stroke-linecap="round"/>`),
  sme: person("sme",
    // mortarboard over the hair
    `<path d="M8 11l10-4 10 4-10 4z" fill="#24212B"/>` +
    `<path d="M13 13v3c0 2.5 10 2.5 10 0v-3" fill="none" stroke="#24212B" stroke-width="1.6"/>` +
    `<path d="M28 11v5" stroke="#24212B" stroke-width="1.2" stroke-linecap="round"/>`),
};

/** The inline SVG markup of an agent seat's avatar at `size` px (36×36 viewBox, like the people avatars). */
export function agentAvatarSvg(role: SeatRole, size: number): string {
  return `<svg width="${size}" height="${size}" viewBox="0 0 36 36" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">${AGENT_AVATARS[role]}</svg>`;
}
