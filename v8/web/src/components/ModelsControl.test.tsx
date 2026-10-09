import { describe, it, expect } from "vitest";
import { screen, fireEvent, waitFor, within } from "@testing-library/react";
import { server } from "../test/setup";
import { http, okJson, renderRoute } from "../pages/testUtils";
import { ModelsControl } from "./ModelsControl";
import { Drawer } from "./Drawer";
import ui from "./ui.module.css";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// S7 (design-b6a55eed13 §4.E): the Models tab edits each role's ORDERED option list and each story's pick
// among them; a change says "applies to the next spawn" and writes tags only — it never touches a live seat.

const CATALOG = {
  roles: { architect: ["claude-fable-5-1"], engineer: ["claude-sonnet-5-5[1m]", "claude-opus-5-5", "gpt-6-sol"] },
  defaults: { architect: "claude-fable-5-1", engineer: "claude-sonnet-5-5[1m]" },
  models: {
    "claude-fable-5-1": { harness: "claude", provider: "anthropic", effort_cap: "medium" },
    "claude-sonnet-5-5[1m]": { harness: "claude", provider: "anthropic", effort_cap: "high" },
    "claude-opus-5-5": { harness: "claude", provider: "anthropic", effort_cap: "medium" },
    "gpt-6-sol": { harness: "codex", provider: "openai", effort_cap: null },
  },
};

const story = { id: "s-1", kind: "story", work_type: "feature", title: "First story", status: "ready", assignee: null, criteria: "0/1", gates: [], blocked_by: [], children: [] };

function board(opts: { epicTags: string[]; storyTags?: string[]; picks?: Record<string, unknown> }) {
  const patches: { id: string; tags: string[] }[] = [];
  const patch = (id: string) => http.patch(`/v1/tickets/${id}`, async ({ request }) => {
    const body = (await request.json()) as { tags: string[] };
    patches.push({ id, tags: body.tags });
    return okJson({ id, tags: body.tags }, "updated");
  });
  server.use(
    http.get("/v1/models", () => okJson(CATALOG)),
    http.get("/v1/tickets/epic-1", () => okJson({ id: "epic-1", kind: "epic", tags: opts.epicTags })),
    http.get("/v1/tickets/s-1", () => okJson({ id: "s-1", kind: "story", tags: opts.storyTags ?? [] })),
    http.get("/v1/epics/epic-1/page", () => okJson({
      board: { epic: { id: "epic-1", kind: "epic", title: "E", status: "in_progress", children: [story] } },
      story_picks: opts.picks ?? {},
    })),
    patch("epic-1"), patch("s-1"),
  );
  return patches;
}

const mount = () => renderRoute("/x", "/x", <ModelsControl epicId="epic-1" />);
const byId = (id: string) => screen.findByTestId(id) as Promise<HTMLSelectElement>;

describe("ModelsControl (S7 option lists and story picks)", () => {
  it("adds an option to a role's list, clamps its effort to the model's cap and saves model:<role>=<id>@<effort>|…", async () => {
    const patches = board({ epicTags: ["area:ui"] });
    mount();
    fireEvent.click(await screen.findByTestId("models-addopt-engineer"));
    const model = await byId("models-opt1-model-engineer");
    expect(model.value).toBe("claude-opus-5-5");
    // opus is capped at medium: high is greyed, and a Claude row with a high cap (sonnet 1M) allows it
    const effort = await byId("models-opt1-effort-engineer");
    expect([...effort.options].find((o) => o.value === "high")?.disabled).toBe(true);
    fireEvent.change(model, { target: { value: "gpt-6-sol" } });
    fireEvent.change(effort, { target: { value: "high" } });
    const head = await byId("models-effort-engineer");
    expect([...head.options].find((o) => o.value === "high")?.disabled).toBe(false);
    fireEvent.change(head, { target: { value: "high" } });
    fireEvent.click(screen.getByTestId("models-save"));
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0].id).toBe("epic-1");
    expect(patches[0].tags).toContain("area:ui");
    expect(patches[0].tags).toContain("model:engineer=claude-sonnet-5-5[1m]@high|gpt-6-sol@high");
    expect(patches[0].tags.some((t) => t.startsWith("seat-effort:engineer"))).toBe(false);
    expect(await screen.findByTestId("models-saved")).toHaveTextContent("next seat spawned");
    expect(screen.getByTestId("models-applies-note")).toHaveTextContent("never swapped");
  });

  it("makes the second option the default and removes one", async () => {
    const patches = board({ epicTags: ["model:engineer=claude-sonnet-5-5[1m]@high|gpt-6-sol@medium|claude-opus-5-5@low"] });
    mount();
    await byId("models-opt1-model-engineer");
    fireEvent.click(screen.getByTestId("models-opt2-remove-engineer"));
    fireEvent.click(screen.getByTestId("models-opt1-default-engineer"));
    expect((await byId("models-model-engineer")).value).toBe("gpt-6-sol");
    fireEvent.click(screen.getByTestId("models-save"));
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0].tags).toContain("model:engineer=gpt-6-sol@medium|claude-sonnet-5-5[1m]@high");
  });

  it("a story picks one of its role's options; only the story's tags are written", async () => {
    const patches = board({
      epicTags: ["model:engineer=claude-sonnet-5-5[1m]@high|gpt-6-sol@medium"], storyTags: ["area:ui"],
    });
    mount();
    const pick = await byId("models-pick-s-1-engineer");
    expect([...pick.options].map((o) => o.value).slice(0, 3)).toEqual(["", "claude-sonnet-5-5[1m]@high", "gpt-6-sol@medium"]);
    expect(pick.options[0]).toHaveTextContent("Default");
    fireEvent.change(pick, { target: { value: "gpt-6-sol@medium" } });
    fireEvent.click(screen.getByTestId("models-save"));
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toEqual({ id: "s-1", tags: ["area:ui", "seat:engineer=gpt-6-sol@medium"] });
    expect(await screen.findByTestId("models-saved")).toHaveTextContent("never swapped");
  });

  it("a role with one option offers no story pick", async () => {
    board({ epicTags: [] });
    mount();
    await byId("models-model-architect");
    expect(screen.queryByTestId("models-pick-s-1-architect")).not.toBeInTheDocument();
  });

  it("removing an option keeps a story pick whose model the role's catalog still lists (RC2 F2)", async () => {
    const patches = board({
      epicTags: ["model:engineer=claude-sonnet-5-5[1m]@high|gpt-6-sol@medium"],
      storyTags: ["area:ui", "seat:engineer=gpt-6-sol@medium"],
      picks: { "s-1": { engineer: { model: "gpt-6-sol", effort: "medium" } } },
    });
    mount();
    expect((await byId("models-pick-s-1-engineer")).value).toBe("gpt-6-sol@medium");
    fireEvent.click(screen.getByTestId("models-opt1-remove-engineer"));
    fireEvent.click(screen.getByTestId("models-save"));
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0].id).toBe("epic-1");
    expect(patches[0].tags).toContain("model:engineer=claude-sonnet-5-5[1m]@high");
    expect((await byId("models-pick-s-1-engineer")).value).toBe("gpt-6-sol@medium");
  });

  // RC2 F2 (owner: "the models tab under the actions dropdown is also broken"): on epic-0cec8d1c31 the
  // engineer list held one option (Sonnet) while three stories carried `seat:engineer=claude-opus-5-5@medium`.
  // The board spawns those stories on Opus (the story pick wins), but the dialog showed "Default (Sonnet)"
  // and the raw id `claude-sonnet-5-5[1m]`.
  it("a story pick outside the epic's list shows the model that really runs, never Default", async () => {
    const patches = board({
      epicTags: ["model:engineer=claude-sonnet-5-5[1m]"],
      storyTags: ["seat:engineer=claude-opus-5-5@medium"],
      picks: { "s-1": { engineer: { model: "claude-opus-5-5", effort: "medium" } } },
    });
    mount();
    const pick = await byId("models-pick-s-1-engineer");
    expect(pick.value).toBe("claude-opus-5-5@medium");
    expect(pick.selectedOptions[0]).toHaveTextContent("Claude Opus 5.5 · medium");
    expect(screen.queryByTestId("models-pick-stale-s-1-engineer")).toBeNull(); // a catalog model: a valid pick
    expect((await byId("models-model-engineer")).selectedOptions[0]).toHaveTextContent("Claude Sonnet 5.5 (1M)");
    expect(screen.getByTestId("models-save")).toBeDisabled(); // showing a pick is not an edit
    fireEvent.change(pick, { target: { value: "" } });
    fireEvent.change(pick, { target: { value: "claude-opus-5-5@medium" } }); // back to the pick it has
    expect(screen.getByTestId("models-save")).toBeDisabled();
    expect(patches).toHaveLength(0);
  });

  it("on an epic listing only Sonnet, a story can be set to Opus at high (RC2 F2, architect m-1f09a47214)", async () => {
    const patches = board({ epicTags: ["model:engineer=claude-sonnet-5-5[1m]"], storyTags: ["area:ui"] });
    server.use(http.get("/v1/models", () => okJson({ ...CATALOG, models: { ...CATALOG.models,
      "claude-opus-5-5": { harness: "claude", provider: "anthropic", effort_cap: "high" } } })));
    mount();
    const pick = await byId("models-pick-s-1-engineer");
    await waitFor(() => expect([...pick.options].map((o) => o.value)).toContain("claude-opus-5-5@high"));
    expect([...pick.options].map((o) => o.value)).toEqual(expect.arrayContaining(["gpt-6-sol@high", "claude-opus-5-5@low"]));
    fireEvent.change(pick, { target: { value: "claude-opus-5-5@high" } });
    fireEvent.click(screen.getByTestId("models-save"));
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toEqual({ id: "s-1", tags: ["area:ui", "seat:engineer=claude-opus-5-5@high"] });
  });

  it("a pick above its model's cap is flagged, never offered", async () => {
    board({
      epicTags: ["model:engineer=claude-sonnet-5-5[1m]"], storyTags: ["seat:engineer=claude-opus-5-5@high"],
      picks: { "s-1": { engineer: { model: "claude-opus-5-5", effort: "high" } } },
    });
    mount();
    const pick = await byId("models-pick-s-1-engineer");
    expect(pick.value).toBe("claude-opus-5-5@high");
    expect(pick.selectedOptions[0]).toHaveTextContent("(not in the catalog)"); // CATALOG caps Opus at medium
    expect(screen.getByTestId("models-pick-stale-s-1-engineer")).toHaveTextContent("runs on Claude Opus 5.5 · high");
  });
});

// S12-ui (owner m-839aa76c90): the Models drawer's save/close row is its footer, with a Close beside Save
describe("ModelsControl footer (S12-ui)", () => {
  it("puts Close, Reset and Save models in one footer row when it sits in a drawer", async () => {
    board({ epicTags: [] });
    let closed = 0;
    renderRoute("/epic/epic-1", "/epic/:id", <Drawer open title="Models" onClose={() => { closed += 1; }}><ModelsControl epicId="epic-1" /></Drawer>);
    const actions = await screen.findByTestId("models-actions");
    expect(within(actions).getByTestId("models-close")).toHaveTextContent("Close");
    expect(within(actions).getByTestId("models-save")).toBeInTheDocument();
    expect(actions).toBe(screen.getByTestId("models-dialog").lastElementChild);
    fireEvent.click(within(actions).getByTestId("models-close"));
    expect(closed).toBe(1);
  });

  it("names roles with the one role-label helper: QA, not qa", async () => {
    board({ epicTags: [] });
    server.use(http.get("/v1/models", () => okJson({ ...CATALOG, roles: { ...CATALOG.roles, qa: ["claude-fable-5-1"] },
      defaults: { ...CATALOG.defaults, qa: "claude-fable-5-1" } })));
    renderRoute("/epic/epic-1", "/epic/:id", <ModelsControl epicId="epic-1" />);
    const row = await screen.findByTestId("models-row-qa");
    expect(row).toHaveTextContent("QA");
    expect(screen.getByTestId("models-addopt-qa")).toHaveAccessibleName("Add an option for QA");
  });
});

// S12-ui (owner m-839aa76c90): "Add an option for <role>" is a compact text action, not a full-width bordered button
describe("Add an option (S12-ui)", () => {
  it("is not styled as a bordered button", async () => {
    board({ epicTags: [] });
    renderRoute("/epic/epic-1", "/epic/:id", <ModelsControl epicId="epic-1" />);
    const add = await screen.findByTestId("models-addopt-engineer");
    expect(add.className.split(" ")).not.toContain(ui.button);
  });
});

// S12-ui2 (qa m-da89ef8294 a, b): "+ Add an option" sits ON the role's row after the effort select, as an icon button
// whose words are its tooltip and accessible name; the ROLE/MODEL/EFFORT header sticks while the rows scroll.
describe("Models layout (S12-ui2)", () => {
  it("puts the add button on the role's row, after the effort select, named by its tooltip", async () => {
    board({ epicTags: [] });
    renderRoute("/epic/epic-1", "/epic/:id", <ModelsControl epicId="epic-1" />);
    const row = await screen.findByTestId("models-row-engineer");
    const add = within(row).getByTestId("models-addopt-engineer");
    const effort = within(row).getByTestId("models-effort-engineer");
    expect(effort.compareDocumentPosition(add) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(add).toHaveAttribute("title", "Add an option for Engineer");
    expect(add).toHaveAccessibleName("Add an option for Engineer");
    fireEvent.click(add);
    expect(await screen.findByTestId("models-opt1-model-engineer")).toBeInTheDocument();
  });

  it("makes the column header sticky", async () => {
    board({ epicTags: [] });
    renderRoute("/epic/epic-1", "/epic/:id", <ModelsControl epicId="epic-1" />);
    expect(await screen.findByTestId("seat-pick-head")).toBeInTheDocument();
    const css = readFileSync(resolve(__dirname, "SeatPicks.module.css"), "utf-8");
    expect(css).toMatch(/\n\.head \{[^}]*position:\s*sticky/);
  });
});
