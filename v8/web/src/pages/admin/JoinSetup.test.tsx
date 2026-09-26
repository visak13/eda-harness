import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";
import { http, HttpResponse } from "msw";
import { server } from "../../test/setup";
import { ThemeProvider } from "../../theme/ThemeProvider";

// /ui/join and /ui/setup (S6 s-e6b4fa59d5): identity.ts redeems ?code= before first paint; the pages report it.
const redeem = vi.hoisted(() => ({ value: null as null | { path: string; ok: boolean; message?: string } }));
vi.mock("../../auth/identity", async (orig) => ({ ...(await orig<typeof import("../../auth/identity")>()), codeRedeem: () => redeem.value }));

import { JoinPage } from "./Join";
import { SetupPage } from "./Setup";

const ok = (value: unknown, hint = "") => HttpResponse.json({ ok: true, value, hint });
const WHO = (handle: string, admin: boolean) => ({ participant: { id: handle, handle, role: "owner", type: "human" }, tickets: [], admin });

function mount(path: string, el: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const router = createMemoryRouter([{ path: path.split("?")[0], element: el }, { path: "/epics", element: <p data-testid="epics-page">epics</p> }], { initialEntries: [path] });
  render(<QueryClientProvider client={qc}><ThemeProvider><RouterProvider router={router} /></ThemeProvider></QueryClientProvider>);
}

beforeEach(() => { redeem.value = null; });

describe("JoinPage", () => {
  it("a redeemed invite lands signed in", async () => {
    redeem.value = { path: "/ui/join", ok: true };
    server.use(http.get("/v1/whoami", () => ok(WHO("carol", false))));
    mount("/join", <JoinPage />);
    expect(await screen.findByTestId("join-ok")).toHaveTextContent("You are signed in as carol");
    expect(screen.getByTestId("join-open-board")).toHaveAttribute("href", "/me");
  });

  it("a used or expired code shows the board's refusal", async () => {
    redeem.value = { path: "/ui/join", ok: false, message: "this invite code was already used" };
    server.use(http.get("/v1/whoami", () => HttpResponse.json({ ok: false, error: { code: "http", message: "sign in" } }, { status: 401 })));
    mount("/join", <JoinPage />);
    expect(await screen.findByTestId("join-error")).toHaveTextContent("this invite code was already used");
    expect(screen.queryByTestId("join-ok")).toBeNull();
  });

  it("no code and no session says how to join", async () => {
    server.use(http.get("/v1/whoami", () => HttpResponse.json({ ok: false, error: { code: "http", message: "sign in" } }, { status: 401 })));
    mount("/join", <JoinPage />);
    expect(await screen.findByTestId("join-nocode")).toBeInTheDocument();
  });
});

describe("SetupPage wizard", () => {
  const HARN = { harnesses: [{ harness: "claude", selected: true, installed: true, version: "2.1.0", live_seats: [] }, { harness: "codex", selected: false, installed: false, live_seats: [] }],
    selected: ["claude"], fable_ack: null, fable_notice: "Codex is not selected, so the adversary role runs on Fable (claude-fable-5-1)." };
  const TAIL = { tailscale: null, serve: null, serve_proxies: [], public_url: null, tailnet_url: null, public_mode: false, rows: [], blockers: 1, auth_keys: { configured: false } };

  it("walks sign-in → harnesses (Fable notice without codex) → remote → teammate → done, and marks setup done", async () => {
    let selection: unknown = null;
    let done = false;
    let invited: unknown = null;
    server.use(
      http.get("/v1/whoami", () => ok(WHO("owner", true))),
      http.get("/v1/admin/harnesses", () => ok(HARN)),
      http.put("/v1/admin/harnesses/selection", async ({ request }) => { selection = await request.json(); return ok({ selected: ["claude"], fable_ack: { by: "owner" }, restart_required: [] }, "saved"); }),
      http.get("/v1/admin/tailnet", () => ok(TAIL)),
      http.post("/v1/admin/teammates", async ({ request }) => { invited = await request.json(); return ok({ teammate: {}, invite: { link: "http://b/ui/join?code=q", vscode_link: "vscode://edp.edp-code/signin?code=q", code: "q", expires_at: "" } }); }),
      http.post("/v1/admin/setup/done", () => { done = true; return ok({ done: true }); }),
    );
    mount("/setup", <SetupPage />);
    expect(await screen.findByTestId("setup-signed-in")).toHaveTextContent("owner");
    fireEvent.click(screen.getByTestId("setup-next"));
    expect(await screen.findByTestId("fable-notice")).toHaveTextContent("adversary role runs on Fable");
    expect(screen.getByTestId("harness-selection-save")).toBeDisabled();
    fireEvent.click(screen.getByTestId("fable-ack"));
    fireEvent.click(screen.getByTestId("harness-selection-save"));
    await waitFor(() => expect(selection).toEqual({ harnesses: ["claude"], fable_ack: true }));
    expect(await screen.findByTestId("setup-remote-status")).toHaveTextContent("not running here");
    fireEvent.click(screen.getByTestId("setup-next"));
    fireEvent.change(await screen.findByTestId("setup-teammate-handle"), { target: { value: "carol" } });
    fireEvent.click(screen.getByTestId("setup-teammate-invite"));
    expect(await screen.findByTestId("setup-invite-link")).toHaveTextContent("http://b/ui/join?code=q");
    expect(invited).toEqual({ handle: "carol" });
    fireEvent.click(screen.getByTestId("setup-next"));
    fireEvent.click(await screen.findByTestId("setup-finish"));
    expect(await screen.findByTestId("epics-page")).toBeInTheDocument();
    expect(done).toBe(true);
  });

  it("a non-admin cannot pass sign-in", async () => {
    server.use(http.get("/v1/whoami", () => ok(WHO("bob", false))));
    mount("/setup", <SetupPage />);
    expect(await screen.findByTestId("setup-not-admin")).toHaveTextContent("bob is not an admin");
    expect(screen.queryByTestId("setup-next")).toBeNull();
  });

  it("shows a refused setup code from the start link", async () => {
    redeem.value = { path: "/ui/setup", ok: false, message: "this sign-in code has expired" };
    server.use(http.get("/v1/whoami", () => HttpResponse.json({ ok: false, error: { code: "http", message: "sign in" } }, { status: 401 })));
    mount("/setup", <SetupPage />);
    expect(await screen.findByTestId("setup-code-error")).toHaveTextContent("this sign-in code has expired");
    expect(screen.getByTestId("setup-signin-submit")).toBeDisabled();
  });
});
