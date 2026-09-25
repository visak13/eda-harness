// Hand-authored contextual adaptations; not image-generated SVG.
import type { TicketStatus } from "../api/types";
export const ICON_PATHS = {
  "decisions": "M10 3Q12 1 14 3L21 10Q23 12 21 14L14 21Q12 23 10 21L3 14Q1 12 3 10ZM12 7v6m0 4h.01",
  "epics": "M6 7h15v14H6ZM17 7V3H3v14h3M10 12h7m-7 4h5",
  "seats": "M8 4a3 3 0 1 0 0 6 3 3 0 0 0 0-6ZM17 4a3 3 0 1 0 0 6 3 3 0 0 0 0-6ZM3 20v-4a5 5 0 0 1 10 0v4ZM14 12a5 5 0 0 1 8 4v4h-6",
  "library": "M3 4h18v4H3ZM5 8v12h14V8M10 12h4",
  // epic-91fcd3b370 S3: the Code tab rail entry (angle brackets and a slash)
  "code": "m8 7-5 5 5 5M16 7l5 5-5 5M14 4l-4 16",
  "find": "M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14ZM15 15l6 6",
  "add": "M12 4v16M4 12h16",
  "close": "M5 5l14 14M19 5 5 19",
  "chevron": "m5 9 7 7 7-7",
  "copy": "M8 7V3h13v14h-4M3 7h14v14H3Z",
  "external": "M14 3h7v7M21 3 11 13M10 5H4v15h15v-6",
  "back": "M20 12H4m7-7-7 7 7 7",
  "forward": "M4 12h16m-7-7 7 7-7 7",
  "history": "M3 10a9 9 0 1 1 1 8M3 4v6h6M12 6v6l4 2",
  "files": "M3 8V5h7l3 3h8v12H3ZM3 11h18",
  "design": "M5 2h9l5 5v15H5ZM14 2v6h5M8 12h8m-8 4h8",
  "work": "M3 3h18v18H3ZM7 8h.01M11 8h6M7 12h.01M11 12h6M7 16h.01M11 16h4",
  "reply": "m10 5-7 7 7 7M3 12h11q7 0 7 8",
  "expand": "M14 3h7v7M21 3l-7 7M3 14v7h7M3 21l7-7",
  "collapse": "M3 9h6V3M9 9 3 3M15 21v-6h6M15 15l6 6",
  "attach": "m9 16 8-8a3 3 0 0 0-4-4L4 13a5 5 0 0 0 7 7l9-9M7 14l8-8",
  "mention": "M16 8v7q4 3 5-3a9 9 0 1 0-4 8M16 9a5 5 0 1 0 0 6",
  "help": "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20ZM9 8q1-4 5-2t-1 6l-1 2m0 4h.01",
  "send": "M3 10 21 3l-7 18-4-7ZM10 14 21 3M10 14v6l3-2",
  "preferences": "M9 3h6l1 4 4 1 1 6-4 2-1 4-6 1-2-4-4-1-1-6 4-2ZM12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z",
  "usage": "M3 14h4v7H3ZM10 9h4v12h-4ZM17 3h4v18h-4Z",
  "refresh": "M3 9a9 9 0 0 1 16-4l2 3M21 3v5h-5M21 15a9 9 0 0 1-16 4l-2-3M3 21v-5h5",
  "filter": "M3 4h18l-7 9v8l-4-2v-6Z",
  "sort": "M7 21V3m-4 4 4-4 4 4M17 3v18m-4-4 4 4 4-4",
  "edit": "m3 21 2-7L16 3q2-2 5 1l-1 3L9 19ZM5 14l4 5M14 5l5 5",
  "check": "m4 12 5 5L20 6",
  "warning": "M10 4q2-3 4 0l8 15q1 2-2 2H4q-3 0-2-2ZM12 9v5m0 4h.01",
  "more": "M4 12a1 1 0 1 0 2 0 1 1 0 0 0-2 0ZM11 12a1 1 0 1 0 2 0 1 1 0 0 0-2 0ZM18 12a1 1 0 1 0 2 0 1 1 0 0 0-2 0Z",
  "download": "M12 3v12m-5-5 5 5 5-5M3 16v5h18v-5",
  "link": "m9 15 6-6M9 7l3-3a5 5 0 0 1 8 6l-4 4M8 10l-4 4a5 5 0 0 0 7 7l4-4",
  "play": "M6 3 21 12 6 21Z",
  "review-request": "M3 4h18v13H9l-6 4ZM7 8h10M7 12h7",
  "status-drafted": "M11 21H4V3h12v7M7 7h5M7 11h3m2 5 7-7 3 3-7 7-4 1Z",
  "status-designed": "M4 2h16v20H4ZM8 6h8M8 10h3v3H8ZM13 16h3v3h-3ZM9 13v4h4",
  "status-signed_off": "M4 2h16v20H4ZM8 6h8m-9 8 3 3 7-7",
  "status-ready": "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Z",
  "status-in_progress": "M12 3a9 9 0 1 1-9 9M3.5 7h.01M7 3.5h.01",
  "status-in_review": "M10 21H4V2h14v7M8 6h6M10 11h12v8h-7l-5 3ZM13 15h6",
  "status-blocked": "M8 2h8l6 6v8l-6 6H8l-6-6V8ZM7 12h10",
  "status-done": "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20ZM7 12l3 3 7-7",
  "status-partial": "m3 6 2 2 4-4M12 6h9M3 14h6v6H3ZM12 17h9",
  "status-dropped": "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20ZM5 19 19 5",
  "role-architect": "M12 2v3M10 7a2 2 0 1 0 4 0 2 2 0 0 0-4 0M11 9 5 21M13 9l6 12M7 16h10",
  "role-engineer": "M15 3a5 5 0 0 0-5 6l-7 7a2 2 0 0 0 3 3l7-7a5 5 0 0 0 6-5l-3 3-3-1-1-3Z",
  "role-qa": "M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14ZM15 15l6 6M7 10l2 2 4-4",
  "role-adversary": "M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16ZM12 1v6M12 17v6M1 12h6M17 12h6",
  "role-sme": "M2 9l10-5 10 5-10 5ZM6 11v5q6 4 12 0v-5M22 9v6",
  "provider-claude": "M12 3v18M4 7.5l16 9M4 16.5l16-9",
  "provider-gpt": "M12 2l9 5v10l-9 5-9-5V7ZM12 7l4 2.5v5L12 17l-4-2.5v-5Z"
} as const;
export type IconName = keyof typeof ICON_PATHS;
export const STATUS_ICONS = {
  "drafted": "status-drafted",
  "designed": "status-designed",
  "signed_off": "status-signed_off",
  "ready": "status-ready",
  "in_progress": "status-in_progress",
  "in_review": "status-in_review",
  "blocked": "status-blocked",
  "done": "status-done",
  "partial": "status-partial",
  "dropped": "status-dropped"
} as const satisfies Record<TicketStatus, IconName>;
export const STATUS_LABELS = {
  "drafted": "Drafted",
  "designed": "Designed",
  "signed_off": "Signed off",
  "ready": "Ready",
  "in_progress": "In progress",
  "in_review": "In review",
  "blocked": "Blocked",
  "done": "Done",
  "partial": "Partial",
  "dropped": "Dropped"
} as const;
/** S-UI (owner m-ec5a9b86c5): one glyph per seat role and per model provider, same stroke family. */
export const ROLE_ICONS = {
  "architect": "role-architect",
  "engineer": "role-engineer",
  "qa": "role-qa",
  "adversary": "role-adversary",
  "sme": "role-sme"
} as const satisfies Record<string, IconName>;
export type SeatRole = keyof typeof ROLE_ICONS;
/** The role of an AGENT seat id (`engineer.s-…`, `architect.epic-…`, or a bare role); null for a person. */
export function seatRole(id: string | null | undefined): SeatRole | null {
  const head = (id ?? "").split(".")[0];
  return Object.prototype.hasOwnProperty.call(ROLE_ICONS, head) ? head as SeatRole : null;
}
export const PROVIDER_ICONS = { "claude": "provider-claude", "gpt": "provider-gpt" } as const satisfies Record<string, IconName>;
/** The provider of a model id: GPT (`gpt-…`, `codex/…`, `openai…`) or Claude (`claude-…`, the `claude` seat). */
export function modelProvider(model: string | null | undefined): keyof typeof PROVIDER_ICONS | null {
  const m = (model ?? "").toLowerCase();
  if (m.startsWith("gpt-") || m.startsWith("codex/") || m.startsWith("openai")) return "gpt";
  if (m.startsWith("claude")) return "claude";
  return null;
}
