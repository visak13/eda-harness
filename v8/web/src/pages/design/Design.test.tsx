import { describe, it, expect, vi } from "vitest";
import { useState } from "react";
import { render, screen, waitFor, within, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../../test/setup";
import { MODEL_CATALOG } from "../../test/handlers";
import {
  DRYRUN_OK, DRYRUN_STALL, INVALID, LEAN, SOLO, STANDARD, TEMPLATES, rowOf, workflowHandlers,
} from "../../test/fixtures/workflows";
import type { ModelCatalog } from "../../api/types";
import { pickableRoles, pinnable, type WorkflowDef } from "../../api/workflows";
import { renderRoute } from "../testUtils";
import { DesignPage } from "./Design";
import { WorkflowList } from "./WorkflowList";
import { PipelineView } from "./PipelineView";
import { RolePanel } from "./RolePanel";
import { CapsPanel, CheckersPanel, GatesPanel, HooksPanel } from "./PolicyPanels";
import { DryRunPanel, PublishSummary, UpstreamBanner, ValidatePanel } from "./CheckPanels";
import { CAP_HELP, CAP_LABEL, DESIGN_SCOPE, HOOK_HELP, HOOK_LABEL, PANELS, bodyOf, panelFor, panelOf, roleLayers, rolesWithErrors } from "./model";
import { statusOf, summaryOf } from "./WorkflowList";

// S14 (c-113c3070c7, c-e9d095f3a3, c-faeeb32860): every Design panel against the board-generated fixtures
// (Standard, Lean, Solo and a planted-invalid draft), then the page's admin flow and its read-only view.

const ok = (value: unknown, hint = "") => HttpResponse.json({ ok: true, value, hint });
const whoami = (admin: boolean) => http.get("/v1/whoami", () => ok({
  participant: { id: "owner", handle: "owner", role: "owner", type: "human", admin }, admin, tickets: [],
}));

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

/** A panel with its own draft state, so an edit re-renders like it does on the page. */
function Editable({ start, children }: { start: WorkflowDef; children: (wf: WorkflowDef, set: (w: WorkflowDef) => void) => React.ReactNode }) {
  const [wf, setWf] = useState(start);
  return <>{children(wf, setWf)}<pre data-testid="draft-json">{JSON.stringify(wf)}</pre></>;
}
const draftOf = () => JSON.parse(screen.getByTestId("draft-json").textContent ?? "{}") as WorkflowDef;
const DRAFT: WorkflowDef = { ...bodyOf(STANDARD), id: "team", version: 1, builtin: false, published: false, source: "standard@1" };

describe("workflow list", () => {
  it("groups presets and custom versions with state, source and pins; Duplicate only for an admin", async () => {
    const rows = [rowOf(STANDARD, ["epic-1", "epic-2"]), rowOf(LEAN), rowOf(SOLO), rowOf(INVALID)];
    const onDup = vi.fn();
    const { rerender } = wrap(<WorkflowList rows={rows} selected="standard@1" canEdit onSelect={() => {}} onDuplicate={onDup} pending={false} />);
    expect(within(screen.getByTestId("wf-presets")).getAllByRole("listitem")).toHaveLength(3);
    expect(within(screen.getByTestId("wf-custom")).getByTestId("wf-row-broken@1")).toHaveTextContent(/draft/);
    expect(screen.getByTestId("wf-row-broken@1")).toHaveTextContent("from standard@1");
    expect(screen.getByTestId("wf-pins-standard@1")).toHaveTextContent("pinned by 2 epics: epic-1, epic-2");
    expect(screen.getByTestId("wf-pins-lean@1")).toHaveTextContent("no epic pins it");
    expect(screen.getByTestId("wf-row-standard@1")).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByTestId("wf-duplicate-lean@1"));
    expect(onDup).toHaveBeenCalledWith("lean@1");
    rerender(<QueryClientProvider client={new QueryClient()}><WorkflowList rows={rows} selected={null} canEdit={false} onSelect={() => {}} onDuplicate={onDup} pending={false} /></QueryClientProvider>);
    expect(screen.queryByTestId("wf-duplicate-lean@1")).toBeNull();
  });

  it("the New Epic picker lists published versions only, Standard first", () => {
    const rows = [rowOf(LEAN), rowOf(INVALID), rowOf(SOLO), rowOf(STANDARD)];
    expect(pinnable(rows).map((r) => r.ref)).toEqual(["standard@1", "lean@1", "solo@1"]);
  });
});

describe("pipeline view", () => {
  it("shows Standard faithfully: spawn edges, qa checks the builders, the design_signoff gate on designed→signed_off", async () => {
    wrap(<PipelineView wf={STANDARD} />);
    for (const id of ["owner", "architect", "engineer", "sme", "adversary", "qa"]) expect(screen.getByTestId(`role-node-${id}`)).toBeInTheDocument();
    expect(screen.getByTestId("spawn-edge-owner-architect")).toBeInTheDocument();
    expect(screen.getByTestId("spawn-edge-architect-engineer")).toBeInTheDocument();
    expect(screen.getByTestId("check-edge-qa-engineer")).toBeInTheDocument();
    expect(screen.getByTestId("flow-gate-design_signoff")).toBeInTheDocument();
    expect(screen.getByTestId("flow-gate-acceptance")).toBeInTheDocument();
    expect(screen.getByTestId("pipeline-idle")).toHaveTextContent("expert");
    fireEvent.click(screen.getByTestId("flow-edge-designed-signed_off"));
    expect(screen.getByTestId("flow-edge-detail")).toHaveTextContent("designed → signed off");
  });

  it("Lean and Solo draw only their roles; the owner checks in Solo", () => {
    const { unmount } = wrap(<PipelineView wf={LEAN} />);
    expect(screen.queryByTestId("role-node-architect")).toBeNull();
    expect(screen.getByTestId("spawn-edge-owner-engineer")).toBeInTheDocument();
    expect(screen.getByTestId("check-edge-qa-engineer")).toBeInTheDocument();
    unmount();
    wrap(<PipelineView wf={SOLO} />);
    expect(screen.getByTestId("check-edge-owner-engineer")).toBeInTheDocument();
    expect(screen.queryByTestId("role-node-qa")).toBeNull();
  });

  it("an unreachable role in the invalid draft is drawn apart as 'no spawner'", () => {
    expect(roleLayers(INVALID).unreached).toContain("designer");
    wrap(<PipelineView wf={INVALID} />);
    expect(screen.getByTestId("role-node-designer")).toHaveTextContent("no spawner");
    expect(screen.getByTestId("pipeline-unreached")).toHaveTextContent("designer");
  });
});

describe("role panel", () => {
  const props = { savedRef: "team@1", templates: TEMPLATES, catalog: MODEL_CATALOG as unknown as ModelCatalog, errorRoles: new Set<string>() };

  it("model from the S12 catalog sets the harness and caps the effort; tools keep kernel tools locked", async () => {
    server.use(...workflowHandlers());
    wrap(<Editable start={DRAFT}>{(wf, set) => (
      <RolePanel {...props} wf={wf} editable selected="engineer" onSelect={() => {}} onChange={set} />
    )}</Editable>);
    const form = await screen.findByTestId("role-form-engineer");
    fireEvent.change(within(form).getByTestId("role-model"), { target: { value: "gpt-6-sol" } });
    const eng = draftOf().roles.find((r) => r.id === "engineer")!;
    expect(eng.model).toBe("gpt-6-sol");
    expect(eng.harness).toBe("codex");
    expect(within(form).getByTestId("role-harness")).toHaveTextContent(/codex/);
    const kernelTool = TEMPLATES.kernel_tools[0];
    expect(within(form).getByTestId(`role-tool-${kernelTool}`)).toBeDisabled();
    expect(within(form).getByTestId(`role-tool-${kernelTool}`)).toBeChecked();
  });

  it("the card editor forks the shipped card and previews the markdown through the board", async () => {
    server.use(...workflowHandlers());
    wrap(<Editable start={DRAFT}>{(wf, set) => (
      <RolePanel {...props} wf={wf} editable selected="qa" onSelect={() => {}} onChange={set} />
    )}</Editable>);
    fireEvent.click(await screen.findByTestId("role-card-fork"));
    expect(draftOf().roles.find((r) => r.id === "qa")!.card_md).toContain("The shipped card.");
    fireEvent.change(screen.getByTestId("role-card"), { target: { value: "Check **everything**." } });
    await waitFor(() => expect(screen.getByTestId("role-card-preview")).toHaveTextContent("Check **everything**."), { timeout: 3000 });
    expect(screen.getByTestId("role-card-kernel")).toHaveTextContent("Boot");
  });

  it("Add role from the reviewer template: id, label and spawner land in the draft", async () => {
    server.use(...workflowHandlers());
    wrap(<Editable start={DRAFT}>{(wf, set) => (
      <RolePanel {...props} wf={wf} editable selected={null} onSelect={() => {}} onChange={set} />
    )}</Editable>);
    fireEvent.click(screen.getByTestId("role-add-open"));
    fireEvent.change(screen.getByTestId("role-add-template"), { target: { value: "reviewer" } });
    fireEvent.change(screen.getByTestId("role-add-id"), { target: { value: "reviewer" } });
    fireEvent.change(screen.getByTestId("role-add-label"), { target: { value: "Reviewer" } });
    fireEvent.change(screen.getByTestId("role-add-spawner"), { target: { value: "architect" } });
    fireEvent.click(screen.getByTestId("role-add-save"));
    const d = draftOf();
    const r = d.roles.find((x) => x.id === "reviewer")!;
    expect(r.label).toBe("Reviewer");
    expect(r.card_md).toBeTruthy();
    expect(r.capacity_class).toBe("checker");
    expect(r.bundle).toContain("doc_create");
    expect(d.roles.find((x) => x.id === "architect")!.may_spawn).toContain("reviewer");
  });

  it("read-only: every control is disabled and there is no Add role", () => {
    server.use(...workflowHandlers());
    wrap(<RolePanel {...props} wf={STANDARD} editable={false} selected="engineer" onSelect={() => {}} onChange={() => {}} />);
    expect(screen.queryByTestId("role-add-open")).toBeNull();
    expect(screen.getByTestId("role-model")).toBeDisabled();
    expect(screen.getByTestId("role-label")).toBeDisabled();
  });
});

describe("hooks, gates and caps", () => {
  it("toggles a hook and edits its role param; every hook carries its one-line help", async () => {
    wrap(<Editable start={DRAFT}>{(wf, set) => <HooksPanel wf={wf} editable onChange={set} templates={TEMPLATES} />}</Editable>);
    const before = DRAFT.hooks.review_story_last.on;
    fireEvent.click(screen.getByTestId("hook-toggle-review_story_last"));
    expect(draftOf().hooks.review_story_last.on).toBe(!before);
    expect(screen.getByTestId("hook-criteria_auto_done")).toHaveTextContent(/becomes done once every criterion passed/);
    fireEvent.change(screen.getByTestId("hook-param-criteria_auto_done-epic_checker"), { target: { value: "owner" } });
    expect(draftOf().hooks.criteria_auto_done.params.epic_checker).toBe("owner");
  });

  it("gates: answerers are checkboxes; dropping every human flags the gate", async () => {
    wrap(<Editable start={DRAFT}>{(wf, set) => <GatesPanel wf={wf} editable onChange={set} />}</Editable>);
    expect(screen.getByTestId("gate-design_signoff")).toHaveTextContent("between designed and signed off");
    expect(screen.getByTestId("gate-design_signoff")).toHaveTextContent("Design sign-off"); // plain name, key kept small
    fireEvent.click(screen.getByTestId("gate-answerer-design_signoff-owner"));
    expect(draftOf().gates.find((g) => g.id === "design_signoff")!.answerers).not.toContain("owner");
    expect(screen.getByTestId("gate-design_signoff")).toHaveTextContent("no human answers it");
  });

  it("caps: a number per cap with its explanation", async () => {
    wrap(<Editable start={DRAFT}>{(wf, set) => <CapsPanel wf={wf} editable onChange={set} />}</Editable>);
    fireEvent.change(screen.getByTestId("cap-stories_per_epic"), { target: { value: "12" } });
    expect(draftOf().caps.stories_per_epic).toBe(12);
    expect(screen.getByTestId("design-caps")).toHaveTextContent(/Open stories one epic may hold/);
  });
});

describe("validate and dry run", () => {
  it("lists the invalid draft's planted errors inline, each linked to the panel that fixes it", async () => {
    const onGo = vi.fn();
    wrap(<ValidatePanel problems={INVALID.problems} ran onGo={onGo} />);
    expect(screen.getByTestId("validate-errors")).toHaveTextContent("5 errors block Publish");
    for (const code of ["role_without_spawner", "card_missing", "bundle_missing", "self_check", "cap_below_1"]) {
      expect(screen.getByTestId(`problem-${code}`)).toBeInTheDocument();
    }
    fireEvent.click(screen.getByTestId("problem-go-card_missing"));
    expect(onGo).toHaveBeenLastCalledWith("roles", "designer", "card");
    expect(panelFor(INVALID.problems.find((p) => p.code === "cap_below_1")!).panel).toBe("policy");
    expect([...rolesWithErrors(INVALID.problems)]).toContain("designer");
  });

  it("the dry run timeline shows spawns and gates; a stall names the step and who was tried", async () => {
    const { rerender } = wrap(<DryRunPanel run={DRYRUN_OK} pending={false} error={null} onRun={() => {}} />);
    expect(screen.getByTestId("dryrun-ok")).toBeInTheDocument();
    expect(screen.getByTestId("dryrun-timeline").querySelector('[data-kind="spawn"]')).not.toBeNull();
    expect(screen.getByTestId("dryrun-timeline").querySelector('[data-kind="gate"]')).not.toBeNull();
    rerender(<QueryClientProvider client={new QueryClient()}><DryRunPanel run={DRYRUN_STALL} pending={false} error={null} onRun={() => {}} /></QueryClientProvider>);
    expect(screen.getByTestId("dryrun-stall")).toHaveTextContent(`Stalls at “${DRYRUN_STALL.stall!.step}”`);
    expect(screen.getByTestId("dryrun-stall")).toHaveTextContent(DRYRUN_STALL.stall!.tried[0].role);
  });
});

describe("upstream changed", () => {
  it("shows the three-way diff and merges into a new draft, listing conflicts", async () => {
    const onMerged = vi.fn();
    server.use(
      http.get("/v1/workflows/:ref/upstream", () => ok({ ref: "team@1", source: "standard@1", latest: "standard@2", changed: true,
        diff: [{ path: "caps.stories_per_epic", op: "changed", before: 8, after: 10 }] })),
      http.post("/v1/workflows/:ref/merge-upstream", () => ok({
        draft: { ...DRAFT, version: 2, source: "standard@2" }, taken: [],
        conflicts: [{ path: "caps.stories_per_epic", base: 8, ours: 9, theirs: 10 }], problems: [] })),
    );
    wrap(<UpstreamBanner refStr="team@1" canEdit onMerged={onMerged} />);
    expect(await screen.findByTestId("upstream-banner")).toHaveTextContent("standard@1 → standard@2");
    fireEvent.click(screen.getByTestId("upstream-show"));
    expect(screen.getByTestId("upstream-diff")).toHaveTextContent("caps.stories_per_epic");
    fireEvent.click(screen.getByTestId("upstream-merge"));
    expect(await screen.findByTestId("upstream-merged")).toHaveTextContent("team@2");
    expect(screen.getByTestId("upstream-conflicts")).toHaveTextContent("caps.stories_per_epic");
    expect(onMerged).toHaveBeenCalled();
  });
});

describe("Design page", () => {
  it("renders when an older board leaves out pinned_by and other fields (t-b2f8859d30)", async () => {
    // art-678346d6e2: "can't access property 'length', e.pinned_by is undefined". The rows and the workflow come back
    // without pinned_by, source, roles-count and most arrays; the page lists them as unpinned instead of crashing.
    const { pinned_by: _p, source: _s, roles: _r, ...bare } = rowOf(STANDARD);
    void _p; void _s; void _r;
    const { transitions: _t, gates: _g, checkers: _c, problems: _pr, hooks: _h, caps: _cp, ...wf } = STANDARD;
    void _t; void _g; void _c; void _pr; void _h; void _cp;
    server.use(whoami(false), http.get("/v1/workflows", () => ok([bare])), http.get("/v1/workflows/:ref", () => ok(wf)),
      ...workflowHandlers()); // msw: the first matching handler wins
    renderRoute("/design", "/design", <DesignPage />);
    expect(await screen.findByTestId("wf-pins-standard@1")).toHaveTextContent("no epic pins it");
    expect(await screen.findByTestId("pipeline-roles")).toBeInTheDocument();
    expect(screen.getByTestId("design-title")).toHaveTextContent("standard@1");
  });

  it("a non-admin reads every version read-only: no Duplicate, no Publish", async () => {
    server.use(whoami(false), ...workflowHandlers());
    renderRoute("/design", "/design", <DesignPage />);
    expect(await screen.findByTestId("design-readonly")).toBeInTheDocument();
    expect(await screen.findByTestId("pipeline-roles")).toBeInTheDocument();
    expect(screen.getByTestId("design-title")).toHaveTextContent("standard@1");
    expect(screen.queryByTestId("design-publish")).toBeNull();
    expect(screen.queryByTestId("design-duplicate")).toBeNull();
    expect(screen.queryByTestId("wf-duplicate-standard@1")).toBeNull();
  });

  it("an admin duplicates a preset under a new id and lands on the draft", async () => {
    let body: unknown = null;
    const team = { ...STANDARD, ...DRAFT, problems: [] };
    server.use(whoami(true), ...workflowHandlers({ "team@1": team }),
      http.post("/v1/workflows/duplicate", async ({ request }) => { body = await request.json(); return ok(DRAFT); }));
    renderRoute("/design", "/design", <DesignPage />);
    fireEvent.click(await screen.findByTestId("design-duplicate"));
    const id = screen.getByTestId("duplicate-id");
    fireEvent.change(id, { target: { value: "team" } });
    fireEvent.click(screen.getByTestId("duplicate-submit"));
    await waitFor(() => expect(body).toEqual({ ref: "standard@1", new_id: "team" }));
    expect(await screen.findByTestId("design-done")).toHaveTextContent("Draft team@1 created from standard@1");
    expect(await screen.findByTestId("design-publish")).toBeInTheDocument();
  });

  it("Publish stops on a validation error (the dry-run stall), opens Validate and links it to the Dry run panel", async () => {
    const team = { ...STANDARD, ...DRAFT, problems: [] };
    const publish = vi.fn();
    server.use(whoami(true), ...workflowHandlers({ "team@1": team }),
      http.put("/v1/workflows", async ({ request }) => ok({ ...(await request.json() as object), problems: [] })),
      http.post("/v1/workflows/validate", () => ok({ valid: false, problems: [
        { code: "dry_run_stall", severity: "error", message: "the dry run stalls at 'epic → done': needs an epic checker", why: "w", fix: "f" }] })),
      http.post("/v1/workflows/dryrun", () => ok(DRYRUN_STALL)),
      http.post("/v1/workflows/:ref/publish", () => { publish(); return ok(team); }),
    );
    renderRoute("/design?wf=team@1&panel=caps", "/design", <DesignPage />);
    fireEvent.change(await screen.findByTestId("cap-stories_per_epic"), { target: { value: "3" } });
    expect(screen.getByTestId("design-state")).toHaveTextContent("unsaved");
    fireEvent.click(screen.getByTestId("design-publish"));
    expect(await screen.findByTestId("problem-dry_run_stall")).toBeInTheDocument();
    expect(publish).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("problem-go-dry_run_stall"));
    fireEvent.click(await screen.findByTestId("dryrun-run"));
    expect(await screen.findByTestId("dryrun-stall")).toBeInTheDocument();
  });
});

describe("carry-over: roles from the pinned workflow", () => {
  it("pickableRoles keeps seat roles then humans, never expert or doctor", () => {
    expect(pickableRoles(STANDARD.roles)).toEqual(["architect", "sme", "engineer", "adversary", "qa", "owner"]);
    expect(pickableRoles(SOLO.roles)).toEqual(["engineer", "owner"]);
  });
});

// ---- t-0c16c00424: delete/archive, and readable like Admin ------------------------------------------------

const PUBLISHED_TEAM = { ...STANDARD, ...DRAFT, published: true, problems: [] };

describe("t-0c16c00424 list: status in words, one-line summary, preset badge", () => {
  it("says draft / published / in use by N epics, with a summary line and a preset badge", () => {
    const team = { ...STANDARD, ...DRAFT, description: "" };
    const rows = [rowOf(STANDARD, ["epic-1", "epic-2"]), rowOf(LEAN), rowOf(team), rowOf({ ...PUBLISHED_TEAM, id: "crew", name: "Crew" })];
    wrap(<WorkflowList rows={rows} selected={null} canEdit onSelect={() => {}} onDuplicate={() => {}} onDelete={() => {}} pending={false} />);
    expect(screen.getByTestId("wf-status-standard@1")).toHaveTextContent("in use by 2 epics");
    expect(screen.getByTestId("wf-status-lean@1")).toHaveTextContent(/^published$/);
    expect(screen.getByTestId("wf-status-team@1")).toHaveTextContent(/^draft$/);
    expect(screen.getByTestId("wf-status-crew@1")).toHaveTextContent(/^published$/);
    expect(screen.getByTestId("wf-preset-standard@1")).toHaveTextContent("preset");
    expect(screen.queryByTestId("wf-preset-team@1")).toBeNull();
    expect(screen.getByTestId("wf-summary-lean@1")).toHaveTextContent(LEAN.description);
    expect(screen.getByTestId("wf-summary-team@1")).toHaveTextContent(`${STANDARD.roles.length} roles, copied from standard@1.`);
    // Delete sits beside Duplicate on your own workflows only; a preset has no Delete
    expect(screen.getByTestId("wf-delete-team@1")).toBeInTheDocument();
    expect(screen.getByTestId("wf-duplicate-team@1")).toBeInTheDocument();
    expect(screen.queryByTestId("wf-delete-standard@1")).toBeNull();
    expect(statusOf({ ...rowOf(LEAN), archived: true }).text).toBe("archived");
    expect(summaryOf({ ...rowOf(team), roles: 1, source: null })).toBe("1 role.");
  });

  it("empty states say what to do next, for an admin and for a reader", () => {
    const { rerender } = wrap(<WorkflowList rows={[rowOf(STANDARD)]} selected={null} canEdit onSelect={() => {}} onDuplicate={() => {}} pending={false} />);
    expect(screen.getByTestId("wf-custom-empty")).toHaveTextContent("Press Duplicate to edit on a preset");
    rerender(<QueryClientProvider client={new QueryClient()}><WorkflowList rows={[rowOf(STANDARD)]} selected={null} canEdit={false} onSelect={() => {}} onDuplicate={() => {}} pending={false} /></QueryClientProvider>);
    expect(screen.getByTestId("wf-custom-empty")).toHaveTextContent("An admin makes one by duplicating a preset");
    rerender(<QueryClientProvider client={new QueryClient()}><WorkflowList rows={[]} selected={null} canEdit={false} onSelect={() => {}} onDuplicate={() => {}} pending={false} /></QueryClientProvider>);
    expect(screen.getByTestId("wf-presets-empty")).toHaveTextContent("Reload the page");
  });

  it("gates, checkers and hooks each say what to do when empty", () => {
    const bare = { ...DRAFT, gates: [], checkers: [], hooks: {} };
    wrap(<>
      <GatesPanel wf={bare} editable onChange={() => {}} />
      <CheckersPanel wf={bare} />
      <HooksPanel wf={bare} editable onChange={() => {}} templates={undefined} />
    </>);
    expect(screen.getByTestId("gates-empty")).toHaveTextContent("duplicate a preset that has the gate you want");
    expect(screen.getByTestId("checkers-empty")).toHaveTextContent("Give a role");
    expect(screen.getByTestId("hooks-empty")).toHaveTextContent("Reload the page");
  });

  it("every hook and cap field reads in plain words with a hint line; the key stays visible", () => {
    wrap(<>
      <HooksPanel wf={DRAFT} editable={false} onChange={() => {}} templates={TEMPLATES} />
      <CapsPanel wf={DRAFT} editable={false} onChange={() => {}} />
    </>);
    const hook = screen.getByTestId("hook-epic_auto_advance");
    expect(hook).toHaveTextContent("Move epics forward on their own");
    expect(hook).toHaveTextContent("epic_auto_advance");
    for (const name of Object.keys(TEMPLATES.hooks)) {
      expect(screen.getByTestId(`hook-${name}`)).toHaveTextContent(HOOK_HELP[name]); // a hint line for every hook
      expect(HOOK_LABEL[name]).toBeTruthy(); // and a plain name
    }
    for (const k of Object.keys(DRAFT.caps)) expect(CAP_HELP[k] && CAP_LABEL[k]).toBeTruthy();
    expect(screen.getByTestId("design-caps")).toHaveTextContent("Stories per epic");
    expect(screen.getByTestId("design-caps")).not.toHaveTextContent("stories per epic"); // not the raw key with spaces
  });
});

describe("t-0c16c00424 sections in the order a person works", () => {
  it("Overview → Roles → Checks and gates → Hooks and caps → Validate and publish; old links still land", () => {
    expect(PANELS.map((p) => p.label)).toEqual(["Overview", "Roles", "Checks and gates", "Hooks and caps", "Validate and publish"]);
    expect(PANELS.every((p) => p.hint.length > 20)).toBe(true);
    expect(["pipeline", "gates", "hooks", "caps", "validate", "dryrun", "diff", null, "nope"].map(panelOf))
      .toEqual(["overview", "checks", "policy", "policy", "publish", "publish", "publish", "overview", "overview"]);
  });

  it("the page opens with the one-line header and renders the tabs in that order", async () => {
    server.use(whoami(false), ...workflowHandlers());
    renderRoute("/design", "/design", <DesignPage />);
    expect(await screen.findByText(DESIGN_SCOPE)).toBeInTheDocument();
    expect(DESIGN_SCOPE).toMatch(/^A workflow is /);
    const tabs = await screen.findAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["Overview", "Roles", "Checks and gates", "Hooks and caps", "Validate and publish"]);
    expect(screen.getByTestId("design-section-hint")).toHaveTextContent(PANELS[0].hint);
    fireEvent.click(tabs[2]);
    expect(await screen.findByTestId("design-checkers")).toBeInTheDocument();
    expect(screen.getByTestId("design-gates")).toBeInTheDocument();
    fireEvent.click(tabs[3]);
    expect(await screen.findByTestId("design-hooks")).toBeInTheDocument();
    expect(screen.getByTestId("design-caps")).toBeInTheDocument();
    fireEvent.click(tabs[4]);
    expect(await screen.findByTestId("design-validate")).toBeInTheDocument();
    expect(screen.getByTestId("design-dryrun")).toBeInTheDocument();
    expect(screen.getByTestId("design-diff")).toBeInTheDocument();
    expect(screen.getByTestId("design-publish-summary")).toBeInTheDocument();
  });

  it("Publish names the epics it leaves unaffected", () => {
    const rows = [rowOf(STANDARD, ["epic-1", "epic-2"]), rowOf(LEAN, ["epic-3"]), rowOf({ ...STANDARD, ...DRAFT, problems: [] })];
    const onPublish = vi.fn();
    wrap(<PublishSummary wf={DRAFT} rows={rows} editable errors={null} pending={false} onPublish={onPublish} />);
    expect(screen.getByTestId("publish-unaffected")).toHaveTextContent("Unaffected: 3 running epics keep the version they started on — 2 on standard@1, 1 on lean@1.");
    fireEvent.click(screen.getByTestId("publish-step-run"));
    expect(onPublish).toHaveBeenCalled();
  });
});

describe("t-0c16c00424 Delete + confirm", () => {
  const withRows = (rows: ReturnType<typeof rowOf>[], extra: Record<string, typeof STANDARD> = {}) => {
    const deleted: string[] = [];
    server.use(whoami(true),
      http.get("/v1/workflows", () => ok(rows)),
      http.delete("/v1/workflows/:ref", ({ params }) => {
        deleted.push(params.ref as string);
        const r = rows.find((x) => x.ref === params.ref)!;
        return ok({ ref: r.ref, outcome: r.published ? "archived" : "deleted" });
      }),
      ...workflowHandlers(extra));
    return deleted;
  };

  it("a draft: the confirm says it is removed for good, and Delete draft calls DELETE", async () => {
    const team = { ...STANDARD, ...DRAFT, problems: [] };
    const deleted = withRows([rowOf(STANDARD), rowOf(team)], { "team@1": team });
    renderRoute("/design", "/design", <DesignPage />);
    fireEvent.click(await screen.findByTestId("wf-delete-team@1"));
    const c = screen.getByTestId("delete-confirm");
    expect(c).toHaveAttribute("data-outcome", "deleted");
    expect(c).toHaveTextContent("Delete draft team@1?");
    expect(c).toHaveTextContent("removed for good");
    fireEvent.click(screen.getByTestId("delete-confirm-run"));
    await waitFor(() => expect(deleted).toEqual(["team@1"]));
    expect(await screen.findByTestId("design-done")).toHaveTextContent("Draft team@1 is deleted.");
  });

  it("an unpinned published version: the confirm says Archive and how to restore", async () => {
    const deleted = withRows([rowOf(STANDARD), rowOf(PUBLISHED_TEAM)], { "team@1": PUBLISHED_TEAM });
    renderRoute("/design", "/design", <DesignPage />);
    fireEvent.click(await screen.findByTestId("wf-delete-team@1"));
    const c = screen.getByTestId("delete-confirm");
    expect(c).toHaveAttribute("data-outcome", "archived");
    expect(c).toHaveTextContent("Archive team@1?");
    expect(c).toHaveTextContent("Show archived versions brings it back");
    fireEvent.click(screen.getByTestId("delete-confirm-run"));
    await waitFor(() => expect(deleted).toEqual(["team@1"]));
    expect(await screen.findByTestId("design-done")).toHaveTextContent("team@1 is archived");
  });

  it("a pinned version: the confirm refuses, names the epics and offers only Close", async () => {
    const deleted = withRows([rowOf(STANDARD), rowOf(PUBLISHED_TEAM, ["epic-9", "epic-10"])], { "team@1": PUBLISHED_TEAM });
    renderRoute("/design", "/design", <DesignPage />);
    fireEvent.click(await screen.findByTestId("wf-delete-team@1"));
    const c = screen.getByTestId("delete-confirm");
    expect(c).toHaveAttribute("data-outcome", "refused");
    expect(c).toHaveTextContent("team@1 can’t be deleted");
    expect(c).toHaveTextContent("pinned by 2 epics: epic-9, epic-10");
    expect(screen.queryByTestId("delete-confirm-run")).toBeNull();
    fireEvent.click(screen.getByTestId("delete-confirm-cancel"));
    expect(screen.queryByTestId("delete-confirm")).toBeNull();
    expect(deleted).toEqual([]);
  });

  it("a reader sees no Delete; Show archived lists archived versions with Restore for an admin", async () => {
    const restored: string[] = [];
    const arch = rowOf(PUBLISHED_TEAM, [], true);
    server.use(whoami(true),
      http.get("/v1/workflows", ({ request }) => ok(new URL(request.url).searchParams.get("archived") ? [rowOf(STANDARD), arch] : [rowOf(STANDARD)])),
      http.post("/v1/workflows/:ref/restore", ({ params }) => { restored.push(params.ref as string); return ok({ ref: params.ref, outcome: "restored" }); }),
      ...workflowHandlers({ "team@1": PUBLISHED_TEAM }));
    renderRoute("/design", "/design", <DesignPage />);
    expect(await screen.findByTestId("wf-row-standard@1")).toBeInTheDocument();
    expect(screen.queryByTestId("wf-row-team@1")).toBeNull();
    fireEvent.click(screen.getByTestId("wf-show-archived"));
    expect(await screen.findByTestId("wf-status-team@1")).toHaveTextContent("archived");
    fireEvent.click(screen.getByTestId("wf-restore-team@1"));
    await waitFor(() => expect(restored).toEqual(["team@1"]));
  });
});
