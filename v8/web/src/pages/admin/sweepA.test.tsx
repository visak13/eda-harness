import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { http, HttpResponse, delay } from "msw";
import { server } from "../../test/setup";
import { ThemeProvider } from "../../theme/ThemeProvider";
import SETTINGS from "../../test/fixtures/admin-settings.json";
import { AdminPage } from "./Admin";
import { ActionsMenu } from "../../components/ActionsMenu";
import { useActionDirty } from "../../components/actionDirty";
import { modelLabel } from "../../api/seats";
import { handleError } from "../../api/admin";

// S12 sweep (note-8f0629190d) findings #3, #8, #9, #10, #12, #13: each test fails on 0.10.0.

const ok = (value: unknown) => HttpResponse.json({ ok: true, value, hint: "" });
const WHO = { participant: { id: "owner", handle: "owner", role: "owner", type: "human" }, tickets: [], admin: true };
const TAILNET = { tailscale: { backend: "Running", dns: "host.tail.ts.net" }, serve: null, serve_proxies: [], public_url: "https://host.tail.ts.net", tailnet_url: "https://host.tail.ts.net",
  public_mode: true, running_public: true, rows: [], blockers: 0, auth_keys: { configured: true } };
const HARNESS = { harness: "claude", selected: true, installed: true, path: "C:/bin/claude", version: "2.1.0", signed_in: true, latest: null, live_seats: [], update: null };

function handlers(extra: Parameters<typeof server.use> = []) {
  server.use(...extra,
    http.get("/v1/whoami", () => ok(WHO)),
    http.get("/v1/admin/services", () => ok({ services: [], supervisor: { running: true, control: true } })),
    http.get("/v1/admin/capacity", () => ok({ total: { cap: 1, overridden: false, in_use: 0 }, live: { cap: 1, overridden: false, in_use: 0 }, classes: [], roles: [], note: "" })),
    http.get("/v1/admin/updates", () => ok({ current: "1", latest: "1", available: false, url: "", checked: true, apply_refusal: null, last: { request: null, result: null, log: [] } })),
    http.get("/v1/admin/release", () => ok({ can_cut: false, reason: "x", repo: "a/b", default_ref: "main", token_set: true, last: null })),
    http.get("/v1/admin/settings", () => ok(SETTINGS)),
    http.get("/v1/admin/teammates", () => ok([])),
    http.get("/v1/admin/tokens/agents", () => ok([])),
    http.get("/v1/admin/access-requests", () => ok([])),
    http.get("/v1/admin/tailnet", () => ok(TAILNET)),
    http.get("/v1/admin/harnesses", () => ok({ harnesses: [HARNESS], selected: ["claude"], fable_ack: null, fable_notice: null })),
    http.get("/v1/admin/integrations", () => ok({ slack: { path: "", exists: false, config: {}, bot_token_set: false, webhook_set: false, people_effective: {} },
      plane: { configured: false, settings: [] }, code_server: { running: false, port: 19410, url: "" }, vscode: { extension_id: "x", vsix_url: "", board_url: "", signin_links: {} } })),
  );
}

function mount(tab: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={qc}><ThemeProvider><MemoryRouter initialEntries={[`/admin?tab=${tab}`]}><AdminPage /></MemoryRouter></ThemeProvider></QueryClientProvider>);
}

afterEach(() => vi.restoreAllMocks());

describe("#3 handle validation mirrors the server", () => {
  it("handleError accepts slugs and refuses names the server refuses", () => {
    for (const good of ["alex", "dr.o-neil_2", "@alex", "ab"]) expect(handleError(good), good).toBeNull();
    for (const bad of ["Bad Name!", "../etc", "a..b", "a/b", "x".repeat(70), "a", "-lead"]) expect(handleError(bad), bad).not.toBeNull();
  });

  it("the invite form shows an inline error, disables Invite and never posts a bad handle", async () => {
    const post = vi.fn();
    handlers([http.post("/v1/admin/teammates", () => { post(); return ok({}); })]);
    mount("teammates");
    const input = await screen.findByTestId("invite-handle");
    fireEvent.change(input, { target: { value: "Bad Name!" } });
    expect(await screen.findByTestId("invite-handle-error")).toHaveTextContent(/lowercase/);
    await waitFor(() => expect(screen.getByTestId("invite-submit")).toBeDisabled());
    fireEvent.submit(input.closest("form")!);
    expect(post).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: "alex" } });
    await waitFor(() => expect(screen.getByTestId("invite-submit")).not.toBeDisabled());
    expect(screen.queryByTestId("invite-handle-error")).toBeNull();
  });
});

describe("#9 no 'Invite is off' flash while Remote access loads", () => {
  it("says nothing about remote access until the tailnet answers, then nothing when it is on", async () => {
    handlers([http.get("/v1/admin/tailnet", async () => { await delay(300); return ok(TAILNET); })]);
    mount("teammates");
    await screen.findByTestId("invite-handle");
    expect(screen.queryByTestId("invite-off-reason")).toBeNull();
    expect(screen.queryByTestId("how-inviting-remote-off")).toBeNull();
    await delay(500);
    expect(screen.queryByTestId("invite-off-reason")).toBeNull();
  });
});

describe("#10 Remote access progress and link", () => {
  it("counts the setup steps without step 1 and opens the tailnet link in a new tab", async () => {
    handlers();
    mount("remote");
    const progress = await screen.findByTestId("remote-progress");
    await waitFor(() => expect(progress).toHaveTextContent("setup steps done (step 1 only explains)"));
    const link = await screen.findByRole("link", { name: "https://host.tail.ts.net" });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link.getAttribute("rel")).toContain("noreferrer");
  });
});

describe("#8 Seat harnesses while the probe runs", () => {
  it("shows Checking, not 'not tested yet', over a placeholder row; then 'unknown' for a latest it could not read", async () => {
    handlers([http.get("/v1/admin/harnesses", async () => { await delay(300); return ok({ harnesses: [HARNESS], selected: ["claude"], fable_ack: null, fable_notice: null }); })]);
    mount("integrations");
    const status = await screen.findByTestId("harnesses-status");
    expect(status).toHaveTextContent("Checking");
    expect(status).not.toHaveTextContent("not tested yet");
    expect(screen.getByTestId("harnesses-checking")).toBeInTheDocument();
    expect(await screen.findByTestId("harness-claude-latest-unknown")).toHaveTextContent("unknown");
    expect(screen.queryByTestId("harnesses-checking")).toBeNull();
  });
});

describe("#12 closing an Actions drawer with unsaved edits asks first", () => {
  function Body({ dirty }: { dirty: boolean }) { useActionDirty(dirty); return <p>body</p>; }
  const items = (dirty: boolean) => [{ key: "models", label: "Models…", gloss: "g", render: () => <Body dirty={dirty} /> }];

  it("keeps the drawer open when the discard is refused, closes it when confirmed", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    render(<ActionsMenu items={items(true)} subject="epic-1" />);
    fireEvent.click(screen.getByTestId("actions-open"));
    fireEvent.click(await screen.findByTestId("action-models"));
    expect(await screen.findByTestId("action-drawer-models")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("action-drawer-models")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(confirm).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(screen.queryByTestId("action-drawer-models")).toBeNull());
  });

  it("closes without asking when nothing is edited", async () => {
    const confirm = vi.spyOn(window, "confirm");
    render(<ActionsMenu items={items(false)} subject="epic-1" />);
    fireEvent.click(screen.getByTestId("actions-open"));
    fireEvent.click(await screen.findByTestId("action-models"));
    fireEvent.click(await screen.findByRole("button", { name: "Close" }));
    expect(confirm).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByTestId("action-drawer-models")).toBeNull());
  });
});

describe("#13 model names, 1M marker and the doctor warning", () => {
  it("names a [1m] id and marks a 1M-window row", () => {
    expect(modelLabel("claude-sonnet-5-5[1m]")).toBe("Claude Sonnet 5.5 (1M)");
    expect(modelLabel("claude-opus-5-5", { context_window: 1_000_000 })).toBe("Claude Opus 5.5 (1M)");
    expect(modelLabel("claude-fable-5-1", { context_window: 1_000_000 })).toBe("Claude Fable 5.1 (1M)");
    expect(modelLabel("claude-sonnet-5-5[1m]", { context_window: 1_000_000 })).toBe("Claude Sonnet 5.5 (1M)");
    expect(modelLabel("gpt-6-sol", {})).toBe("GPT-6 Sol");
  });

  it("the Models tab prints the doctor window warning", async () => {
    handlers([http.get("/v1/admin/models", () => ok({
      models: { "claude-opus-5-5": { harness: "claude", provider: "claude", context_window: 200000, auto_compact: 350000, effort_cap: "high" } },
      role_models: { engineer: ["claude-opus-5-5"] }, default_model: "claude-opus-5-5", selected: ["claude"], warnings: [],
      window_problems: [{ model: "claude-opus-5-5", code: "compact_above_window", what: "claude-opus-5-5 compacts at 350000 tokens but its real window is 200000", fix: "lower auto_compact" }],
    }))]);
    mount("models");
    expect(await screen.findByTestId("window-problem-claude-opus-5-5")).toHaveTextContent("compacts at 350000");
    expect(await screen.findByTestId("model-row-claude-opus-5-5")).toHaveTextContent("Claude Opus 5.5");
  });
});
