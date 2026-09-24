import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import { ThemeProvider } from "../theme/ThemeProvider";
import { AppShell } from "./AppShell";
import { EpicsPage } from "../pages/Epics";

function renderShell(initial = "/me", epicsBody: React.ReactNode = <div>epics body</div>) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <MemoryRouter initialEntries={[initial]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="me" element={<div>decisions body</div>} />
              <Route path="epics" element={epicsBody} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
  server.use(http.get("/v1/me/avatar", () => HttpResponse.json({ ok: true, value: { catalog: [] } })));
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});

describe("AppShell", () => {
  it("renders Epics, Seats, Library and Needs you (one Library destination)", async () => {
    renderShell("/me");
    const links = screen.getAllByRole("link");
    expect(links.map((l) => l.textContent?.replace(/\d+$/, "").trim())).toEqual([
      "Epics",
      "Seats",
      "Library",
      "Needs you",
    ]);
    // NavLink marks the active route with aria-current=page.
    expect(screen.getByRole("link", { name: /Needs you/ })).toHaveAttribute("aria-current", "page");
  });

  it("renders nav counts when /v1/me/summary provides them", async () => {
    server.use(
      http.get("/v1/me/summary", () =>
        HttpResponse.json({ ok: true, value: { decisions: 3, epics: 5, seats: 2, library: 9 } }),
      ),
    );
    renderShell("/me");
    expect(await screen.findByText("3")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
  });

  it("works with no counts when summary is unavailable (G1a not landed)", async () => {
    server.use(http.get("/v1/me/summary", () => HttpResponse.json({ ok: false, hint: "no route" }, { status: 404 })));
    renderShell("/me");
    // The shell still renders its nav; counts are simply absent.
    expect(screen.getByRole("link", { name: /Needs you/ })).toBeInTheDocument();
  });

  it("shows identity (as) on the account row; the whoami role sits under it once resolved", async () => {
    renderShell("/me");
    expect(screen.getByTestId("identity")).toHaveTextContent("owner");
    // whoami resolves handle=owner (same as ?as=) → the row shows the role rather than repeating the handle
    await waitFor(() => expect(screen.getByTestId("whoami-handle")).toHaveTextContent(/owner|member/));
    expect(screen.getByTestId("account-open")).toHaveTextContent("Preferences");
  });

  it("shows the inline identity panel when whoami returns 401 (design §4.1)", async () => {
    server.use(
      http.get("/v1/whoami", () =>
        HttpResponse.json(
          { ok: false, error: "X-Token required for human participant 'owner'", hint: "check your token" },
          { status: 401 },
        ),
      ),
    );
    renderShell("/me");
    expect(await screen.findByTestId("identity-panel")).toBeInTheDocument();
    expect(screen.getByTestId("identity-hint")).toHaveTextContent("check your token");
    // The shell chrome is NOT rendered while identity is unresolved (no silent `as` fallback).
    expect(screen.queryByRole("link", { name: /Needs you/ })).not.toBeInTheDocument();
  });

  it("hides Epics, Seats and Needs you for an expert (whoami answers 403) — t-3e246b5e32 (e)", async () => {
    server.use(
      http.get("/v1/whoami", () =>
        HttpResponse.json({ ok: false, error: "expert 'dana' reaches only its Library topic" }, { status: 403 }),
      ),
    );
    renderShell("/me");
    await waitFor(() => expect(screen.queryByRole("link", { name: /Needs you/ })).not.toBeInTheDocument());
    const names = screen.getAllByRole("link").map((l) => l.textContent?.replace(/\d+$/, "").trim());
    expect(names).toEqual(["Library"]);
    expect(screen.queryByTestId("identity-panel")).not.toBeInTheDocument();
  });

  it("opens the account menu (Settings, ThemePicker) from the rail's account row and can switch theme", async () => {
    renderShell("/me");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Account and preferences" }));
    const dialog = screen.getByRole("dialog", { name: "Account and preferences" });
    expect(dialog).toBeInTheDocument();
    // the Settings page (s-7f663c6322) launches from this menu
    expect(within(dialog).getByTestId("settings-open")).toHaveAttribute("href", "/settings");
    // S17 c-066a9b347a: help is the floating top-right button and Notifications moved to Settings.
    expect(within(dialog).queryByTestId("glossary-open")).toBeNull();
    expect(within(dialog).queryByRole("button", { name: "Enable notifications" })).toBeNull();
    expect(screen.getByRole("button", { name: "What am I looking at? (Ctrl /)" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "Ember" }));
    expect(document.documentElement.dataset.theme).toBe("ember");
  });

  it("lists in-view epics when the endpoint returns some", async () => {
    server.use(
      http.get("/v1/epics/summary", () =>
        HttpResponse.json({ ok: true, value: [{ id: "e1", title: "Board redesign" }] }),
      ),
    );
    renderShell("/me");
    // The former "In view" block is gone (human report 2026-09-10): epic words are not navigation
    // and overflowed the rail. Nothing from /v1/epics/summary renders in the shell any more.
    await screen.findByTestId("identity");
    expect(screen.queryByText("In view")).toBeNull();
    expect(screen.queryByText("Board redesign")).toBeNull();
  });

  it("renders the routed page body through the Outlet", async () => {
    renderShell("/epics");
    await waitFor(() => expect(screen.getByText("epics body")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /Epics/ })).toHaveAttribute("aria-current", "page");
  });
});

// Human #38 (m-4e303d7b27): the sidebar highlight follows the ROUTE FAMILY. Epic and ticket pages
// keep "Epics" lit; every Library tab, a doc page and an artifact page keep "Library" lit; a seat
// deep-link keeps "Seats". Exactly one nav link is current on each.
describe("AppShell nav route families (human #38)", () => {
  function renderAt(path: string) {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={qc}>
        <ThemeProvider>
          <MemoryRouter initialEntries={[path]}>
            <Routes>
              <Route element={<AppShell />}>
                <Route path="*" element={<div>body</div>} />
              </Route>
            </Routes>
          </MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>,
    );
  }
  const cases: Array<[string, string]> = [
    ["/me", "Needs you"],
    ["/epics", "Epics"],
    ["/epic/epic-1b289d63f9", "Epics"],
    ["/ticket/s-abc", "Epics"],
    ["/seats", "Seats"],
    ["/seats#engineer.s-1", "Seats"],
    ["/library/knowledge", "Library"],
    ["/library/tickets", "Library"],
    ["/doc/strategyhl-1", "Library"],

  ];
  for (const [path, label] of cases) {
    it(`${path} lights ${label} only`, async () => {
      renderAt(path);
      await screen.findByRole("link", { name: new RegExp(label) });
      const current = screen.getAllByRole("link").filter((l) => l.getAttribute("aria-current") === "page");
      expect(current.map((l) => l.textContent?.replace(/\d+$/, "").trim())).toEqual([label]);
    });
  }
  it("/unknown lights nothing", async () => {
    renderAt("/nowhere");
    await screen.findByRole("link", { name: /Needs you/ });
    expect(screen.getAllByRole("link").filter((l) => l.getAttribute("aria-current") === "page")).toEqual([]);
  });
});

// Human #22: the "New epic" button opens the dialog (it used to be a dead plate control). It now
// lives on the Epics page (design-a2e5369133: no global header), reached through the shell's Outlet.
describe("AppShell New epic (human #22)", () => {
  it("opens the New epic dialog from the Epics page button", async () => {
    server.use(http.get("/v1/pool/capabilities", () => HttpResponse.json({ ok: true, value: { spawn: true } })));
    server.use(http.get("/v1/epics/summary", () => HttpResponse.json({ ok: true, value: [] })));
    renderShell("/epics", <EpicsPage />);
    const btn = await screen.findByTestId("new-epic-open");
    expect(btn).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(btn);
    expect(await screen.findByRole("dialog", { name: "New epic" })).toBeInTheDocument();
    expect(btn).toHaveAttribute("aria-expanded", "true");
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "New epic" })).not.toBeInTheDocument());
  });
});

// S17 c-33ffd96baf: the rail collapses to an icon rail with a visible control, remembered per viewer.
describe("rail collapse (S17)", () => {
  it("toggles the rail, keeps item names accessible, and remembers the choice", async () => {
    localStorage.clear();
    const view = renderShell("/me");
    const toggle = screen.getByRole("button", { name: "Collapse menu" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Expand menu" })).toHaveAttribute("aria-expanded", "false");
    expect(document.querySelector('[data-rail="collapsed"]')).not.toBeNull();
    expect(screen.getByRole("link", { name: /Epics/ })).toBeInTheDocument(); // label clipped, still named
    expect(Object.keys(localStorage).some((k) => k.endsWith(".rail-collapsed") && localStorage.getItem(k) === "1")).toBe(true);
    view.unmount();
    renderShell("/me");
    expect(screen.getByRole("button", { name: "Expand menu" })).toBeInTheDocument();
  });
});
