import { api, postJson } from "./client";
export interface ReviewContext {
  ticket_id: string; source_title: string; source_kind: string; design_ref: string;
  reviewed_version: number; current_version: number; gate_event_id: string | null;
  can_approve: boolean; can_review: boolean;
}
export const getReviewContext = (id: string, source: string, version: number, request?: string | null) => {
  const params = new URLSearchParams({ source, version: String(version) });
  if (request) params.set("request", request);
  return api<ReviewContext>(`/v1/docs/${encodeURIComponent(id)}/context?${params}`);
};
export interface ReviewWrite {
  ticket_id: string; design_ref: string; reviewed_version: number; idempotency_key: string;
  artifacts?: string[];
}
export const decideDesign = (body: ReviewWrite & { gate_event_id: string; decision: "approve" | "request_changes"; feedback?: string }) =>
  postJson<{ message_id?: string; decision: string; unresolved_mentions?: string[]; delivery_note?: string }>("/v1/gates/decide", body);
export const commentDocument = (body: ReviewWrite & { text: string }) =>
  postJson<{ message_id: string; unresolved_mentions?: string[]; delivery_note?: string }>("/v1/docs/comments", body);
