import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import { ThemeProvider } from "../theme/ThemeProvider";
import { AppShell } from "./AppShell";

function renderShell(initial = "/me") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <MemoryRouter initialEntries={[initial]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="me" element={<div>decisions body</div>} />
              <Route path="epics" element={<div>epics body</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});

describe("AppShell", () => {
  it("renders the four nav sections in order with the current route active", async () => {
    renderShell("/me");
    const links = screen.getAllByRole("link");
    expect(links.map((l) => l.textContent?.replace(/\d+$/, "").trim())).toEqual([
      "Decisions",
      "Epics",
      "Seats",
      "Library",
    ]);
    // NavLink marks the active route with aria-current=page.
    expect(screen.getByRole("link", { name: /Decisions/ })).toHaveAttribute("aria-current", "page");
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
    expect(screen.getByRole("link", { name: /Decisions/ })).toBeInTheDocument();
  });

  it("shows identity (as) and the whoami handle", async () => {
    renderShell("/me");
    expect(screen.getByTestId("identity")).toHaveTextContent("owner");
    expect(await screen.findByTestId("whoami-handle")).toHaveTextContent("owner");
  });

  it("opens the identity popover to the ThemePicker and can switch theme", async () => {
    renderShell("/me");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Account and preferences" }));
    const dialog = screen.getByRole("dialog", { name: "Preferences" });
    expect(dialog).toBeInTheDocument();
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
    expect(await screen.findByText("Board redesign")).toBeInTheDocument();
    expect(screen.getByText("In view")).toBeInTheDocument();
  });

  it("renders the routed page body through the Outlet", async () => {
    renderShell("/epics");
    await waitFor(() => expect(screen.getByText("epics body")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /Epics/ })).toHaveAttribute("aria-current", "page");
  });
});
