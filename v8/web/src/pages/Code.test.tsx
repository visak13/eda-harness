import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import type { CodeStatus } from "../api/types";
import { CodeFaqPage, CodePage } from "./Code";

// epic-91fcd3b370 S3: the Code tab — the iframe comes from GET /v1/code (never a hard-coded port),
// a stopped service is a named state with the start command (never a blank frame), a remote browser
// is told the editor runs on the board host only, and a deep link reaches the iframe URL.

const ok = (value: unknown) => HttpResponse.json({ ok: true, value, hint: "" });
const STATUS: CodeStatus = {
  port: 9555, url: "http://127.0.0.1:9555/", running: true, version: "4.138.0",
  default_folder: "C:\\Projects\\Learning\\eda-base3\\v8", start_command: ".\\edp.ps1 start code",
};

function mount(path = "/code", status: Partial<CodeStatus> | "error" = {}, hostname?: string) {
  let calls = 0;
  server.use(http.get("/v1/code", () => {
    calls += 1;
    return status === "error"
      ? HttpResponse.json({ ok: false, error: { code: "http", message: "board down" }, hint: "" }, { status: 502 })
      : ok({ ...STATUS, ...status });
  }));
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="code" element={<CodePage hostname={hostname} />} />
          <Route path="code/faq" element={<CodeFaqPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { calls: () => calls };
}

describe("CodePage", () => {
  it("embeds code-server at the port the board reports with no folder, so it reopens its last folder", async () => {
    mount();
    const frame = await screen.findByTestId("code-frame");
    expect(frame.getAttribute("src")).toBe("http://127.0.0.1:9555/");
    expect(screen.getByTestId("code-state")).toHaveTextContent("code-server 4.138.0 · running");
    expect(screen.getByTestId("code-newwindow")).toHaveAttribute("href", frame.getAttribute("src"));
    expect(screen.getByTestId("code-newwindow")).toHaveAttribute("target", "_blank");
    expect(screen.getByRole("heading", { level: 1, name: "Code" })).toBeInTheDocument();
  });

  it("a deep link opens the folder and the file at the range's start line, and shows the range", async () => {
    mount("/code?folder=C%3A%5CProjects%5Cv8&file=src%2Fedp8%2Fboard.py&line=10-20");
    const src = (await screen.findByTestId("code-frame")).getAttribute("src")!;
    const u = new URL(src);
    expect(u.searchParams.get("folder")).toBe("/c:/Projects/v8");
    expect(JSON.parse(u.searchParams.get("payload")!)).toEqual([
      ["openFile", "vscode-remote://127.0.0.1:9555/c:/Projects/v8/src/edp8/board.py:10"],
      ["gotoLineMode", "true"],
    ]);
    expect(screen.getByTestId("code-where")).toHaveTextContent("src/edp8/board.py L10–20");
    expect(screen.queryByTestId("code-invalid")).toBeNull();
  });

  it("names the parameters it had to ignore", async () => {
    mount("/code?folder=relative&line=abc");
    await screen.findByTestId("code-frame");
    expect(screen.getByTestId("code-invalid")).toHaveTextContent("Ignored: folder, line");
  });

  it("down: says the service is not running, names the start command, and Retry asks again — no frame", async () => {
    const m = mount("/code", { running: false, version: null });
    expect(await screen.findByTestId("code-down")).toHaveTextContent("Code service is not running");
    expect(screen.getByTestId("code-start-command")).toHaveTextContent(".\\edp.ps1 start code");
    expect(screen.queryByTestId("code-frame")).toBeNull();
    expect(screen.queryByTestId("code-newwindow")).toBeNull();
    expect(screen.getByTestId("code-state")).toHaveTextContent("not running");
    expect(screen.getByTestId("code-faq")).toHaveAttribute("href", "/code/faq");
    const before = m.calls();
    fireEvent.click(screen.getByTestId("code-retry"));
    await waitFor(() => expect(m.calls()).toBeGreaterThan(before));
  });

  it("a board error is its own state with Retry, never a blank frame", async () => {
    mount("/code", "error");
    expect(await screen.findByTestId("code-board-error")).toHaveTextContent("The board did not answer");
    expect(screen.queryByTestId("code-frame")).toBeNull();
  });

  it("a browser off the board host is told the editor runs on the host only", async () => {
    mount("/code", {}, "192.168.1.20");
    expect(await screen.findByTestId("code-host-only")).toHaveTextContent("Code runs on the board host only");
    expect(screen.queryByTestId("code-frame")).toBeNull();
    expect(screen.queryByTestId("code-newwindow")).toBeNull();
  });
});

describe("CodeFaqPage", () => {
  it("renders the FAQ the board serves and links back to the tab", async () => {
    server.use(http.get("/v1/code/faq", () => ok({ name: "code-tab-faq", path: "guides/code-tab-faq.md", html: "<h1>Code tab FAQ</h1><h2>The shared tree and live seats</h2>" })));
    mount("/code/faq");
    expect(await screen.findByText("The shared tree and live seats")).toBeInTheDocument();
    expect(screen.getByTestId("code-faq-back")).toHaveAttribute("href", "/code");
  });
});
