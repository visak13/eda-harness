import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, MemoryRouter, RouterProvider } from "react-router";
import { http, HttpResponse } from "msw";
import { server } from "../../test/setup";
import { ThemeProvider } from "../../theme/ThemeProvider";
import { appRoutes } from "../../routes";
import SETTINGS from "../../test/fixtures/admin-settings.json";
import type { SettingsView } from "../../api/admin";
import { AdminPage } from "./Admin";

// S6 (s-e6b4fa59d5) Admin console. c-f27302e7e4: tabs for an admin, none for a non-admin; the Settings tab
// renders EVERY key of a registry fixture (generated from edp8.admin.settings_api.listing(), 165 keys) —
// env-set keys read-only, secrets masked. c-e834afcefc: every mutating action shows the board's refusal.

const ok = (value: unknown, hint = "") => HttpResponse.json({ ok: true, value, hint });
const refuse = (status: number, message: string) => HttpResponse.json({ ok: false, error: { code: "http", message }, hint: "" }, { status });

const WHO_ADMIN = { participant: { id: "owner", handle: "owner", role: "owner", type: "human" }, tickets: [], admin: true };
const WHO_BOB = { participant: { id: "bob", handle: "bob", role: "owner", type: "human" }, tickets: [], admin: false };

const SERVICES = {
  services: [
    { service: "board", state: "up", health: "up", pid: 11, port: 9400, uptime: "1h", rev: "abcdef123", managed: true },
    { service: "pool", state: "up", health: "up", pid: 12, port: 9301, uptime: "1h", managed: true },
    { service: "code-server", state: "down", port: 9410, managed: false, note: "started by its own scripts" },
  ],
  supervisor: { running: true, control: true },
};
const CAPACITY = {
  total: { cap: 10, overridden: false, in_use: 3 },
  live: { cap: 20, overridden: false, in_use: 4 },
  classes: [
    { class: "builder", cap: 6, overridden: false, in_use: 2 },
    { class: "planner", cap: 4, overridden: false, in_use: 1 },
    { class: "checker", cap: null, overridden: false, exempt: true, in_use: 0 },
  ],
  roles: [
    { role: "engineer", capacity_class: "builder", declared_max: null, workflows: ["standard@1"], epics: 1, cap: null, overridden: false, in_use: 2 },
    { role: "designer", capacity_class: "planner", declared_max: 2, workflows: ["custom@3"], epics: 1, cap: 2, overridden: false, in_use: 0 },
  ],
  note: "Every cap is at least 1.",
};
const UPDATES = { current: "0.9.0", latest: "1.0.0", available: true, url: "https://example.test/r", checked: true, apply_refusal: null, last: { request: null, result: null, log: [] } };
const TEAM = [
  { id: "owner", handle: "owner", role: "owner", admin: true, init_human: true, has_token: true, last_seen: null, invite_expires: null },
  { id: "carol", handle: "carol", role: "owner", admin: false, init_human: false, has_token: true, last_seen: "2026-09-26T10:00:00Z", invite_expires: null },
];
const TAILNET = { tailscale: { backend: "Running", dns: "host.tail.ts.net" }, serve: null, serve_proxies: [], public_url: null, tailnet_url: "https://host.tail.ts.net",
  public_mode: false, rows: [{ level: "OK", check: "tailscale", detail: "running" }], blockers: 0, auth_keys: { configured: true } };
const INTEGRATIONS = {
  slack: { path: "slack_map.json", exists: true, config: { webhook_url: "https://hooks.slack.com/•••abcd", board_url: "http://b" }, bot_token_set: false, webhook_set: true,
    people_effective: { carol: { slack_id: "U1", source: "person settings" } } },
  plane: { configured: false, settings: (SETTINGS as SettingsView).groups.flatMap((g) => g.settings).filter((s) => s.env.startsWith("EDP8_PLANE_")) },
  code_server: { running: true, port: 9410, url: "http://127.0.0.1:9410/" },
  vscode: { extension_id: "edp.edp-code", vsix_url: "https://github.com/x/y/releases/latest", board_url: "http://b", signin_links: { carol: "vscode://edp.edp-code/signin?board=http%3A%2F%2Fb&handle=carol" } },
};
const HARNESSES = {
  harnesses: [
    { harness: "claude", selected: true, installed: true, path: "C:/bin/claude", version: "2.1.0", signed_in: true, latest: "2.2.0", live_seats: [], update: null },
    { harness: "codex", selected: true, installed: true, path: "C:/bin/codex", version: "0.40.0", signed_in: false, latest: "0.41.0", live_seats: ["qa.e-1"], update: null },
    { harness: "pi", selected: false, installed: false, path: null, version: null, signed_in: null, latest: null, live_seats: [], update: null },
  ],
  selected: ["claude", "codex"], fable_ack: null, fable_notice: null,
};

function adminHandlers(who: unknown = WHO_ADMIN) {
  return [
    http.get("/v1/whoami", () => ok(who)),
    http.get("/v1/admin/services", () => ok(SERVICES)),
    http.get("/v1/admin/capacity", () => ok(CAPACITY)),
    http.get("/v1/admin/updates", () => ok(UPDATES)),
    http.get("/v1/admin/settings", () => ok(SETTINGS)),
    http.get("/v1/admin/teammates", () => ok(TEAM)),
    http.get("/v1/admin/tokens/agents", () => ok([{ handle: "eng.x", participant_id: "eng.x", role: "engineer", model: null, last_seen: null, revoked: false }])),
    http.get("/v1/admin/tailnet", () => ok(TAILNET)),
    http.get("/v1/admin/integrations", () => ok(INTEGRATIONS)),
    http.get("/v1/admin/harnesses", () => ok(HARNESSES)),
  ];
}

function mount(tab = "services", extra: Parameters<typeof server.use> = [], who: unknown = WHO_ADMIN) {
  server.use(...extra, ...adminHandlers(who));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <MemoryRouter initialEntries={[`/admin?tab=${tab}`]}>
          <AdminPage />
        </MemoryRouter>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

const TOTAL_KEYS = (SETTINGS as SettingsView).groups.reduce((n, g) => n + g.settings.length, 0);

describe("Admin visibility (c-f27302e7e4)", () => {
  it("an admin sees the six tabs", async () => {
    mount();
    expect(await screen.findByTestId("admin-page")).toBeInTheDocument();
    for (const name of ["Services", "Settings", "Teammates", "Remote access", "Integrations", "Seats & models"]) {
      expect(screen.getByRole("tab", { name })).toBeInTheDocument();
    }
  });

  it("a non-admin gets no tabs and no admin fetch", async () => {
    const hit = vi.fn();
    mount("services", [http.get("/v1/admin/*", () => { hit(); return ok({}); })], WHO_BOB);
    expect(await screen.findByTestId("admin-forbidden")).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(hit).not.toHaveBeenCalled();
  });

  it("the rail shows Admin only to an admin", async () => {
    const common = [
      http.get("/v1/me/summary", () => ok({})),
      http.get("/v1/*", () => ok([])),
    ];
    for (const [who, present] of [[WHO_ADMIN, true], [WHO_BOB, false]] as const) {
      server.resetHandlers();
      server.use(http.get("/v1/whoami", () => ok(who)), ...adminHandlers(who).slice(1), ...common);
      const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      const router = createMemoryRouter(appRoutes, { initialEntries: ["/epics"] });
      const view = render(<QueryClientProvider client={qc}><ThemeProvider><RouterProvider router={router} /></ThemeProvider></QueryClientProvider>);
      await screen.findByTestId("identity");
      if (present) expect(await screen.findByTestId("nav-admin")).toHaveAttribute("href", "/admin");
      else await waitFor(() => expect(screen.queryByTestId("nav-admin")).toBeNull());
      view.unmount();
    }
  });
});

describe("Settings tab renders the registry (c-f27302e7e4)", () => {
  it("renders exactly one field per fixture key, in every group, with no hand-coded list", async () => {
    mount("settings");
    await waitFor(() => expect(screen.getAllByTestId("setting-field")).toHaveLength(TOTAL_KEYS));
    expect(TOTAL_KEYS).toBeGreaterThan(100);
    const keys = new Set(screen.getAllByTestId("setting-field").map((el) => el.getAttribute("data-key")));
    for (const g of (SETTINGS as SettingsView).groups) {
      expect(screen.getByTestId(`settings-group-${g.group}`)).toBeInTheDocument();
      for (const s of g.settings) expect(keys.has(s.key), s.key).toBe(true);
    }
    // each field carries its doc line
    const first = (SETTINGS as SettingsView).groups[0].settings[0];
    expect(screen.getByText(first.doc)).toBeInTheDocument();
  });

  it("env-set keys are read-only with the reason; secrets are masked and write-only", async () => {
    const view = structuredClone(SETTINGS) as SettingsView;
    const rows = view.groups.flatMap((g) => g.settings);
    const envRow = rows.find((s) => !s.secret && !s.env_only && s.type === "int")!;
    Object.assign(envRow, { source: "env", set: true, read_only: true, read_only_reason: `set by the environment variable ${envRow.env} (read-only here; unset it to edit)`, value: 9999 });
    const secret = rows.find((s) => s.secret && !s.read_only)!;
    Object.assign(secret, { source: "config", set: true, value: "********" });
    mount("settings", [http.get("/v1/admin/settings", () => ok(view))]);
    const envField = await screen.findByTestId(`setting-${envRow.key}-input`);
    expect(envField).toBeDisabled();
    expect(screen.getByTestId(`setting-${envRow.key}-readonly`)).toHaveTextContent(`set by the environment variable ${envRow.env}`);
    // every env-only / env-set row in the fixture is disabled too
    for (const s of rows.filter((r) => r.read_only)) expect(screen.getByTestId(`setting-${s.key}-input`)).toBeDisabled();
    const secretInput = screen.getByTestId(`setting-${secret.key}-input`) as HTMLInputElement;
    expect(secretInput.type).toBe("password");
    expect(secretInput.value).toBe("");
    expect(screen.getByTestId(`setting-${secret.key}-masked`)).toHaveTextContent("secret · set ********");
  });

  it("a save sends only the changed keys and raises the restart banner", async () => {
    let body: unknown = null;
    const row = (SETTINGS as SettingsView).groups.flatMap((g) => g.settings).find((s) => !s.read_only && s.type === "int" && s.restart_required !== "none")!;
    mount("settings", [http.put("/v1/admin/settings", async ({ request }) => { body = await request.json(); return ok({ updated: [], restart_required: [row.restart_required] }); })]);
    fireEvent.change(await screen.findByTestId(`setting-${row.key}-input`), { target: { value: "7" } });
    fireEvent.click(screen.getByTestId("admin-settings-save"));
    await waitFor(() => expect(body).toEqual({ values: { [row.key]: 7 } }));
    expect(await screen.findByTestId("restart-banner")).toHaveTextContent(`restart ${row.restart_required} to apply`);
    expect(screen.getByTestId(`restart-banner-${row.restart_required}`)).toBeInTheDocument();
  });
});

// ------------------------------------------------------------------ c-e834afcefc: every refusal is shown

type Case = { name: string; tab: string; method: "post" | "put" | "delete"; path: string; act: () => Promise<void> | void; testid: string };
const click = (id: string) => async () => { fireEvent.click(await screen.findByTestId(id)); };

const CASES: Case[] = [
  { name: "service restart", tab: "services", method: "post", path: "/v1/admin/services/pool/restart", act: click("service-pool-restart"), testid: "service-action-error" },
  { name: "update apply", tab: "services", method: "post", path: "/v1/admin/updates/apply", act: click("update-apply"), testid: "update-apply-error" },
  { name: "capacity save", tab: "services", method: "put", path: "/v1/admin/capacity",
    act: async () => { fireEvent.change(await screen.findByTestId("cap-total-input"), { target: { value: "8" } }); fireEvent.click(screen.getByTestId("capacity-save")); }, testid: "capacity-save-error" },
  { name: "settings save", tab: "settings", method: "put", path: "/v1/admin/settings",
    act: async () => {
      const row = (SETTINGS as SettingsView).groups.flatMap((g) => g.settings).find((s) => !s.read_only && s.type === "int")!;
      fireEvent.change(await screen.findByTestId(`setting-${row.key}-input`), { target: { value: "3" } });
      fireEvent.click(screen.getByTestId("admin-settings-save"));
    }, testid: "admin-settings-save-error" },
  { name: "invite", tab: "teammates", method: "post", path: "/v1/admin/teammates",
    act: async () => { fireEvent.change(await screen.findByTestId("invite-handle"), { target: { value: "dan" } }); fireEvent.click(screen.getByTestId("invite-submit")); }, testid: "invite-error" },
  { name: "revoke", tab: "teammates", method: "post", path: "/v1/admin/teammates/carol/revoke", act: click("teammate-carol-revoke"), testid: "teammate-action-error" },
  { name: "rotate", tab: "teammates", method: "post", path: "/v1/admin/teammates/carol/rotate", act: click("teammate-carol-rotate"), testid: "teammate-action-error" },
  { name: "re-invite", tab: "teammates", method: "post", path: "/v1/admin/teammates/carol/invite", act: click("teammate-carol-invite"), testid: "teammate-action-error" },
  { name: "admin flag", tab: "teammates", method: "put", path: "/v1/admin/teammates/carol", act: click("teammate-carol-admin"), testid: "teammate-action-error" },
  { name: "agent token revoke", tab: "teammates", method: "delete", path: "/v1/admin/tokens/agents/eng.x", act: click("agent-token-eng.x-revoke"), testid: "agent-token-revoke-error" },
  { name: "tailscale key", tab: "teammates", method: "post", path: "/v1/admin/teammates/carol/tailscale-key",
    act: async () => {
      await screen.findByTestId("teammate-carol");
      await waitFor(() => expect(screen.getByTestId("tailscale-key-who")).not.toBeDisabled());
      fireEvent.change(screen.getByTestId("tailscale-key-who"), { target: { value: "carol" } });
      fireEvent.click(screen.getByTestId("tailscale-key-mint"));
    }, testid: "tailscale-key-error" },
  { name: "tailnet apply", tab: "remote", method: "post", path: "/v1/admin/tailnet/apply", act: click("remote-apply"), testid: "remote-action-error" },
  { name: "slack save", tab: "integrations", method: "put", path: "/v1/admin/integrations/slack",
    act: async () => { fireEvent.change(await screen.findByTestId("slack-webhook"), { target: { value: "https://evil.example/x" } }); fireEvent.click(screen.getByTestId("slack-save")); }, testid: "slack-save-error" },
  { name: "slack test", tab: "integrations", method: "post", path: "/v1/admin/integrations/slack/test", act: click("slack-test"), testid: "slack-test-error" },
  { name: "plane test", tab: "integrations", method: "post", path: "/v1/admin/integrations/plane/test", act: click("plane-test"), testid: "plane-test-error" },
  { name: "code-server test", tab: "integrations", method: "post", path: "/v1/admin/integrations/code-server/test", act: click("code-server-test"), testid: "code-server-test-error" },
  { name: "vscode test", tab: "integrations", method: "post", path: "/v1/admin/integrations/vscode/test", act: click("vscode-test"), testid: "vscode-test-error" },
  { name: "harness update", tab: "integrations", method: "post", path: "/v1/admin/harnesses/codex/update", act: click("harness-codex-update"), testid: "harness-update-error" },
  { name: "harness selection", tab: "models", method: "put", path: "/v1/admin/harnesses/selection",
    act: async () => { fireEvent.click(await screen.findByTestId("pick-pi-input")); fireEvent.click(screen.getByTestId("harness-selection-save")); }, testid: "harness-selection-save-error" },
];

describe("every admin action shows the board's refusal (c-e834afcefc)", () => {
  it.each(CASES)("$name", async (c) => {
    const message = `refused: ${c.name} is not allowed right now (${c.path})`;
    mount(c.tab, [http[c.method](c.path, () => refuse(409, message))]);
    await c.act();
    expect(await screen.findByTestId(c.testid)).toHaveTextContent(message);
  });

  it("tailnet remove too", async () => {
    mount("remote", [
      http.get("/v1/admin/tailnet", () => ok({ ...TAILNET, public_mode: true, public_url: "https://host.tail.ts.net" })),
      http.post("/v1/admin/tailnet/remove", () => refuse(409, "EDP8_PUBLIC_URL is set by the environment")),
    ]);
    fireEvent.click(await screen.findByTestId("remote-remove"));
    expect(await screen.findByTestId("remote-action-error")).toHaveTextContent("EDP8_PUBLIC_URL is set by the environment");
  });

  it("plane save too", async () => {
    mount("integrations", [http.put("/v1/admin/integrations/plane", () => refuse(400, "plane.url: not a valid url"))]);
    const url = await screen.findByTestId("setting-plane.url-input").catch(() => null);
    const first = url ?? (await screen.findAllByTestId(/setting-plane\..*-input/))[0];
    fireEvent.change(first, { target: { value: "x" } });
    fireEvent.click(screen.getByTestId("plane-save"));
    expect(await screen.findByTestId("plane-save-error")).toHaveTextContent("plane.url: not a valid url");
  });
});

describe("Services", () => {
  it("a board restart shows restarting… and polls /healthz until a new started_at", async () => {
    let n = 0;
    mount("services", [
      http.post("/v1/admin/services/board/restart", () => HttpResponse.json({ ok: true, value: { service: "board", state: "restarting", started_at: "T0" }, hint: "poll /healthz" }, { status: 202 })),
      http.get("/healthz", () => {
        n += 1;
        if (n === 2) return HttpResponse.error();
        return HttpResponse.json({ ok: true, started_at: n < 3 ? "T0" : "T1" });
      }),
    ]);
    fireEvent.click(await screen.findByTestId("service-board-restart"));
    expect(await screen.findByTestId("restart-status")).toHaveTextContent(/Restarting board/);
    await waitFor(() => expect(screen.getByTestId("restart-status")).toHaveTextContent("board is back (started T1)"), { timeout: 8000 });
  }, 12_000);

  it("shows the update banner with Apply, and the refusal reason when Apply is impossible", async () => {
    mount("services", [http.get("/v1/admin/updates", () => ok({ ...UPDATES, apply_refusal: "this is a source checkout (dev mode): update it with git" }))]);
    expect(await screen.findByTestId("update-banner")).toHaveTextContent("Version 1.0.0 is available (this install runs 0.9.0)");
    expect(screen.getByTestId("update-apply")).toBeDisabled();
    expect(screen.getByTestId("update-refusal")).toHaveTextContent("dev mode");
  });

  it("unmanaged code-server has no buttons; the supervisor being down is said", async () => {
    mount("services", [http.get("/v1/admin/services", () => ok({ ...SERVICES, supervisor: { running: false, control: false } }))]);
    const row = await screen.findByTestId("service-code-server");
    expect(within(row).queryByRole("button")).toBeNull();
    expect(screen.getByTestId("supervisor-down")).toHaveTextContent("not running");
  });
});

describe("Capacity (c-002a8ba1b5)", () => {
  it("shows every cap with live usage, checker exempt, per-role rows from the pinned workflows", async () => {
    mount("services");
    expect(await screen.findByTestId("cap-total-usage")).toHaveTextContent("3 / 10 in use");
    expect(screen.getByTestId("cap-live-usage")).toHaveTextContent("4 / 20 in use");
    expect(screen.getByTestId("cap-class:builder-usage")).toHaveTextContent("2 / 6 in use");
    expect(screen.getByTestId("cap-class:planner-usage")).toHaveTextContent("1 / 4 in use");
    expect(screen.getByTestId("cap-class:checker-usage")).toHaveTextContent("exempt from class caps");
    expect(screen.getByTestId("cap-role:engineer-usage")).toHaveTextContent("2 / no cap in use");
    expect(screen.getByTestId("cap-role:designer")).toHaveTextContent("custom@3");
    expect(screen.getByTestId("capacity")).toHaveTextContent("a cap of 0 would not pause anything");
  });

  it("clamps below 1 with the pause explanation and saves only what changed", async () => {
    let body: unknown = null;
    mount("services", [http.put("/v1/admin/capacity", async ({ request }) => { body = await request.json(); return ok(CAPACITY, "applied by the pool now; no restart needed"); })]);
    fireEvent.change(await screen.findByTestId("cap-class:builder-input"), { target: { value: "0" } });
    expect(screen.getByTestId("capacity-clamp")).toHaveTextContent("saved as 1");
    fireEvent.change(screen.getByTestId("cap-role:designer-input"), { target: { value: "" } });
    fireEvent.change(screen.getByTestId("cap-live-input"), { target: { value: "12" } });
    fireEvent.click(screen.getByTestId("capacity-save"));
    await waitFor(() => expect(body).toEqual({ max_live_shells: 12, classes: { builder: 1 }, role_caps: { designer: null } }));
    expect(await screen.findByTestId("capacity-saved")).toHaveTextContent("no restart needed");
  });
});

describe("Teammates", () => {
  it("an invite shows the one-time link and the VS Code deep link, each with a copy button", async () => {
    mount("teammates", [http.post("/v1/admin/teammates", () => ok({ teammate: { ...TEAM[1], handle: "dan" },
      invite: { link: "http://b/ui/join?code=abc", vscode_link: "vscode://edp.edp-code/signin?board=http%3A%2F%2Fb&handle=dan&code=abc", code: "abc", expires_at: "2026-09-28T00:00:00Z" } }))]);
    fireEvent.change(await screen.findByTestId("invite-handle"), { target: { value: "dan" } });
    fireEvent.click(screen.getByTestId("invite-submit"));
    expect(await screen.findByTestId("invite-link")).toHaveTextContent("http://b/ui/join?code=abc");
    expect(screen.getByTestId("invite-vscode-link")).toHaveTextContent("vscode://edp.edp-code/signin");
    expect(screen.getByTestId("invite-link-copy")).toBeInTheDocument();
    expect(screen.getByTestId("invite-vscode-link-copy")).toBeInTheDocument();
  });

  it("the Tailscale key panel is disabled with a pointer until the API is configured", async () => {
    mount("teammates", [http.get("/v1/admin/tailnet", () => ok({ ...TAILNET, auth_keys: { configured: false } }))]);
    expect(await screen.findByTestId("tailscale-keys-off")).toHaveTextContent("configure the Tailscale API");
    expect(screen.getByTestId("tailscale-key-mint")).toBeDisabled();
  });

  it("rotate shows the new token once", async () => {
    mount("teammates", [http.post("/v1/admin/teammates/carol/rotate", () => ok({ handle: "carol", token: "new-secret" }))]);
    fireEvent.click(await screen.findByTestId("teammate-carol-rotate"));
    expect(await screen.findByTestId("rotated-token")).toHaveTextContent("new-secret");
  });
});

describe("Integrations", () => {
  it("has a card with a Test for Slack, VS Code, code-server, Plane and harnesses (installed/latest)", async () => {
    mount("integrations");
    for (const id of ["slack", "vscode", "code-server", "plane", "harnesses"]) expect(await screen.findByTestId(`integration-${id}`)).toBeInTheDocument();
    for (const id of ["slack-test", "vscode-test", "code-server-test", "plane-test", "harnesses-test"]) expect(screen.getByTestId(id)).toBeInTheDocument();
    expect(await screen.findByTestId("harness-codex")).toHaveTextContent("0.40.0");
    expect(screen.getByTestId("harness-codex")).toHaveTextContent("0.41.0");
  });

  it("a Slack test ping reports where it went", async () => {
    mount("integrations", [http.post("/v1/admin/integrations/slack/test", () => ok({ sent: true, to: "the default webhook" }))]);
    fireEvent.click(await screen.findByTestId("slack-test"));
    expect(await screen.findByTestId("slack-test-done")).toHaveTextContent("Test ping sent to the default webhook");
  });
});

describe("Seats & models (§4.11)", () => {
  it("shows the Fable risk notice when codex is not selected and needs the acknowledgement once", async () => {
    let body: unknown = null;
    mount("models", [http.put("/v1/admin/harnesses/selection", async ({ request }) => { body = await request.json(); return ok({ selected: ["claude"], fable_ack: { by: "owner" }, restart_required: ["board"] }); })]);
    await screen.findByTestId("harness-selection");
    await waitFor(() => expect(screen.getByTestId("pick-codex-input")).toBeChecked());
    expect(screen.queryByTestId("fable-notice")).toBeNull();
    fireEvent.click(screen.getByTestId("pick-codex-input"));
    expect(screen.getByTestId("fable-notice")).toHaveTextContent("adversary role runs on Fable");
    expect(screen.getByTestId("harness-selection-save")).toBeDisabled();
    fireEvent.click(screen.getByTestId("fable-ack"));
    fireEvent.click(screen.getByTestId("harness-selection-save"));
    await waitFor(() => expect(body).toEqual({ harnesses: ["claude"], fable_ack: true }));
  });

  it("refuses to save with neither claude nor codex", async () => {
    mount("models");
    await waitFor(() => expect(screen.getByTestId("pick-codex-input")).toBeChecked());
    fireEvent.click(screen.getByTestId("pick-codex-input"));
    fireEvent.click(screen.getByTestId("pick-claude-input"));
    expect(screen.getByTestId("harness-neither")).toBeInTheDocument();
    expect(screen.getByTestId("harness-selection-save")).toBeDisabled();
  });
});

// S12 (t-186b964fb1, contract m-62fc5b54f9): Admin → Seats & models → Models. The editor lists only entries
// of the selected harnesses, keeps hidden entries on every full-replacement PUT, adds/edits/removes,
// sets a role default (first id) and shows a test-spawn reply.
describe("Models editor (S12)", () => {
  type Cat = { models: Record<string, Record<string, unknown>>; role_models: Record<string, string[]>; selected: string[]; warnings: string[] };
  const CATALOG: Cat = {
    models: {
      "claude-opus-5-5": { harness: "claude", provider: "anthropic", context_window: 200000, effort_cap: "medium" },
      "gpt-6-sol": { harness: "codex", provider: "openai", context_window: null, effort_cap: null },
      "hidden-model": { harness: "pi", provider: "openrouter", effort_cap: null, auto_compact: 0.8 },
    },
    role_models: { engineer: ["claude-opus-5-5", "gpt-6-sol"], qa: ["claude-opus-5-5"] },
    selected: ["claude", "codex"],
    warnings: ["codex is selected but not signed in"],
  };

  function stateful(start: Cat) {
    let cur: Cat = structuredClone(start);
    const puts: Cat[] = [];
    return {
      puts,
      handlers: [
        http.get("/v1/admin/models", () => ok(cur)),
        http.put("/v1/admin/models", async ({ request }) => {
          const b = (await request.json()) as Cat;
          puts.push(b);
          cur = { ...cur, models: b.models, role_models: b.role_models };
          return ok(cur, "catalog saved");
        }),
        http.post("/v1/admin/models/test-spawn", async ({ request }) => {
          const b = (await request.json()) as { model: string; role: string };
          const e = cur.models[b.model] as { harness: string; provider: string };
          return ok({ reply: `stub reply from ${b.model}`, model: b.model, harness: e.harness, provider: e.provider });
        }),
      ],
    };
  }

  it("lists only selected-harness models, shows warnings and the hidden count", async () => {
    const s = stateful(CATALOG);
    mount("models", s.handlers);
    expect(await screen.findByTestId("model-row-claude-opus-5-5")).toHaveTextContent("anthropic");
    expect(screen.getByTestId("model-row-gpt-6-sol")).toHaveTextContent("codex");
    expect(screen.queryByTestId("model-row-hidden-model")).toBeNull();
    expect(screen.getByTestId("models-hidden")).toHaveTextContent("1 model of unselected harnesses is hidden");
    expect(screen.getByTestId("models-warnings")).toHaveTextContent("not signed in");
    expect(screen.getByTestId("model-row-claude-opus-5-5")).toHaveTextContent("engineer (default)");
  });

  it("add a Pi model, make it a role default, test spawn a stub reply, then remove it (hidden entries kept)", async () => {
    const s = stateful({ ...CATALOG, selected: ["claude", "pi"] });
    mount("models", s.handlers);
    await screen.findByTestId("model-row-claude-opus-5-5");
    fireEvent.click(screen.getByTestId("model-add"));
    expect(screen.getByTestId("model-form-harness")).toHaveValue("pi");
    fireEvent.change(screen.getByTestId("model-form-id"), { target: { value: "qwen3-coder" } });
    fireEvent.change(screen.getByTestId("model-form-provider"), { target: { value: "openrouter" } });
    fireEvent.change(screen.getByTestId("model-form-window"), { target: { value: "128000" } });
    fireEvent.change(screen.getByTestId("model-form-cap"), { target: { value: "medium" } });
    fireEvent.click(screen.getByTestId("model-form-save"));
    await waitFor(() => expect(s.puts).toHaveLength(1));
    expect(s.puts[0].models["qwen3-coder"]).toEqual({ harness: "pi", provider: "openrouter", context_window: 128000, effort_cap: "medium" });
    expect(s.puts[0].models["gpt-6-sol"]).toBeDefined(); // the unselected codex entry is kept
    expect(await screen.findByTestId("model-row-qwen3-coder")).toHaveTextContent("openrouter");

    fireEvent.click(await screen.findByTestId("role-pick-engineer-qwen3-coder-input"));
    fireEvent.change(screen.getByTestId("role-default-engineer"), { target: { value: "qwen3-coder" } });
    fireEvent.click(screen.getByTestId("role-models-save"));
    await waitFor(() => expect(s.puts).toHaveLength(2));
    expect(s.puts[1].role_models.engineer).toEqual(["qwen3-coder", "claude-opus-5-5", "gpt-6-sol"]);
    await waitFor(() => expect(screen.getByTestId("model-row-qwen3-coder")).toHaveTextContent("engineer (default)"));

    fireEvent.change(screen.getByTestId("test-spawn-model"), { target: { value: "qwen3-coder" } });
    fireEvent.click(screen.getByTestId("test-spawn-run"));
    expect(await screen.findByTestId("test-spawn-reply")).toHaveTextContent("stub reply from qwen3-coder");
    expect(screen.getByTestId("test-spawn-result")).toHaveTextContent("pi · openrouter replied");

    fireEvent.click(screen.getByTestId("model-remove-qwen3-coder"));
    await waitFor(() => expect(s.puts).toHaveLength(3));
    expect(s.puts[2].models["qwen3-coder"]).toBeUndefined();
    expect(s.puts[2].role_models.engineer).toEqual(["claude-opus-5-5", "gpt-6-sol"]);
    await waitFor(() => expect(screen.queryByTestId("model-row-qwen3-coder")).toBeNull());
  });

  it("edit keeps fields the form does not show, and a refused save shows the board's words", async () => {
    const s = stateful({ ...CATALOG, selected: ["pi"] });
    mount("models", s.handlers);
    fireEvent.click(await screen.findByTestId("model-edit-hidden-model"));
    expect(screen.getByTestId("model-form-id")).toBeDisabled();
    fireEvent.change(screen.getByTestId("model-form-provider"), { target: { value: "groq" } });
    fireEvent.click(screen.getByTestId("model-form-save"));
    await waitFor(() => expect(s.puts).toHaveLength(1));
    expect(s.puts[0].models["hidden-model"]).toMatchObject({ provider: "groq", auto_compact: 0.8 });

    server.use(http.put("/v1/admin/models", () => refuse(400, "provider groq has no credential")));
    fireEvent.click(await screen.findByTestId("model-remove-hidden-model"));
    expect(await screen.findByTestId("models-save-error")).toHaveTextContent("no credential");
  });

  it("catches a duplicate id before the PUT", async () => {
    const s = stateful(CATALOG);
    mount("models", s.handlers);
    await screen.findByTestId("model-row-claude-opus-5-5");
    fireEvent.click(screen.getByTestId("model-add"));
    fireEvent.change(screen.getByTestId("model-form-id"), { target: { value: "gpt-6-sol" } });
    fireEvent.change(screen.getByTestId("model-form-provider"), { target: { value: "openai" } });
    expect(screen.getByTestId("model-form-clash")).toBeInTheDocument();
    expect(screen.getByTestId("model-form-save")).toBeDisabled();
    expect(s.puts).toHaveLength(0);
  });
});
