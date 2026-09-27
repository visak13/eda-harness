import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";
import { http, HttpResponse } from "msw";
import { server } from "./setup";
import { ThemeProvider } from "../theme/ThemeProvider";
import { appRoutes } from "../routes";
import { buildStamp, needsBoardRestart } from "../live/boardVersion";

// t-b2f8859d30 (owner art-678346d6e2): a bundle ahead of the board crashed /ui/design with the router's full-screen
// "Unexpected Application Error!". Now a page's render error is a card in the page's place with the rail still
// working, and a bundle built after the board started shows a quiet restart banner.

// The Design page is replaced by one that throws the owner's exact error, so the boundary is proven on the real
// route table (routes.tsx), inside the real shell.
vi.mock("../pages/design/Design", () => ({
  DesignPage: () => { throw new TypeError("can't access property 'length', e.pinned_by is undefined"); },
}));

const ok = (value: unknown) => HttpResponse.json({ ok: true, value, hint: "" });
const WHO = { participant: { id: "owner", handle: "owner", role: "owner", type: "human" }, tickets: [], admin: true };

function mount(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(appRoutes, { initialEntries: [path] });
  render(<QueryClientProvider client={qc}><ThemeProvider><RouterProvider router={router} /></ThemeProvider></QueryClientProvider>);
  return router;
}

describe("needsBoardRestart", () => {
  const build = { rev: "bbbbbbb", dirty: false, at: "2026-09-27T01:00:00Z" };
  it("is true only when the bundle was built after the board started and differs from it", () => {
    expect(needsBoardRestart(build, { git_rev: "aaaaaaa", started_at: "2026-09-27T00:00:00Z" })).toBe(true);
    expect(needsBoardRestart(build, { git_rev: "aaaaaaa", started_at: "2026-09-27T02:00:00Z" })).toBe(false); // board restarted since
    expect(needsBoardRestart(build, { git_rev: "bbbbbbb", started_at: "2026-09-27T00:00:00Z" })).toBe(false); // same clean rev
    expect(needsBoardRestart({ ...build, dirty: true }, { git_rev: "bbbbbbb", started_at: "2026-09-27T00:00:00Z" })).toBe(true);
    expect(needsBoardRestart(null, { git_rev: "aaaaaaa", started_at: "2026-09-27T00:00:00Z" })).toBe(false); // dev server
    expect(needsBoardRestart(build, { git_rev: "aaaaaaa" })).toBe(false); // no started_at: unknown, stay quiet
  });

  it("the build stamps this bundle (vite define)", () => {
    const s = buildStamp();
    expect(s?.rev).toMatch(/\S/);
    expect(Number.isNaN(Date.parse(s?.at ?? ""))).toBe(false);
  });
});

describe("the SPA never crashes ahead of the board", () => {
  it("a page render error shows the inline error card and the rail still works", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {}); // React reports the caught render error
    server.use(http.get("/v1/whoami", () => ok(WHO)), http.get("/v1/me/summary", () => ok({})), http.get("/v1/*", () => ok([])));
    const router = mount("/design");
    const card = await screen.findByTestId("page-error");
    expect(card).toHaveAttribute("role", "alert");
    expect(within(card).getByTestId("page-error-message")).toHaveTextContent("e.pinned_by is undefined");
    expect(within(card).getByTestId("page-error-reload")).toHaveTextContent("Reload this page");
    expect(screen.queryByText(/Unexpected Application Error/)).toBeNull();
    // the shell is still there: the rail answers, and moving to another page clears the error
    const rail = screen.getByRole("link", { name: /^Epics/ });
    fireEvent.click(rail);
    await waitFor(() => expect(router.state.location.pathname).toBe("/epics"));
    await waitFor(() => expect(screen.queryByTestId("page-error")).toBeNull());
    expect(screen.getByTestId("page-framing")).toHaveAttribute("data-route", "/epics");
  });

  it("a bundle built after the board started shows the restart banner, not a crash", async () => {
    server.use(
      http.get("/v1/health", () => HttpResponse.json({ ok: true, git_rev: "0000000", started_at: "2000-01-01T00:00:00Z" })),
      http.get("/v1/whoami", () => ok(WHO)), http.get("/v1/me/summary", () => ok({})), http.get("/v1/*", () => ok([])),
    );
    mount("/epics");
    const banner = await screen.findByTestId("board-behind-banner");
    expect(banner).toHaveAttribute("role", "status");
    expect(banner).toHaveTextContent("This page needs a board restart (admin)");
  });

  it("no banner when the board started after this bundle was built", async () => {
    server.use(http.get("/v1/whoami", () => ok(WHO)), http.get("/v1/me/summary", () => ok({})), http.get("/v1/*", () => ok([])));
    mount("/epics");
    await waitFor(() => expect(screen.getByTestId("page-framing")).toHaveAttribute("data-route", "/epics"));
    await new Promise((r) => setTimeout(r, 50)); // let the health query settle
    expect(screen.queryByTestId("board-behind-banner")).toBeNull();
  });
});
