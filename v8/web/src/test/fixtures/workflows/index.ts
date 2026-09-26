import { http, HttpResponse } from "msw";
import type { DryRun, Templates, WorkflowRead, WorkflowRow } from "../../../api/workflows";
import dryrunStallJson from "./dryrun-stall.json";
import dryrunStandardJson from "./dryrun-standard.json";
import invalidJson from "./invalid.json";
import leanJson from "./lean.json";
import soloJson from "./solo.json";
import standardJson from "./standard.json";
import templatesJson from "./templates.json";

// S14: board-generated workflow fixtures (GET /v1/workflows/<ref>, /templates, POST /dryrun on a scratch
// board) and one msw handler set over them, shared by the Design tab's unit tests and the dead-control walk.

export const STANDARD = standardJson as unknown as WorkflowRead;
export const LEAN = leanJson as unknown as WorkflowRead;
export const SOLO = soloJson as unknown as WorkflowRead;
/** A draft copy of Standard with planted errors: role_without_spawner, card_missing, bundle_missing, self_check, cap_below_1. */
export const INVALID = invalidJson as unknown as WorkflowRead;
export const TEMPLATES = templatesJson as unknown as Templates;
export const DRYRUN_OK = dryrunStandardJson as unknown as DryRun;
/** A dry run that stalls at "epic → done". */
export const DRYRUN_STALL = dryrunStallJson as unknown as DryRun;

const ok = (value: unknown, hint = "") => HttpResponse.json({ ok: true, value, hint });

export function rowOf(d: WorkflowRead, pinnedBy: string[] = []): WorkflowRow {
  return {
    id: d.id, version: d.version, ref: `${d.id}@${d.version}`, name: d.name, description: d.description,
    builtin: d.builtin, published: d.published, source: d.source ?? null, pinned_by: pinnedBy, roles: d.roles.length,
  };
}

export const WORKFLOWS: Record<string, WorkflowRead> = {
  "standard@1": STANDARD, "lean@1": LEAN, "solo@1": SOLO, "broken@1": INVALID,
};

/** Handlers for the read side of /v1/workflows*; tests add their own for writes. */
export function workflowHandlers(extra: Record<string, WorkflowRead> = {}, pins: Record<string, string[]> = { "standard@1": ["epic-1"] }) {
  const all = { ...WORKFLOWS, ...extra };
  return [
    http.get("/v1/workflows", () => ok(Object.values(all).map((d) => rowOf(d, pins[`${d.id}@${d.version}`] ?? [])))),
    http.get("/v1/workflows/templates", () => ok(TEMPLATES)),
    http.get("/v1/workflows/:ref/upstream", ({ params }) =>
      ok({ ref: params.ref, source: all[params.ref as string]?.source ?? null, latest: null, changed: false, diff: [] })),
    http.get("/v1/workflows/:ref/card/:role", ({ params }) =>
      ok({ role: params.role, name: `${params.role}.md`, source: "shipped", markdown: `# ${params.role}\n\nThe shipped card.`,
        html: `<h1>${params.role}</h1><p>The shipped card.</p>`, kernel_preamble: "Boot: whoami, subscribe, context." })),
    http.post("/v1/workflows/card-preview", async ({ request }) => {
      const b = (await request.json()) as { card_md: string };
      return ok({ html: `<p>${b.card_md}</p>`, kernel_preamble: "Boot: whoami, subscribe, context." });
    }),
    http.get("/v1/workflows/:ref", ({ params }) => {
      const d = all[params.ref as string];
      return d ? ok(d) : HttpResponse.json({ ok: false, error: { code: "not_found", message: `no workflow ${params.ref}` } }, { status: 404 });
    }),
  ];
}
