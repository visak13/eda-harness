import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "../theme/ThemeProvider";
import { AppShell } from "./AppShell";
import { usePageFrame } from "./PageFrame";

// A routed body that declares its framing + the only terms it shows, so the panel can be checked
// for "lists only the terms visible on the current page" (design §15, criterion c-cccc3183db).
function SeatsLikeBody() {
  usePageFrame("See who is available, read their latest status, and message or resume a seat.", [
    { category: "concept", value: "seat" },
    { category: "concept", value: "presence" },
    { category: "role", value: "engineer" },
  ]);
  return <div>seats body</div>;
}

function renderShell(initial = "/me", body: React.ReactNode = <div>decisions body</div>) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <MemoryRouter initialEntries={[initial]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="me" element={<div>decisions body</div>} />
              <Route path="seats" element={body} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => localStorage.clear());

describe("page framing landmark", () => {
  it("renders a page-framing sentence inside the main landmark on every route", () => {
    renderShell("/me");
    const main = screen.getByRole("main");
    const framing = within(main).getByTestId("page-framing");
    expect(framing).toHaveTextContent("Decisions collects requests that need your action.");
  });

  it("uses the page's own framing when a page declares one", () => {
    renderShell("/seats", <SeatsLikeBody />);
    expect(within(screen.getByRole("main")).getByTestId("page-framing")).toHaveTextContent(
      "message or resume a seat",
    );
  });
});

describe("What am I looking at? panel", () => {
  it("opens from the header ? button and closes on its close button", () => {
    renderShell("/me");
    expect(screen.queryByRole("dialog", { name: "What am I looking at?" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("glossary-open"));
    const dialog = screen.getByRole("dialog", { name: "What am I looking at?" });
    expect(dialog).toBeInTheDocument();
    // Fallback (no page terms) lists the full glossary — ticket stages present.
    expect(within(dialog).getByText("In progress")).toBeInTheDocument();
    expect(within(dialog).getByText("A request for an answer.")).toBeInTheDocument(); // Question meaning
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog", { name: "What am I looking at?" })).not.toBeInTheDocument();
  });

  it("Ctrl-/ toggles the panel open and closed", () => {
    renderShell("/me");
    fireEvent.keyDown(document, { key: "/", ctrlKey: true });
    expect(screen.getByRole("dialog", { name: "What am I looking at?" })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "/", ctrlKey: true });
    expect(screen.queryByRole("dialog", { name: "What am I looking at?" })).not.toBeInTheDocument();
  });

  it("Esc closes the panel and restores focus to the opener", () => {
    renderShell("/me");
    const opener = screen.getByTestId("glossary-open");
    fireEvent.click(opener);
    expect(screen.getByRole("dialog", { name: "What am I looking at?" })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "What am I looking at?" })).not.toBeInTheDocument();
    expect(document.activeElement).toBe(opener);
  });

  it("lists ONLY the terms the current page declares", () => {
    renderShell("/seats", <SeatsLikeBody />);
    fireEvent.click(screen.getByTestId("glossary-open"));
    const dialog = screen.getByRole("dialog", { name: "What am I looking at?" });
    // Declared: role engineer + concept seat/presence. Present:
    expect(within(dialog).getByText("Engineer")).toBeInTheDocument();
    expect(within(dialog).getByText(/An agent assigned to work\./, { exact: false })).toBeInTheDocument(); // seat
    // NOT declared: ticket stages must be absent.
    expect(within(dialog).queryByText("In progress")).not.toBeInTheDocument();
    expect(within(dialog).queryByText("A request for an answer.")).not.toBeInTheDocument();
  });
});
