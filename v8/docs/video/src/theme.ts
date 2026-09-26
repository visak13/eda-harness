// The Heronry dark palette (v8/assets/brand/heronry/palettes.json, heronry.dark) plus the splash
// heron's own colours and the board-avatar role colours (web/src/components/agentAvatars.ts).
import "@fontsource-variable/nunito-sans";
import "@fontsource/jetbrains-mono/400.css";

export const C = {
  bg: "#211B18",
  surface: "#302723",
  surface2: "#3A2F2A",
  text: "#F5EBDD",
  muted: "#C1AEA1",
  accent: "#E9A38B",
  success: "#93C5A3",
  warning: "#E7BD66",
  danger: "#F09C96",
  border: "#A18A7D",
  buttonText: "#2C201B",
  beak: "#C8703F",
  wing: "#5E3E2E",
  cream: "#FBF0DE",
} as const;

export const ROLE = {
  architect: "#70BCE8",
  engineer: "#8DD9B5",
  qa: "#F3B89A",
  adversary: "#D98C9D",
  sme: "#D9A441",
} as const;

export const FONT = "'Nunito Sans Variable', 'Nunito Sans', system-ui, sans-serif";
export const MONO = "'JetBrains Mono', ui-monospace, monospace";

export const FPS = 30;
export const W = 1920;
export const H = 1080;
