import { describe, it, expect, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";
import { http, HttpResponse } from "msw";
import { server } from "./setup";
import { ThemeProvider } from "../theme/ThemeProvider";
import { appRoutes } from "../routes";
import { boardNewerThanPage, buildStamp, needsBoardRestart, resetLoadedVersion, sameRev, semverNewer } from "../live/boardVersion";

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

  it("boardNewerThanPage is judged by release version only: the board is newer than the page, or than what the page first saw", () => {
    const v = { ...build, version: "0.10.6" };
    expect(boardNewerThanPage(v, { version: "0.10.7", git_rev: "bbbbbbb" }, null)).toBe(true); // board 0.10.7 against page 0.10.6
    expect(boardNewerThanPage(v, { version: "0.10.6", git_rev: "v0.10.6" }, null)).toBe(false); // a tag in git_rev, a sha in the build: same release
    expect(boardNewerThanPage(v, { version: "0.10.6", git_rev: "ccccccc", started_at: "2026-09-27T02:00:00Z" }, null)).toBe(false); // other rev, same release
    expect(boardNewerThanPage(v, { version: "0.10.5", git_rev: "bbbbbbb" }, "0.10.5")).toBe(false); // the page is the newer one
    expect(boardNewerThanPage(v, { version: "0.10.6" }, "0.10.5")).toBe(false); // the bundle's own release is the page's; what it first saw does not matter
    expect(boardNewerThanPage({ ...build }, { version: "0.10.6" }, "0.10.5")).toBe(true); // no bundle version: the version moved since the page loaded
    expect(boardNewerThanPage(null, { version: "0.10.6" }, "0.10.6")).toBe(false); // dev server, nothing moved
    expect(boardNewerThanPage(v, undefined, "0.10.5")).toBe(false);
    expect(boardNewerThanPage(v, { git_rev: "ccccccc" }, null)).toBe(false); // no version reported: stay quiet
  });

  it("semverNewer compares releases numerically", () => {
    expect(semverNewer("0.10.7", "0.10.6")).toBe(true);
    expect(semverNewer("0.11.0", "0.10.9")).toBe(true);
    expect(semverNewer("0.9.9", "0.10.0")).toBe(false); // not a string compare
    expect(semverNewer("0.10.6", "0.10.6")).toBe(false);
    expect(semverNewer("v0.10.7-rc1", "0.10.6")).toBe(true);
    expect(semverNewer("nonsense", "0.10.6")).toBe(false);
    expect(semverNewer("0.10.7", null)).toBe(false);
  });

  it("a tag in the board's git_rev never reads as a build the board lacks", () => {
    expect(needsBoardRestart(build, { git_rev: "v0.10.6", started_at: "2026-09-27T00:00:00Z" })).toBe(false);
  });

  it("a 7-character build rev and a 12-character board rev name the same commit", () => {
    expect(sameRev("ed9e269", "ed9e269abcde")).toBe(true);
    expect(sameRev("ed9e269", "aaaaaaa00000")).toBe(false);
    expect(boardNewerThanPage(build, { git_rev: "bbbbbbb12345", started_at: "2026-09-27T02:00:00Z" }, null)).toBe(false);
    expect(boardNewerThanPage(build, { git_rev: "unknown", started_at: "2026-09-27T02:00:00Z" }, null)).toBe(false);
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

  it("a page open across an update shows a non-blocking reload banner once /v1/health reports a newer release, and a reload clears it", async () => {
    resetLoadedVersion();
    const pageVersion = buildStamp()!.version!;
    const [maj, min, patch] = pageVersion.split(".").map(Number);
    let version = pageVersion;
    const reload = vi.fn();
    vi.spyOn(window, "location", "get").mockReturnValue({ ...window.location, reload } as Location);
    server.use(
      // git_rev is a TAG, as the installed board reports it: it must not matter
      http.get("/v1/health", () => HttpResponse.json({ ok: true, version, git_rev: "v" + version, started_at: "2000-01-01T00:00:00Z" })),
      http.get("/v1/whoami", () => ok(WHO)), http.get("/v1/me/summary", () => ok({})), http.get("/v1/*", () => ok([])),
    );
    mount("/epics");
    await waitFor(() => expect(screen.getByTestId("page-framing")).toHaveAttribute("data-route", "/epics"));
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByTestId("board-updated-banner")).toBeNull(); // tag vs sha at the same release: no banner
    version = `${maj}.${min}.${patch + 1}`; // the board is updated while the page stays open; the next focus re-checks
    window.dispatchEvent(new Event("visibilitychange")); // react-query's focus manager listens on window
    window.dispatchEvent(new Event("focus"));
    const banner = await screen.findByTestId("board-updated-banner"); // board newer than the page
    expect(banner).toHaveAttribute("role", "status");
    expect(banner).toHaveTextContent("Heronry was updated. Reload to get the new version.");
    fireEvent.click(within(banner).getByRole("button", { name: "Reload" }));
    expect(reload).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("page-framing")).toBeInTheDocument(); // the page is not blocked
    vi.restoreAllMocks();
  });

  it("after a reload (a page built for the board's release) the banner is gone", async () => {
    resetLoadedVersion();
    cleanup(); // the old page is gone; the reloaded one is built at the release the board now runs
    const pageVersion = buildStamp()!.version!;
    server.use(
      http.get("/v1/health", () => HttpResponse.json({ ok: true, version: pageVersion, git_rev: "v" + pageVersion, started_at: "2999-01-01T00:00:00Z" })),
      http.get("/v1/whoami", () => ok(WHO)), http.get("/v1/me/summary", () => ok({})), http.get("/v1/*", () => ok([])),
    );
    mount("/epics");
    await waitFor(() => expect(screen.getByTestId("page-framing")).toHaveAttribute("data-route", "/epics"));
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByTestId("board-updated-banner")).toBeNull();
    expect(screen.queryByTestId("board-behind-banner")).toBeNull();
  });

  it("an OLD open tab (the board runs a newer release than this bundle) shows the reload banner and not the restart one", async () => {
    resetLoadedVersion();
    server.use(
      http.get("/v1/health", () => HttpResponse.json({ ok: true, version: "999.0.0", git_rev: "v999.0.0", started_at: "2999-01-01T00:00:00Z" })),
      http.get("/v1/whoami", () => ok(WHO)), http.get("/v1/me/summary", () => ok({})), http.get("/v1/*", () => ok([])),
    );
    mount("/epics");
    const banner = await screen.findByTestId("board-updated-banner");
    expect(banner).toHaveTextContent("Heronry was updated. Reload to get the new version.");
    expect(screen.queryByTestId("board-behind-banner")).toBeNull();
  });

  it("no banner when the board started after this bundle was built", async () => {
    server.use(http.get("/v1/whoami", () => ok(WHO)), http.get("/v1/me/summary", () => ok({})), http.get("/v1/*", () => ok([])));
    mount("/epics");
    await waitFor(() => expect(screen.getByTestId("page-framing")).toHaveAttribute("data-route", "/epics"));
    await new Promise((r) => setTimeout(r, 50)); // let the health query settle
    expect(screen.queryByTestId("board-behind-banner")).toBeNull();
  });
});
