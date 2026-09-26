import { api, postJson } from "./client";

// S6 (design-e963c656f5 §4.8, §4.10, §4.11, §4.14(d)): the Admin console's client over S5's /v1/admin/*
// (admin human token only). Shapes mirror the route handlers in src/edp8/admin/*.py. Every mutation
// returns the board envelope's hint; a refusal throws BoardApiError, which AdminError renders verbatim.

// ------------------------------------------------------------------------------------------ services

export interface ServiceRow {
  service: string;
  state: string;
  health?: string;
  pid?: number | null;
  port?: number | null;
  url?: string | null;
  uptime?: string | number | null;
  rev?: string | null;
  started_at?: string | null;
  last_probe?: string | null;
  last_restart_reason?: string | null;
  managed?: boolean;
  note?: string | null;
}

export interface ServicesView {
  services: ServiceRow[];
  supervisor: { running: boolean; control: boolean; error?: string };
}

export const getServices = () => api<ServicesView>("/v1/admin/services");
export const serviceAction = (svc: string, verb: "start" | "stop" | "restart", body: { force?: boolean; keep_seats?: boolean } = {}) =>
  postJson<{ service?: string; state?: string; started_at?: string | null }>(`/v1/admin/services/${encodeURIComponent(svc)}/${verb}`, body);

/** /healthz is outside the envelope: `{ok, started_at}`. */
export async function getHealthz(): Promise<{ ok: boolean; started_at: string | null }> {
  const r = await fetch("/healthz", { cache: "no-store" });
  if (!r.ok) throw new Error(`healthz ${r.status}`);
  const b = await r.json();
  return { ok: Boolean(b.ok), started_at: b.started_at ?? null };
}

// ------------------------------------------------------------------------------------------ capacity

export interface CapRow { cap: number | null; overridden: boolean; in_use: number }
export interface ClassRow extends CapRow { class: string; exempt?: boolean }
export interface RoleRow extends CapRow { role: string; capacity_class: string | null; declared_max: number | null; workflows: string[]; epics: number }
export interface CapacityView { total: CapRow; live: CapRow; classes: ClassRow[]; roles: RoleRow[]; note: string }
export interface CapacityPut {
  max_total_shells?: number;
  max_live_shells?: number;
  classes?: Record<string, number | null>;
  role_caps?: Record<string, number | null>;
  clear?: string[];
}

export const getCapacity = () => api<CapacityView>("/v1/admin/capacity");
export const putCapacity = (body: CapacityPut) => postJson<CapacityView>("/v1/admin/capacity", body, "PUT");

// ------------------------------------------------------------------------------------------ updates

export interface UpdatesView {
  current: string;
  latest: string | null;
  available: boolean;
  url: string | null;
  checked: boolean;
  apply_refusal: string | null;
  last: { request: Record<string, unknown> | null; result: { state?: string } & Record<string, unknown> | null; log: string[] };
}

export const getUpdates = () => api<UpdatesView>("/v1/admin/updates");
export const applyUpdate = (force = false) => postJson<Record<string, unknown>>("/v1/admin/updates/apply", { force });

// ------------------------------------------------------------------------------------------ models

// S12 (s-32035a77da, contract m-62fc5b54f9): the model catalog in the data dir. Every entry names its
// harness and provider explicitly (no id-prefix routing); `role_models[role][0]` is the role's default.

export interface ModelEntry {
  harness: string;
  provider: string;
  context_window?: number | null;
  auto_compact?: number | boolean | null;
  effort_cap?: string | null;
}
export interface ModelsCatalogIn { models: Record<string, ModelEntry>; role_models: Record<string, string[]> }
export interface AdminModelsView extends ModelsCatalogIn { selected: string[]; warnings: string[] }
export interface TestSpawnResult { reply: string; model: string; harness: string; provider: string }

export const getAdminModels = () => api<AdminModelsView>("/v1/admin/models");
/** Full replacement of the catalog; the board validates harness, install and provider credential. */
export const putAdminModels = (body: ModelsCatalogIn) => postJson<AdminModelsView>("/v1/admin/models", body, "PUT");
/** Run a stub prompt on a private seat of `model` for `role`. */
export const testSpawnModel = (body: { model: string; role: string; effort?: string }) =>
  postJson<TestSpawnResult>("/v1/admin/models/test-spawn", body);

// ------------------------------------------------------------------------------------------ settings

export type SettingValue = string | number | boolean | string[] | null;
export interface SettingRow {
  key: string;
  env: string;
  type: string;
  group: string;
  doc: string;
  secret: boolean;
  restart_required: string;
  env_only: boolean;
  choices: string[];
  /** t-5dd0cc18ea: basic shows by default, advanced behind "Show advanced" (internal keys are never listed) */
  tier?: "basic" | "advanced" | string;
  label?: string;
  help?: string;
  unit?: string;
  source: "env" | "config" | "default" | string;
  set: boolean;
  read_only: boolean;
  read_only_reason: string | null;
  value: SettingValue;
  default: SettingValue;
  default_doc?: string;
  error?: string;
}
export interface SettingsView { config_file: string; groups: { group: string; settings: SettingRow[] }[] }
export interface SettingsPutResult { updated: SettingRow[]; restart_required: string[] }

export const getAdminSettings = () => api<SettingsView>("/v1/admin/settings");
export const putAdminSettings = (values: Record<string, SettingValue>) =>
  postJson<SettingsPutResult>("/v1/admin/settings", { values }, "PUT");

// ------------------------------------------------------------------------------------------ teammates

export interface Teammate {
  id: string;
  handle: string;
  role: string;
  admin: boolean;
  init_human: boolean;
  has_token: boolean;
  last_seen: string | null;
  invite_expires: string | null;
}
export interface Invite { link: string; vscode_link: string; code: string; expires_at: string | null }
export interface AgentToken { handle: string; participant_id: string | null; role: string | null; model: string | null; last_seen: string | null; revoked: boolean }
export interface TailscaleKey { teammate: string; key: string; id?: string; expires?: string; ephemeral: boolean; reusable: boolean; preauthorized: boolean; tags: string[] }

export const getTeammates = () => api<Teammate[]>("/v1/admin/teammates");
export const createTeammate = (body: { handle: string; role?: string; admin?: boolean }) =>
  postJson<{ teammate: Teammate; invite: Invite }>("/v1/admin/teammates", body);
export const reinviteTeammate = (handle: string) => postJson<Invite>(`/v1/admin/teammates/${encodeURIComponent(handle)}/invite`, {});
export const setTeammateAdmin = (handle: string, admin: boolean) =>
  postJson<Teammate>(`/v1/admin/teammates/${encodeURIComponent(handle)}`, { admin }, "PUT");
export const revokeTeammate = (handle: string) => postJson<{ handle: string; revoked: boolean }>(`/v1/admin/teammates/${encodeURIComponent(handle)}/revoke`, {});
export const rotateTeammate = (handle: string) => postJson<{ handle: string; token: string }>(`/v1/admin/teammates/${encodeURIComponent(handle)}/rotate`, {});
export const getAgentTokens = () => api<AgentToken[]>("/v1/admin/tokens/agents");
export const revokeAgentToken = async (handle: string) =>
  postJson<{ handle: string; revoked: boolean }>(`/v1/admin/tokens/agents/${encodeURIComponent(handle)}`, undefined, "DELETE");
export const mintTailscaleKey = (handle: string, body: { ephemeral?: boolean; preauthorized?: boolean; expiry_s?: number; tags?: string[] } = {}) =>
  postJson<TailscaleKey>(`/v1/admin/teammates/${encodeURIComponent(handle)}/tailscale-key`, body);

// ------------------------------------------------------------------------------------------ remote

/** One readiness row (edp8.tailnet.classify): level BLOCKER|WARN|OK|INFO, the area it checks, what it found
 *  and the fix. */
export interface TailnetRow { level: string; area?: string; text?: string; fix?: string; [k: string]: unknown }
export interface TailnetView {
  tailscale: { backend?: string; dns?: string; [k: string]: unknown } | null;
  serve: unknown;
  serve_proxies: { from: string; to: string }[];
  public_url: string | null;
  tailnet_url: string | null;
  public_mode: boolean;
  rows: TailnetRow[];
  blockers: number;
  auth_keys: { configured: boolean };
  /** The mode the running board started in (null on an older board); differs from public_mode until a restart. */
  running_public?: boolean | null;
}
export const getTailnet = () => api<TailnetView>("/v1/admin/tailnet");
export const getTailnetGuide = () => api<{ name: string; path: string; html: string }>("/v1/admin/tailnet/guide");
export const applyTailnet = (force = false) => postJson<Record<string, unknown>>("/v1/admin/tailnet/apply", { force });
export const removeTailnet = () => postJson<Record<string, unknown>>("/v1/admin/tailnet/remove", {});

// ------------------------------------------------------------------------------------------ integrations

export interface SlackView {
  path: string;
  exists: boolean;
  config: Record<string, unknown>;
  bot_token_set: boolean;
  webhook_set: boolean;
  people_effective: Record<string, Record<string, unknown> & { source: string }>;
}
export interface CodeServerStatus { running: boolean; port: number; url?: string; version?: string | null; start_command?: string; [k: string]: unknown }
export interface VscodeView { extension_id: string; vsix_url: string; board_url: string; signin_links: Record<string, string> }
export interface IntegrationsView {
  slack: SlackView;
  plane: { configured: boolean; settings: SettingRow[] };
  code_server: CodeServerStatus;
  vscode: VscodeView;
}
export const getIntegrations = () => api<IntegrationsView>("/v1/admin/integrations");
export const putSlack = (values: Record<string, unknown>) => postJson<SlackView>("/v1/admin/integrations/slack", { values }, "PUT");
export const testSlack = (handle?: string) => postJson<{ sent: boolean; to: string }>("/v1/admin/integrations/slack/test", handle ? { handle } : {});
export const putPlane = (values: Record<string, SettingValue>) =>
  postJson<{ configured: boolean; settings: SettingRow[]; restart_required: string[] }>("/v1/admin/integrations/plane", { values }, "PUT");
export const testPlane = () => postJson<{ ok: boolean; message: string }>("/v1/admin/integrations/plane/test", {});
export const testCodeServer = () => postJson<CodeServerStatus>("/v1/admin/integrations/code-server/test", {});
export const testVscode = () => postJson<{ board_url: string }>("/v1/admin/integrations/vscode/test", {});

// ------------------------------------------------------------------------------------------ harnesses

export interface HarnessRow {
  harness: string;
  selected: boolean;
  installed: boolean;
  path: string | null;
  version: string | null;
  signed_in: boolean | null;
  latest: string | null;
  live_seats: string[] | null;
  update: { state: string; exit?: number | null; output?: string | null; before?: string | null; after?: string | null } | null;
}
export interface HarnessesView { harnesses: HarnessRow[]; selected: string[]; fable_ack: Record<string, unknown> | null; fable_notice: string | null }

export const getHarnesses = (latest = true) => api<HarnessesView>(`/v1/admin/harnesses?latest=${latest}`);
export const updateHarness = (h: string, wait = false) => postJson<HarnessRow["update"]>(`/v1/admin/harnesses/${encodeURIComponent(h)}/update`, { wait });
export const putHarnessSelection = (harnesses: string[], fable_ack = false) =>
  postJson<{ selected: string[]; fable_ack: Record<string, unknown> | null; restart_required: string[] }>("/v1/admin/harnesses/selection", { harnesses, fable_ack }, "PUT");

// ------------------------------------------------------------------------------------------ setup / join

export interface SetupState { done: boolean; at?: string | null; by?: string | null }
export const getSetup = () => api<SetupState>("/v1/admin/setup");
export const finishSetup = () => postJson<SetupState>("/v1/admin/setup/done", {});

/** The invite redeem (no credential: the one-time code is it). */
export const redeemInvite = (code: string) => postJson<{ handle: string; token: string; board_url: string }>("/v1/join", { code });
