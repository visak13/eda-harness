import { useQuery } from "@tanstack/react-query";
import { api, postJson } from "./client";
import { ROLES } from "./types";

// S14 (design-e963c656f5 §4.14(c)-(e)): the Design tab's reads and writes. The board owns the definition
// schema, the lint (Validate), the dry run and the immutable versions; the tab is a client of
// /v1/workflows* and never re-derives a rule the board enforces.

export interface Precondition {
  check: string;
  params?: Record<string, unknown>;
  when?: Record<string, unknown> | null;
  code?: string;
  message?: string;
  hint?: string;
  hook?: string | null;
  phase?: "open" | "answer" | "both";
}

export interface Transition {
  from: string;
  to: string;
  requires: Precondition[];
  auto?: boolean;
  auto_when?: Record<string, unknown> | null;
}

export interface GateDef {
  id: string;
  answerers: string[];
  requires: Precondition[];
  answer_requires?: Precondition[];
}

export type CapacityClass = "builder" | "planner" | "checker";

export interface RoleDef {
  id: string;
  label?: string;
  human?: boolean;
  card?: string;
  card_md?: string;
  model?: string | null;
  harness?: string | null;
  effort?: string | null;
  bundle?: string[] | null;
  spawnable?: boolean;
  may_spawn?: string[];
  may_create?: string[];
  criterion_author?: boolean;
  criterion_checker?: boolean;
  gate_answerer?: boolean;
  doc_types?: string[];
  capacity_class?: CapacityClass | null;
  max_concurrent?: number | null;
  kernel?: boolean;
}

export interface CheckerRule { when?: Record<string, unknown> | null; role: string }
export interface HookSetting { on: boolean; params: Record<string, unknown> }

export interface WorkflowDef {
  schema_version?: number;
  id: string;
  version: number;
  name: string;
  description: string;
  builtin: boolean;
  published: boolean;
  source?: string | null;
  roles: RoleDef[];
  kinds: string[];
  statuses: string[];
  terminal: string[];
  transitions: Transition[];
  checkers: CheckerRule[];
  caps: Record<string, number>;
  gates: GateDef[];
  permissions: Record<string, string[]>;
  hooks: Record<string, HookSetting>;
}

export interface Problem { code: string; message: string; why: string; fix: string; severity: "error" | "warning"; docs?: string }
export type WorkflowRead = WorkflowDef & { problems: Problem[] };

export interface WorkflowRow {
  id: string;
  version: number;
  ref: string;
  name: string;
  description: string;
  builtin: boolean;
  published: boolean;
  source: string | null;
  pinned_by: string[];
  roles: number;
  /** t-0c16c00424: hidden from the list until restored (only with ?archived=true). */
  archived: boolean;
  /** What Delete would do; the board says it, so the confirm never guesses. */
  delete_outcome: DeleteOutcome;
}

export interface DeleteOutcome { action: "deleted" | "archived" | "refused"; reason: string }

/** The board's rule (edp8/workflow.py `_delete_outcome`), used only when an older board left the field out. */
export function deleteOutcomeOf(r: Pick<WorkflowRow, "builtin" | "published" | "pinned_by" | "archived">): DeleteOutcome {
  const n = r.pinned_by.length;
  if (r.builtin) return { action: "refused", reason: "a built-in preset always stays" };
  if (n) return { action: "refused", reason: `pinned by ${n} epic${n === 1 ? "" : "s"}: ${r.pinned_by.join(", ")}` };
  if (r.archived) return { action: "refused", reason: "already archived; restore it instead" };
  return r.published ? { action: "archived", reason: "published: hidden from the list, restorable" }
    : { action: "deleted", reason: "an unpublished draft" };
}

export interface RoleTemplate { label: string; help: string; role: Partial<RoleDef> }
export interface Templates {
  roles: Record<string, RoleTemplate>;
  hooks: Record<string, Record<string, unknown>>;
  predicates: string[];
  kernel_tools: string[];
  why_fix: Record<string, [string, string]>;
  tool_needs: Record<string, [string, string]>;
  tools: { name: string; description: string }[];
}

export interface TimelineEvent { kind: "spawn" | "wake" | "gate" | "act" | "transition" | "stall" | "done"; step: string; who: string; text: string; by?: string; event?: string }
export interface DryRun {
  ok: boolean;
  ref: string | null;
  timeline: TimelineEvent[];
  stall: { step: string; needs: string; tried: { role: string; refusal: string }[] } | null;
}

export interface Change { path: string; op: "added" | "removed" | "changed"; before: unknown; after: unknown }
export interface Upstream { ref: string; source: string | null; latest: string | null; changed: boolean; diff: Change[] }
export interface MergeResult { draft: WorkflowDef; conflicts: { path: string; base: unknown; ours: unknown; theirs: unknown }[]; taken: string[]; problems: Problem[] }

export const refOf = (d: { id: string; version: number }) => `${d.id}@${d.version}`;

// t-b2f8859d30 (owner art-678346d6e2): a board older than this bundle answered without `pinned_by` and the Design
// page crashed on `.length`. Every list/array field a page reads is filled in here, so an older or partial board
// answer renders as "none" instead of throwing.
const arr = <T,>(v: T[] | null | undefined): T[] => (Array.isArray(v) ? v : []);
const obj = <T extends object>(v: T | null | undefined): T => (v && typeof v === "object" && !Array.isArray(v) ? v : ({} as T));

export function normaliseRow(r: Partial<WorkflowRow> & { id: string; version: number }): WorkflowRow {
  const row = {
    ...r, ref: r.ref ?? refOf(r), name: r.name ?? "", description: r.description ?? "", builtin: Boolean(r.builtin),
    published: Boolean(r.published), source: r.source ?? null, pinned_by: arr(r.pinned_by),
    roles: typeof r.roles === "number" ? r.roles : Array.isArray(r.roles) ? (r.roles as unknown[]).length : 0,
    archived: Boolean(r.archived),
  };
  return { ...row, delete_outcome: r.delete_outcome?.action ? r.delete_outcome : deleteOutcomeOf(row) };
}

export function normaliseWorkflow(d: Partial<WorkflowRead> & { id: string; version: number }): WorkflowRead {
  return {
    ...d, name: d.name ?? "", description: d.description ?? "", builtin: Boolean(d.builtin), published: Boolean(d.published),
    roles: arr(d.roles), kinds: arr(d.kinds), statuses: arr(d.statuses), terminal: arr(d.terminal),
    transitions: arr(d.transitions), checkers: arr(d.checkers), gates: arr(d.gates), problems: arr(d.problems),
    caps: obj(d.caps), permissions: obj(d.permissions), hooks: obj(d.hooks),
  };
}

const fetchWorkflows = async (archived: boolean) =>
  arr(await api<WorkflowRow[] | null>(`/v1/workflows${archived ? "?archived=true" : ""}`)).map(normaliseRow);
export const listWorkflows = () => fetchWorkflows(false);
/** t-0c16c00424: the list with archived versions too (the Design tab's Show archived). */
export const listWorkflowsWithArchived = () => fetchWorkflows(true);
export const getWorkflow = async (ref: string) =>
  normaliseWorkflow(await api<WorkflowRead>(`/v1/workflows/${encodeURIComponent(ref)}`));
export const getTemplates = () => api<Templates>("/v1/workflows/templates");
export const duplicateWorkflow = (ref: string, newId?: string) =>
  postJson<WorkflowDef>("/v1/workflows/duplicate", { ref, ...(newId ? { new_id: newId } : {}) });
export const saveWorkflow = (d: WorkflowDef) => postJson<WorkflowRead>("/v1/workflows", d, "PUT");
export const validateWorkflow = (d: WorkflowDef) =>
  postJson<{ valid: boolean; problems: Problem[] }>("/v1/workflows/validate", d);
export const dryRunWorkflow = (d: WorkflowDef) => postJson<DryRun>("/v1/workflows/dryrun", d);
export const publishWorkflow = (ref: string) => postJson<WorkflowDef>(`/v1/workflows/${encodeURIComponent(ref)}/publish`, {});
export const diffWorkflow = (against: string, definition: WorkflowDef) =>
  postJson<{ against: string; changes: Change[] }>("/v1/workflows/diff", { against, definition });
export const deleteWorkflow = (ref: string) =>
  postJson<{ ref: string; outcome: "deleted" | "archived" }>(`/v1/workflows/${encodeURIComponent(ref)}`, undefined, "DELETE");
export const restoreWorkflow = (ref: string) =>
  postJson<{ ref: string; outcome: "restored" }>(`/v1/workflows/${encodeURIComponent(ref)}/restore`, {});
export const getUpstream = (ref: string) => api<Upstream>(`/v1/workflows/${encodeURIComponent(ref)}/upstream`);
export const mergeUpstream = (ref: string) => postJson<MergeResult>(`/v1/workflows/${encodeURIComponent(ref)}/merge-upstream`, {});

/** Published versions an epic may pin, newest first per workflow (the New Epic picker). */
export function pinnable(rows: WorkflowRow[]): WorkflowRow[] {
  return rows.filter((r) => r.published).sort((a, b) =>
    Number(b.builtin && b.id === "standard") - Number(a.builtin && a.id === "standard")
    || a.id.localeCompare(b.id) || b.version - a.version);
}

/** S14 carry-over (S13 m-d6ae00b4b9): the roles of the workflow a ticket's epic pins, from the board — the
 *  static ROLES list is only the fallback while it loads or when the read fails. Humans last. */
export function useWorkflowRoles(ticketId: string | null | undefined): { roles: string[]; ref: string | null; loaded: boolean } {
  const pin = useQuery({
    queryKey: ["ticket", ticketId, "workflow"],
    queryFn: () => api<{ workflow: string }>(`/v1/tickets/${encodeURIComponent(ticketId ?? "")}?include=chain`),
    enabled: Boolean(ticketId),
    staleTime: 60_000,
    retry: false,
  });
  const ref = pin.data?.workflow ?? null;
  const wf = useQuery({
    queryKey: ["workflow", ref],
    queryFn: () => getWorkflow(ref ?? ""),
    enabled: Boolean(ref),
    staleTime: Infinity, // an epic pins a PUBLISHED version: immutable
    retry: false,
  });
  if (!wf.data) return { roles: [...ROLES], ref, loaded: false };
  return { roles: pickableRoles(wf.data.roles), ref, loaded: true };
}

/** The roles a person addresses or asks: every seat role plus the owner, without the kernel-only ones. */
export function pickableRoles(roles: RoleDef[]): string[] {
  const hidden = new Set(["expert", "doctor"]);
  const seats = roles.filter((r) => !r.human && !hidden.has(r.id)).map((r) => r.id);
  const humans = roles.filter((r) => r.human && !hidden.has(r.id)).map((r) => r.id);
  return [...seats, ...humans];
}
