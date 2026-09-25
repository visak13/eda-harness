import { describe, it, expect, vi } from "vitest";
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

function mount(path = "/code", status: Partial<CodeStatus> | "error" = {}, hostname = "127.0.0.1", mint: "ok" | "forbidden" = "ok") {
  let calls = 0;
  let mints = 0;
  server.use(http.get("/v1/code", () => {
    calls += 1;
    return status === "error"
      ? HttpResponse.json({ ok: false, error: { code: "http", message: "board down" }, hint: "" }, { status: 502 })
      : ok({ ...STATUS, ...status });
  }), http.post("/v1/code/session", () => {
    mints += 1;
    return mint === "ok"
      ? ok({ token: `tok${mints}`, expires_at: 1 })
      : HttpResponse.json({ ok: false, error: { code: "forbidden", message: "only the board's human owner opens the Code tab" }, hint: "" }, { status: 403 });
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
  return { calls: () => calls, mints: () => mints };
}

/** The frame loads the guard's login URL; `next` is the embed URL the guard redirects to. */
function framed(src: string): { origin: string; token: string | null; target: string } {
  const u = new URL(src);
  expect(u.pathname).toBe("/__edp/login");
  return { origin: u.origin, token: u.searchParams.get("t"), target: new URL(u.searchParams.get("next")!, u.origin).toString() };
}

describe("CodePage", () => {
  it("embeds code-server at the port the board reports with no folder, so it reopens its last folder", async () => {
    mount();
    const frame = await screen.findByTestId("code-frame");
    const f = framed(frame.getAttribute("src")!);
    expect(f).toEqual({ origin: "http://127.0.0.1:9555", token: "tok1", target: "http://127.0.0.1:9555/" });
    expect(new URL(frame.getAttribute("src")!).searchParams.get("next")).toBe("/");
    expect(screen.getByTestId("code-state")).toHaveTextContent("code-server 4.138.0 · running");
    expect(screen.getByTestId("code-newwindow")).toHaveAttribute("href", "http://127.0.0.1:9555/");
    expect(screen.getByTestId("code-newwindow")).toHaveAttribute("target", "_blank");
    expect(screen.getByRole("heading", { level: 1, name: "Code" })).toBeInTheDocument();
  });

  it("a deep link opens the folder and the file at the range's start line, and shows the range", async () => {
    mount("/code?folder=C%3A%5CProjects%5Cv8&file=src%2Fedp8%2Fboard.py&line=10-20");
    const u = new URL(framed((await screen.findByTestId("code-frame")).getAttribute("src")!).target);
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

  it("a board opened as localhost frames the guard as localhost (the SameSite=Strict cookie stays same-site)", async () => {
    mount("/code", {}, "localhost");
    expect(framed((await screen.findByTestId("code-frame")).getAttribute("src")!).origin).toBe("http://localhost:9555");
  });

  it("a board that predates the mint route (404) frames the guard directly, as before S8", async () => {
    mount("/code", {}, "127.0.0.1", "ok");
    // registered after mount's handlers, so it wins (msw prepends); the mint runs only after /v1/code answers
    server.use(http.post("/v1/code/session", () => HttpResponse.json({ ok: false, error: { code: "http", message: "Not Found" }, hint: "" }, { status: 404 })));
    await waitFor(() => expect(screen.getByTestId("code-frame").getAttribute("src")).toBe("http://127.0.0.1:9555/"));
  });

  it("no session for anyone but the owner: a named state, never a frame", async () => {
    mount("/code", {}, "127.0.0.1", "forbidden");
    expect(await screen.findByTestId("code-no-session")).toHaveTextContent("only the board's human owner opens the Code tab");
    expect(screen.queryByTestId("code-frame")).toBeNull();
  });

  it("Open in new window mints its own token (the frame's is spent) and opens the login URL", async () => {
    const m = mount();
    await screen.findByTestId("code-frame");
    const win = { opener: {} as unknown, location: { href: "" } };
    const open = vi.spyOn(window, "open").mockReturnValue(win as unknown as Window);
    fireEvent.click(screen.getByTestId("code-newwindow"));
    expect(open).toHaveBeenCalledWith("about:blank", "_blank");
    await waitFor(() => expect(win.location.href).not.toBe(""));
    expect(win.opener).toBeNull();
    expect(framed(win.location.href)).toEqual({ origin: "http://127.0.0.1:9555", token: "tok2", target: "http://127.0.0.1:9555/" });
    expect(m.mints()).toBe(2);
    open.mockRestore();
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
