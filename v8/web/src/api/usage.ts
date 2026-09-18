import { api } from "./client";

export type UsageStatus = "available" | "stale" | "unavailable" | "auth_required" | "error";
export interface UsageWindow {
  key: string;
  window_minutes: number | null;
  used_percent: number | null;
  resets_at: number | null;
  observed_at: string | null;
  status: UsageStatus;
  reason: string;
}
export interface ProviderUsage {
  provider: "claude" | "codex";
  account_binding: string | null;
  source: string;
  received_at: string | null;
  retry_after_seconds: number;
  windows: UsageWindow[];
}
export interface Usage { providers: ProviderUsage[] }
export const getUsage = (): Promise<Usage> => api<Usage>("/v1/me/usage");
