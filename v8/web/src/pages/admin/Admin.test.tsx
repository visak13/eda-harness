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
import { attentionHandler } from "../../test/attentionFixture";

// S6 (s-e6b4fa59d5) Admin console. c-f27302e7e4: tabs for an admin, none for a non-admin; the Settings tab
// renders EVERY visible key of a registry fixture (scripts/gen_admin_settings_fixture.py) —
// env-set keys read-only, secrets masked. c-e834afcefc: every mutating action shows the board's refusal.

const ok = (value: unknown, hint = "") => HttpResponse.json({ ok: true, value, hint });
const refuse = (status: number, message: string) => HttpResponse.json({ ok: false, error: { code: "http", message }, hint: "" }, { status });

const WHO_ADMIN = { participant: { id: "owner", handle: "owner", role: "owner", type: "human" }, tickets: [], admin: true };
const WHO_BOB = { participant: { id: "bob", handle: "bob", role: "owner", type: "human" }, tickets: [], admin: false };

const SERVICES = {
  services: [
    { service: "board", state: "up", health: "up", pid: 11, port: 9400, uptime: "1h", rev: "abcdef123", managed: true },
    { service: "pool", state: "up", health: "up", pid: 12, port: 9301, uptime: "1h", managed: true },
    { service: "code-server", state: "down", port: 9410, managed: true, installed: true, autostart: false,
      note: "optional: starts only when you start it" },
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
const ALL_ROWS = (SETTINGS as SettingsView).groups.flatMap((g) => g.settings);
const BASIC_KEYS = ALL_ROWS.filter((s) => s.tier === "basic").map((s) => s.key);
/** Turn on Settings → Show advanced (the page opens on basic keys only). */
async function showAdvanced() {
  fireEvent.click(await screen.findByTestId("settings-show-advanced"));
}
const REMOTE_ON = http.get("/v1/admin/tailnet", () => ok({ ...TAILNET, public_mode: true, public_url: "https://host.tail.ts.net" }));

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
    await showAdvanced();
    await waitFor(() => expect(screen.getAllByTestId("setting-field")).toHaveLength(TOTAL_KEYS));
    expect(TOTAL_KEYS).toBeGreaterThan(80); // basic + advanced; internal keys never reach the SPA
    const keys = new Set(screen.getAllByTestId("setting-field").map((el) => el.getAttribute("data-key")));
    for (const g of (SETTINGS as SettingsView).groups) {
      expect(screen.getByTestId(`settings-group-${g.group}`)).toBeInTheDocument();
      for (const s of g.settings) expect(keys.has(s.key), s.key).toBe(true);
    }
    // each field carries its plain help line
    const first = (SETTINGS as SettingsView).groups[0].settings[0];
    expect(screen.getByTestId(`setting-${first.key}-help`)).toHaveTextContent(first.help!);
  });

  it("env-set keys are read-only with the reason; secrets are masked and write-only", async () => {
    const view = structuredClone(SETTINGS) as SettingsView;
    const rows = view.groups.flatMap((g) => g.settings);
    const envRow = rows.find((s) => !s.secret && !s.env_only && s.type === "int")!;
    Object.assign(envRow, { source: "env", set: true, read_only: true, read_only_reason: `set by the environment variable ${envRow.env} (read-only here; unset it to edit)`, value: 9999 });
    const secret = rows.find((s) => s.secret && !s.read_only)!;
    Object.assign(secret, { source: "config", set: true, value: "********" });
    mount("settings", [http.get("/v1/admin/settings", () => ok(view))]);
    await showAdvanced();
    const envField = await screen.findByTestId(`setting-${envRow.key}-input`);
    expect(envField).toBeDisabled();
    expect(screen.getByTestId(`setting-${envRow.key}-readonly`)).toHaveTextContent("Set by the environment, so it is locked here.");
    expect(screen.getByTestId(`setting-${envRow.key}-readonly`).textContent).not.toContain(envRow.env);
    expect(screen.getByTestId(`setting-${envRow.key}-readonly-reason`)).toHaveTextContent(`set by the environment variable ${envRow.env}`);
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
    await showAdvanced();
    fireEvent.change(await screen.findByTestId(`setting-${row.key}-input`), { target: { value: "7" } });
    fireEvent.click(screen.getByTestId("admin-settings-save"));
    await waitFor(() => expect(body).toEqual({ values: { [row.key]: 7 } }));
    expect(await screen.findByTestId("restart-banner")).toHaveTextContent(`restart ${row.restart_required} to apply`);
    expect(screen.getByTestId(`restart-banner-${row.restart_required}`)).toBeInTheDocument();
  });
});

// ------------------------------------------------------------------ c-e834afcefc: every refusal is shown

type Case = { name: string; tab: string; method: "post" | "put" | "delete"; path: string; act: () => Promise<void> | void; testid: string; extra?: Parameters<typeof server.use> };
const click = (id: string) => async () => { fireEvent.click(await screen.findByTestId(id)); };

const CASES: Case[] = [
  { name: "service restart", tab: "services", method: "post", path: "/v1/admin/services/pool/restart", act: click("service-pool-restart"), testid: "service-action-error" },
  { name: "update apply", tab: "services", method: "post", path: "/v1/admin/updates/apply", act: click("update-apply"), testid: "update-apply-error" },
  { name: "capacity save", tab: "services", method: "put", path: "/v1/admin/capacity",
    act: async () => { fireEvent.change(await screen.findByTestId("cap-total-input"), { target: { value: "8" } }); fireEvent.click(screen.getByTestId("capacity-save")); }, testid: "capacity-save-error" },
  { name: "settings save", tab: "settings", method: "put", path: "/v1/admin/settings",
    act: async () => {
      const row = (SETTINGS as SettingsView).groups.flatMap((g) => g.settings).find((s) => !s.read_only && s.type === "int")!;
      await showAdvanced();
      fireEvent.change(await screen.findByTestId(`setting-${row.key}-input`), { target: { value: "3" } });
      fireEvent.click(screen.getByTestId("admin-settings-save"));
    }, testid: "admin-settings-save-error" },
  { name: "invite", tab: "teammates", method: "post", path: "/v1/admin/teammates",
    act: async () => { fireEvent.change(await screen.findByTestId("invite-handle"), { target: { value: "dan" } });
      await waitFor(() => expect(screen.getByTestId("invite-submit")).not.toBeDisabled()); fireEvent.click(screen.getByTestId("invite-submit")); }, testid: "invite-error", extra: [REMOTE_ON] },
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
    mount(c.tab, [http[c.method](c.path, () => refuse(409, message)), ...(c.extra ?? [])]);
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

  it("S21: the code-server row starts through the supervisor like the others; the supervisor being down is said", async () => {
    mount("services", [http.get("/v1/admin/services", () => ok({ ...SERVICES, supervisor: { running: false, control: false } }))]);
    const row = await screen.findByTestId("service-code-server");
    expect(within(row).getByTestId("service-code-server-start")).toBeEnabled();
    expect(within(row).getByTestId("service-code-server-stop")).toBeDisabled();
    expect(within(row).queryByText("not managed here")).toBeNull();
    expect(screen.getByTestId("supervisor-down")).toHaveTextContent("not running");
  });

  it("S21: a missing code-server says how to install it and offers nothing to start", async () => {
    const rows = SERVICES.services.map((r) => r.service === "code-server"
      ? { ...r, state: "not_installed", health: "not installed", installed: false, install_hint: "npm install -g code-server",
          note: "code-server is not installed. Install it: npm install -g code-server" } : r);
    mount("services", [http.get("/v1/admin/services", () => ok({ ...SERVICES, services: rows }))]);
    const row = await screen.findByTestId("service-code-server");
    expect(row).toHaveTextContent("npm install -g code-server");
    expect(row).toHaveTextContent("not installed");
    for (const verb of ["start", "stop", "restart"]) expect(within(row).getByTestId(`service-code-server-${verb}`)).toBeDisabled();
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
    mount("teammates", [REMOTE_ON, http.post("/v1/admin/teammates", () => ok({ teammate: { ...TEAM[1], handle: "dan" },
      invite: { link: "http://b/ui/join?code=abc", vscode_link: "vscode://edp.edp-code/signin?board=http%3A%2F%2Fb&handle=dan&code=abc", code: "abc", expires_at: "2026-09-28T00:00:00Z" } }))]);
    fireEvent.change(await screen.findByTestId("invite-handle"), { target: { value: "dan" } });
    await waitFor(() => expect(screen.getByTestId("invite-submit")).not.toBeDisabled());
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

  it("S20: the Teammates tab carries the access-request dot and the waiting request is marked", async () => {
    mount("teammates", [attentionHandler(), http.get("/v1/admin/access-requests", () => ok([
      { id: "ar-1", created_at: "2026-09-27T01:00:00Z", name: "Dana Lee", role_wanted: "engineer", note: "", status: "pending", decided_by: null, decided_at: null, handle: null },
      { id: "ar-2", created_at: "2026-09-27T01:05:00Z", name: "Eli Park", role_wanted: "engineer", note: "", status: "pending", decided_by: null, decided_at: null, handle: null }]))]);
    const tab = await screen.findByRole("tab", { name: /Teammates/ });
    expect(await within(tab).findByRole("img", { name: "needs your attention: 1" })).toBeInTheDocument();
    expect(within(screen.getByRole("tab", { name: /Services/ })).queryByRole("img")).toBeNull();
    const row = await screen.findByTestId("access-request-ar-1");
    await waitFor(() => expect(row).toHaveAttribute("data-attention", "true"));
    expect(within(row).getByRole("img", { name: "needs your attention: 1" })).toBeInTheDocument();
    expect(screen.getByTestId("access-request-ar-2")).not.toHaveAttribute("data-attention");
  });

  it("rotate shows the new token once", async () => {
    mount("teammates", [http.post("/v1/admin/teammates/carol/rotate", () => ok({ handle: "carol", token: "new-secret" }))]);
    fireEvent.click(await screen.findByTestId("teammate-carol-rotate"));
    expect(await screen.findByTestId("rotated-token")).toHaveTextContent("new-secret");
  });
});

// ------------------------------------------------------------------ t-5dd0cc18ea: owner walkthrough m-b9c54cb63b

describe("Admin UX pass (t-5dd0cc18ea, owner m-b9c54cb63b)", () => {
  it("Settings opens on basic keys only (about 20) and Show advanced adds the rest", async () => {
    mount("settings");
    expect(BASIC_KEYS.length).toBeGreaterThanOrEqual(15);
    expect(BASIC_KEYS.length).toBeLessThanOrEqual(25);
    await waitFor(() => expect(screen.getAllByTestId("setting-field")).toHaveLength(BASIC_KEYS.length));
    for (const el of screen.getAllByTestId("setting-field")) expect(el).toHaveAttribute("data-tier", "basic");
    expect(screen.getByTestId("settings-count")).toHaveTextContent(`The ${BASIC_KEYS.length} settings most people change`);
    const sw = screen.getByTestId("settings-show-advanced");
    expect(sw).toHaveAttribute("role", "switch");
    expect(sw).not.toBeChecked();
    await showAdvanced();
    await waitFor(() => expect(screen.getAllByTestId("setting-field")).toHaveLength(TOTAL_KEYS));
  });

  it("every enum key is radios (4 or fewer choices) or a dropdown, every boolean a toggle, every number carries its unit", async () => {
    mount("settings");
    await showAdvanced();
    await waitFor(() => expect(screen.getAllByTestId("setting-field")).toHaveLength(TOTAL_KEYS));
    const enums = ALL_ROWS.filter((s) => s.choices.length);
    expect(enums.length).toBeGreaterThanOrEqual(10);
    for (const s of enums) {
      const el = screen.getByTestId(`setting-${s.key}-input`);
      expect(el, s.key).toHaveAttribute("data-control", s.choices.length <= 4 ? "radio" : "select");
      if (s.choices.length <= 4) expect(within(el).getAllByRole("radio")).toHaveLength(s.choices.length);
      else expect(el.tagName).toBe("SELECT");
    }
    const bools = ALL_ROWS.filter((s) => s.type === "bool");
    expect(bools.length).toBeGreaterThan(5);
    for (const s of bools) expect(screen.getByTestId(`setting-${s.key}-input`), s.key).toHaveAttribute("role", "switch");
    for (const s of ALL_ROWS.filter((r) => (r.type === "int" || r.type === "float") && r.unit)) {
      expect(screen.getByTestId(`setting-${s.key}-unit`), s.key).toHaveTextContent(s.unit!);
    }
    // a radio click is a change like any other
    fireEvent.click(screen.getByTestId("setting-codex.effort-choice-high"));
    expect(screen.getByTestId("admin-settings-save")).toHaveTextContent("Save 1 change");
  });

  it("every visible key has a plain one-line description; the env var sits only in Advanced details", async () => {
    mount("settings");
    await showAdvanced();
    await waitFor(() => expect(screen.getAllByTestId("setting-field")).toHaveLength(TOTAL_KEYS));
    for (const s of ALL_ROWS) {
      expect(s.help, s.key).toBeTruthy();
      expect(s.label, s.key).toBeTruthy();
      const help = screen.getByTestId(`setting-${s.key}-help`);
      expect(help).toHaveTextContent(s.help!);
      expect(help.textContent).not.toContain(s.env);
      const details = screen.getByTestId(`setting-${s.key}-advanced`) as HTMLDetailsElement;
      expect(details.tagName).toBe("DETAILS");
      expect(details.open).toBe(false);
      expect(within(details).getByTestId(`setting-${s.key}-env`)).toHaveTextContent(s.env);
    }
  });

  it("no brand.* or other internal key reaches the page", async () => {
    expect(ALL_ROWS.some((s) => s.key.startsWith("brand.") || s.tier === "internal" || s.env_only)).toBe(false);
    mount("settings");
    await showAdvanced();
    await waitFor(() => expect(screen.getAllByTestId("setting-field")).toHaveLength(TOTAL_KEYS));
    expect(document.querySelector('[data-key^="brand."]')).toBeNull();
    expect(screen.queryByText(/EDP_PRODUCT_NAME|EDP_TAGLINE/)).toBeNull();
  });

  it("the header shows no file path until Show where, then the path with a copy button", async () => {
    const view = { ...(SETTINGS as SettingsView), config_file: "C:\\Users\\me\\AppData\\Local\\heronry\\config\\config.toml" };
    mount("settings", [http.get("/v1/admin/settings", () => ok(view))]);
    const header = await screen.findByTestId("settings-header");
    await screen.findAllByTestId("setting-field");
    expect(header).toHaveTextContent("Saved in your Heronry config file. A value set by the environment is locked here.");
    expect(screen.getByTestId("admin-settings")).not.toHaveTextContent("config.toml");
    expect(screen.queryByTestId("settings-config-path")).toBeNull();
    fireEvent.click(screen.getByTestId("settings-show-where"));
    expect(screen.getByTestId("settings-config-path")).toHaveTextContent(view.config_file);
    expect(screen.getByTestId("settings-config-path-copy")).toBeInTheDocument();
  });

  it("group and detail expanders use the app's chevron icon", async () => {
    mount("settings");
    await screen.findAllByTestId("setting-field");
    const groups = (SETTINGS as SettingsView).groups.filter((g) => g.settings.some((s) => s.tier === "basic"));
    for (const g of groups) {
      const summary = screen.getByTestId(`settings-group-${g.group}`).querySelector(":scope > summary")!;
      expect(summary.querySelector('svg[data-icon="chevron"]'), g.group).not.toBeNull();
      expect(summary.textContent).not.toMatch(/[▸▾▶▼›⌄]/);
    }
    for (const d of screen.getAllByText("Advanced details")) expect(d.querySelector('svg[data-icon="chevron"]')).not.toBeNull();
  });

  it("the Capacity card is on Services only", async () => {
    const view = mount("settings");
    await screen.findAllByTestId("setting-field");
    expect(screen.queryByTestId("capacity")).toBeNull();
    expect(screen.queryByTestId("settings-group-capacity")).toBeNull();
    view.unmount();
    mount("services");
    expect(await screen.findByTestId("capacity")).toBeInTheDocument();
  });

  it("Teammates explains inviting in 3 steps and says colleagues can't bring their own agents", async () => {
    mount("teammates", [REMOTE_ON]);
    const steps = await screen.findByTestId("how-inviting-steps");
    const items = within(steps).getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent(/Add their name.*one-time link/);
    expect(items[1]).toHaveTextContent(/tailnet.*Mint key/);
    expect(items[2]).toHaveTextContent(/Send them the link.*Remote access must be on/);
    expect(screen.getByTestId("how-inviting-agents")).toHaveTextContent("seats this board starts on this computer");
    expect(screen.getByTestId("how-inviting-agents")).toHaveTextContent("they can't bring their own");
    fireEvent.change(screen.getByTestId("invite-handle"), { target: { value: "dan" } });
    await waitFor(() => expect(screen.getByTestId("invite-submit")).not.toBeDisabled());
    expect(screen.queryByTestId("invite-off-reason")).toBeNull();
  });

  it("the invite button is disabled with a reason while Remote access is off", async () => {
    mount("teammates");
    fireEvent.change(await screen.findByTestId("invite-handle"), { target: { value: "dan" } });
    expect(await screen.findByTestId("invite-off-reason")).toHaveTextContent("Invite is off while Remote access is off");
    expect(screen.getByTestId("invite-submit")).toBeDisabled();
    expect(screen.getByTestId("invite-submit")).toHaveAttribute("aria-describedby", "invite-off-reason");
    expect(screen.getByTestId("how-inviting-remote-off")).toHaveTextContent("Remote access is off");
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
      "claude-opus-5-5": { harness: "claude", provider: "anthropic", context_window: 200000, auto_compact: 150000, effort_cap: "medium" },
      "gpt-6-sol": { harness: "codex", provider: "openai", context_window: 272000, auto_compact: 200000, effort_cap: "high" },
      "hidden-model": { harness: "pi", provider: "openrouter", context_window: 131072, auto_compact: 100000, effort_cap: "high", extra_key: "kept" },
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

  it("a Codex row without numbers shows Codex default (N) and saves blank as unset (m-ab7426f038)", async () => {
    const cat = structuredClone(CATALOG) as Cat & { harness_defaults?: Record<string, unknown> };
    cat.models["gpt-6-sol"] = { harness: "codex", provider: "codex", effort_cap: "high" };
    cat.harness_defaults = { "gpt-6-sol": { context_window: 272000, auto_compact: 244800, source: "codex debug models" } };
    const s = stateful(cat);
    mount("models", s.handlers);
    expect(await screen.findByTestId("model-window-gpt-6-sol")).toHaveTextContent("Codex default (272,000)");
    expect(screen.getByTestId("model-compact-gpt-6-sol")).toHaveTextContent("Codex default (244,800)");
    expect(screen.getByTestId("model-compact-claude-opus-5-5")).toHaveTextContent("150,000");
    fireEvent.click(screen.getByTestId("model-edit-gpt-6-sol"));
    expect(screen.getByTestId("model-form-compact")).toHaveAttribute("placeholder", "blank = Codex default");
    fireEvent.change(screen.getByTestId("model-form-compact"), { target: { value: "500000" } });
    fireEvent.click(screen.getByTestId("model-form-save"));
    await waitFor(() => expect(s.puts).toHaveLength(1));
    expect(s.puts[0].models["gpt-6-sol"]).toEqual({ harness: "codex", provider: "codex", effort_cap: "high", auto_compact: 500000 });
  });

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
    // a test spawn needs the harness installed (t-20f0718990 greys it with the reason otherwise)
    const PI_IN = http.get("/v1/admin/harnesses", () => ok({ ...HARNESSES, harnesses: HARNESSES.harnesses.map((h) => (h.harness === "pi" ? { ...h, installed: true, version: "0.9.0" } : h)) }));
    mount("models", [PI_IN, ...s.handlers]);
    await screen.findByTestId("model-row-claude-opus-5-5");
    fireEvent.click(screen.getByTestId("model-add"));
    expect(screen.getByTestId("model-form-harness")).toHaveValue("pi");
    fireEvent.change(screen.getByTestId("model-form-id"), { target: { value: "qwen3-coder" } });
    fireEvent.change(screen.getByTestId("model-form-provider"), { target: { value: "openrouter" } });
    fireEvent.change(screen.getByTestId("model-form-window"), { target: { value: "128000" } });
    fireEvent.change(screen.getByTestId("model-form-cap"), { target: { value: "medium" } });
    expect(screen.getByTestId("model-form-problem")).toHaveTextContent("Auto-compact must be a token count below the context window");
    expect(screen.getByTestId("model-form-save")).toBeDisabled();
    fireEvent.change(screen.getByTestId("model-form-compact"), { target: { value: "100000" } });
    fireEvent.click(screen.getByTestId("model-form-save"));
    await waitFor(() => expect(s.puts).toHaveLength(1));
    expect(s.puts[0].models["qwen3-coder"]).toEqual({ harness: "pi", provider: "openrouter", context_window: 128000, auto_compact: 100000, effort_cap: "medium" });
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
    expect(s.puts[0].models["hidden-model"]).toMatchObject({ provider: "groq", context_window: 131072, auto_compact: 100000, extra_key: "kept" });

    server.use(http.put("/v1/admin/models", () => refuse(400, "provider groq has no credential")));
    fireEvent.click(await screen.findByTestId("model-remove-hidden-model"));
    expect(await screen.findByTestId("models-save-error")).toHaveTextContent("no credential");
  });

  it("refuses to remove a role's only model before the PUT", async () => {
    const s = stateful(CATALOG);
    mount("models", s.handlers);
    await screen.findByTestId("model-row-claude-opus-5-5");
    fireEvent.click(screen.getByTestId("model-remove-claude-opus-5-5"));
    expect(screen.getByTestId("models-remove-blocked")).toHaveTextContent("only model of qa");
    expect(s.puts).toHaveLength(0);
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

// t-20f0718990 (owner m-3136ceca05): Admin UX pass 2 — reading order, scope line, Remote access as a guided
// setup, Integrations that explain themselves, and greyed Seats & models choices that say why.
describe("Admin UX pass 2 (t-20f0718990)", () => {
  it("tabs run in the README's reading order and the header states Admin's scope", async () => {
    mount();
    await screen.findByTestId("admin-page");
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Services", "Seats & models", "Teammates", "Remote access", "Integrations", "Settings"]);
    expect(screen.getByText(/For the whole install, admins only/)).toBeInTheDocument();
  });

  it("Remote access is a numbered walk whose steps show live done / not done", async () => {
    mount("remote", [http.get("/v1/admin/tailnet", () => ok({ ...TAILNET, tailscale: null, blockers: 1,
      rows: [{ level: "BLOCKER", area: "admin token", text: "EDP8_ADMIN_TOKEN is unset", fix: "apply generates one" }] }))]);
    const steps = await screen.findByTestId("remote-steps");
    await waitFor(() => expect(screen.getByTestId("remote-backend")).toHaveTextContent("Not detected"));
    expect(screen.getByTestId("remote-step-install-state")).toHaveTextContent("Not done yet");
    expect(steps.querySelectorAll(":scope > li")).toHaveLength(6);
    expect(screen.getByTestId("remote-step-signin-state")).toHaveTextContent("Not done yet");
    expect(screen.getByTestId("remote-backend")).toHaveTextContent("Not detected");
    for (const os of ["Windows", "macOS", "Linux"]) expect(screen.getByTestId(`remote-download-${os}`)).toHaveAttribute("href", expect.stringContaining("tailscale.com/download"));
    // the readiness rows' real fields (area/text/fix) are shown, not blank cells
    expect(screen.getByTestId("remote-blocker-list")).toHaveTextContent("admin token: EDP8_ADMIN_TOKEN is unset");
    expect(screen.getByTestId("remote-apply")).toBeDisabled();
    expect(screen.getByTestId("remote-apply-why")).toHaveTextContent("Finish step 3 first");
    // every step has its diagram
    expect(within(steps).getAllByRole("img")).toHaveLength(6);
  });

  it("a finished setup marks every step done and shows the address", async () => {
    mount("remote", [http.get("/v1/admin/tailnet", () => ok({ ...TAILNET, public_mode: true, public_url: "https://host.tail.ts.net",
      serve_proxies: [{ from: "https://host.tail.ts.net:443", to: "http://127.0.0.1:9400" }], running_public: true }))]);
    for (const s of ["install", "signin", "ready", "serve", "restart"]) {
      await waitFor(() => expect(screen.getByTestId(`remote-step-${s}-state`)).toHaveTextContent(/^Done$/));
    }
    expect(screen.getByTestId("remote-progress")).toHaveTextContent("5 of 5 steps done");
    expect(screen.getByTestId("remote-public-url")).toHaveTextContent("https://host.tail.ts.net");
  });

  it("the written guide opens in place", async () => {
    mount("remote", [http.get("/v1/admin/tailnet/guide", () => ok({ name: "remote-access", path: "guides/remote-access.md", html: "<h1>Remote access</h1><h2>1. What it is for</h2>" }))]);
    const fold = await screen.findByTestId("remote-guide");
    (fold as HTMLDetailsElement).open = true;
    fireEvent(fold, new Event("toggle"));
    expect(await within(fold).findByText("1. What it is for")).toBeInTheDocument();
  });

  it("every integration says what it does, needs, where to get it and what changes, with a status", async () => {
    mount("integrations");
    for (const id of ["harnesses", "vscode", "slack", "plane", "code-server"]) {
      const about = await screen.findByTestId(`about-${id}`);
      for (const line of ["What it does", "What you need", "Where to get it", "Once connected"]) expect(about).toHaveTextContent(line);
      expect(within(about).queryAllByRole("link").length).toBeGreaterThan(0);
    }
    // order: essentials first (README.md)
    const cards = screen.getAllByTestId(/^integration-/).map((c) => c.getAttribute("data-testid"));
    expect(cards).toEqual(["integration-harnesses", "integration-vscode", "integration-slack", "integration-plane", "integration-code-server"]);
    // statuses: codex is signed out -> error with the reason; Slack set up but untested; Plane not set up
    await waitFor(() => expect(screen.getByTestId("harnesses-status")).toHaveTextContent("Error: claude ready; codex not signed in"));
    expect(screen.getByTestId("slack-status")).toHaveTextContent("Set up, not tested yet");
    expect(screen.getByTestId("plane-status")).toHaveTextContent("Not set up");
    // a step that must come first is named next to the disabled action
    expect(screen.getByTestId("plane-test")).toBeDisabled();
    expect(screen.getByTestId("plane-test-why")).toHaveTextContent("then Save Plane");
    expect(screen.getByTestId("harness-pi-update")).toBeDisabled();
    expect(screen.getByTestId("harness-pi-why")).toHaveTextContent("Not installed: install it first");
  });

  it("a Test turns the status into connected (tested) or an error with the reason", async () => {
    mount("integrations", [
      http.post("/v1/admin/integrations/vscode/test", () => ok({ board_url: "http://b" })),
      http.post("/v1/admin/integrations/slack/test", () => refuse(502, "Slack answered 404: no_service")),
    ]);
    fireEvent.click(await screen.findByTestId("vscode-test"));
    expect(await screen.findByTestId("vscode-status")).toHaveTextContent("Connected (tested): the board answers at http://b");
    fireEvent.click(screen.getByTestId("slack-test"));
    await waitFor(() => expect(screen.getByTestId("slack-status")).toHaveTextContent("Error: Slack answered 404: no_service"));
  });

  it("Seats & models: a greyed model or choice says why in visible text", async () => {
    const cat = {
      models: {
        "claude-opus-5-5": { harness: "claude", provider: "anthropic", context_window: 200000, auto_compact: 150000, effort_cap: "medium" },
        "qwen3-coder": { harness: "pi", provider: "openrouter", context_window: 131072, auto_compact: 100000, effort_cap: "high" },
      },
      role_models: { engineer: ["claude-opus-5-5", "qwen3-coder"], doctor: ["claude-opus-5-5"] },
      selected: ["claude", "pi"],
      warnings: [],
    };
    mount("models", [http.get("/v1/admin/models", () => ok(cat))]);
    // pi is not installed in the harness probe
    expect(await screen.findByTestId("model-why-qwen3-coder")).toHaveTextContent("harness not installed");
    expect(screen.getByTestId("role-pick-engineer-qwen3-coder")).toHaveTextContent("harness not installed");
    // the doctor role renders as Help, with its icon
    const doctor = screen.getByTestId("role-models-doctor");
    expect(doctor).toHaveTextContent("Help");
    expect(doctor.querySelector("[data-role-icon=doctor]")).not.toBeNull();
    // test spawn: an uninstalled harness is greyed and says why
    fireEvent.change(screen.getByTestId("test-spawn-model"), { target: { value: "qwen3-coder" } });
    expect(screen.getByTestId("test-spawn-run")).toBeDisabled();
    expect(screen.getByTestId("test-spawn-why")).toHaveTextContent("qwen3-coder: harness not installed");
    // test spawn: an effort above the model's cap is greyed and labelled
    fireEvent.change(screen.getByTestId("test-spawn-model"), { target: { value: "claude-opus-5-5" } });
    const high = within(screen.getByTestId("test-spawn-effort")).getByRole("option", { name: /high/ }) as HTMLOptionElement;
    expect(high.disabled).toBe(true);
    expect(high).toHaveTextContent("above cap");
    // the add form: Claude's greyed high is explained next to the select
    fireEvent.click(screen.getByTestId("model-add"));
    fireEvent.change(screen.getByTestId("model-form-harness"), { target: { value: "claude" } });
    expect(screen.getByTestId("model-form-cap-why")).toHaveTextContent("Claude models are capped at medium");
  });
});
