import { api, postJson } from "./client";
import type { Teammate } from "./admin";

// t-882e4d2eeb (design-e963c656f5 §4.18): Request access from the sign-in page, the admin's Requests list,
// and Remove (revoke + retire). Shapes mirror src/edp8/admin/access.py and teammates.py. The claim code and
// the token only ever travel in POST bodies, never in a URL.

export interface AccessAvailability { enabled: boolean; reason: string | null; roles: string[] }
export interface AccessAsked { id: string; claim_code: string; poll_s: number }
export type AccessClaim =
  | { status: "pending"; poll_s: number }
  | { status: "denied" }
  | { status: "expired" }
  | { status: "approved"; handle: string; token: string; board_url: string };

export interface AccessRequestRow {
  id: string;
  created_at: string;
  name: string;
  role_wanted: string;
  note: string;
  status: "pending" | "approved" | "denied" | "claimed" | "expired";
  decided_by: string | null;
  decided_at: string | null;
  handle: string | null;
}

/** An Admin → Teammates row with the removed flag (retired humans stay listed for the admin only). */
export type TeammateRow = Teammate & { retired?: boolean };

export const getAccessAvailability = () => api<AccessAvailability>("/v1/access-requests/available");
export const askAccess = (body: { name: string; role_wanted: string; note: string }) =>
  postJson<AccessAsked>("/v1/access-requests", body);
export const claimAccess = (code: string) => postJson<AccessClaim>("/v1/access-requests/claim", { code });

export const getAccessRequests = () => api<AccessRequestRow[]>("/v1/admin/access-requests");
export const approveAccess = (id: string, body: { handle?: string; admin?: boolean } = {}) =>
  postJson<AccessRequestRow>(`/v1/admin/access-requests/${encodeURIComponent(id)}/approve`, body);
export const denyAccess = (id: string) =>
  postJson<AccessRequestRow>(`/v1/admin/access-requests/${encodeURIComponent(id)}/deny`, {});
export const removeTeammate = (handle: string) =>
  postJson<{ handle: string; removed: boolean }>(`/v1/admin/teammates/${encodeURIComponent(handle)}/remove`, {});
