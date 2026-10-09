import { api, postJson } from "./client";

// s-aa76c83998 (design-63db8a7d42 item H): the epic's marked requirements (`GET /v1/epics/{id}/requirements`) and the
// Mark-as-requirement write (`POST /v1/requirements`, which sends no message). `blocked_reason` is the board's own
// sentence for what holds the epic open (absent when nothing does). A guest's answer is its own marks only.

export type RequirementState = "open" | "linked";

export interface RequirementRow {
  id: string;
  state: RequirementState;
  epic: string;
  ticket: string;
  source: string;
  char_start: number;
  char_end: number;
  text: string;
  by: string;
  at: string;
  criterion?: string;
  doc?: { id: string; version: number; heading: string };
  linked_by?: string;
}

export interface RequirementsList {
  requirements: RequirementRow[];
  digests: unknown[];
  blocked_reason?: string;
}

export const getEpicRequirements = (epicId: string) =>
  api<RequirementsList>(`/v1/epics/${encodeURIComponent(epicId)}/requirements`);

/** Record a span of a message as a requirement. A quote carries its character range; without one the board finds
 *  `text` in the message (the whole message when it does not occur). Idempotent: the same span is one requirement. */
export const markRequirement = (p: { messageId: string; charStart?: number | null; charEnd?: number | null; text?: string }) =>
  postJson<RequirementRow>("/v1/requirements", {
    message_id: p.messageId,
    char_start: p.charStart ?? null,
    char_end: p.charEnd ?? null,
    text: p.text ?? null,
  }).then((r) => r.value);
