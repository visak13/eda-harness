import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { Markdown, MessageMarkdown, externalizeLinks, linkifyMessageHtml } from "../components/Markdown";
import { HistoryButtons, useDesktopShortcuts } from "./DesktopChrome";
import { desktopNotify, isDesktopShell, isExternalHref } from "./shell";

// S11 (s-9277bcebc9): the desktop shell's page side. pywebview injects `window.pywebview` before page scripts and fills
// `.api` (edp8.desktop.Bridge) a moment later; these tests stand in for it.

interface FakeApi { notify: ReturnType<typeof vi.fn>; open_external: ReturnType<typeof vi.fn>; ping: ReturnType<typeof vi.fn> }
function installShell(overrides: Partial<FakeApi> = {}): FakeApi {
  const api: FakeApi = {
    notify: vi.fn(async () => ({ ok: true })),
    open_external: vi.fn(async () => true),
    ping: vi.fn(async () => ({ shell: "heronry-desktop", platform: "win32", toast: true })),
    ...overrides,
  };
  (window as unknown as { pywebview: unknown }).pywebview = { api };
  return api;
}
afterEach(() => { delete (window as unknown as { pywebview?: unknown }).pywebview; vi.restoreAllMocks(); });

describe("shell detection", () => {
  it("is the desktop shell only when pywebview is injected", () => {
    expect(isDesktopShell()).toBe(false);
    installShell();
    expect(isDesktopShell()).toBe(true);
  });

  it("notifies through the bridge, and says false in a browser or when the shell drops it", async () => {
    expect(await desktopNotify("t", "b")).toBe(false);
    const api = installShell();
    expect(await desktopNotify("Title", "Body")).toBe(true);
    expect(api.notify).toHaveBeenCalledWith("Title", "Body");
    api.notify.mockResolvedValueOnce({ ok: false, reason: "rate-limited" });
    expect(await desktopNotify("t", "b")).toBe(false);
    api.notify.mockRejectedValueOnce(new Error("bridge gone"));
    expect(await desktopNotify("t", "b")).toBe(false);
  });

  it("waits for pywebviewready when the api is not there yet", async () => {
    (window as unknown as { pywebview: unknown }).pywebview = { api: {} };
    const pending = desktopNotify("t", "b");
    const api = { notify: vi.fn(async () => ({ ok: true })), open_external: vi.fn(), ping: vi.fn() };
    (window as unknown as { pywebview: { api: unknown } }).pywebview.api = api;
    window.dispatchEvent(new Event("pywebviewready"));
    expect(await pending).toBe(true);
  });

  it("knows an external href from an in-app one", () => {
    const base = "http://127.0.0.1:9400/ui/epic/e1";
    expect(isExternalHref("https://github.com/a/b", base)).toBe(true);
    expect(isExternalHref("http://127.0.0.1:9402/mcp", base)).toBe(true);
    expect(isExternalHref("/ui/doc/design-1", base)).toBe(false);
    expect(isExternalHref("http://127.0.0.1:9400/ui/ticket/t-1", base)).toBe(false);
    expect(isExternalHref("mailto:a@b.test", base)).toBe(false);
    expect(isExternalHref("#section", base)).toBe(false);
    expect(isExternalHref("javascript:alert(1)", base)).toBe(false);
  });
});

describe("external links in every markdown renderer", () => {
  const html = '<p><a href="https://example.com/x">out</a> <a href="/ui/doc/design-1">in</a> <a href="mailto:a@b.test">mail</a> '
    + '<a href="http://localhost:3999/p">other port</a> <a href="#top">anchor</a></p>';

  function ext(container: HTMLElement) {
    return Array.from(container.querySelectorAll("a")).map((a) => [a.textContent, a.getAttribute("target"), a.getAttribute("rel")]);
  }

  it("externalizeLinks adds target=_blank rel=noopener to http(s) links on another origin only", () => {
    const doc = new DOMParser().parseFromString(externalizeLinks(html), "text/html");
    const rows = Array.from(doc.querySelectorAll("a")).map((a) => [a.textContent, a.getAttribute("target"), a.getAttribute("rel")]);
    expect(rows).toEqual([
      ["out", "_blank", "noopener noreferrer"],
      ["in", null, null],
      ["mail", null, null],
      ["other port", "_blank", "noopener noreferrer"],
      ["anchor", null, null],
    ]);
  });

  it("leaves a body without anchors untouched", () => {
    expect(externalizeLinks("<p>no links</p>")).toBe("<p>no links</p>");
  });

  it("<Markdown> (docs, ticket descriptions, cards, FAQ) opens external links in a new context", () => {
    const { container } = render(<Markdown html={html} />);
    expect(ext(container)[0]).toEqual(["out", "_blank", "noopener noreferrer"]);
    expect(ext(container)[1]).toEqual(["in", null, null]);
  });

  it("<MessageMarkdown> does too, including a bare URL the thread linkifies", () => {
    const { container } = render(<MemoryRouter><MessageMarkdown html={'<p>see https://bare.example/z and <a href="https://example.com/x">out</a></p>'} /></MemoryRouter>);
    expect(ext(container)).toEqual([["https://bare.example/z", "_blank", "noopener noreferrer"], ["out", "_blank", "noopener noreferrer"]]);
    // the linkifier itself never leaves a bare external link without rel
    expect(linkifyMessageHtml("<p>https://bare.example/z</p>")).toContain('rel="noopener noreferrer"');
  });

  it("DOMPurify's removal of target does not leave a hostile target on the page", () => {
    const { container } = render(<Markdown html={'<a href="https://example.com" target="_top" rel="opener">x</a>'} />);
    expect(ext(container)).toEqual([["x", "_blank", "noopener noreferrer"]]);
  });
});

function Where() { return <p data-testid="where">{useLocation().pathname}</p>; }
function Harness({ entries = ["/epics", "/seats", "/library"], index = 1 }: { entries?: string[]; index?: number }) {
  function Inner() { useDesktopShortcuts(); return <><HistoryButtons /><Where /><a href="https://example.com/out" data-testid="out">out</a><a href="/ui/seats" data-testid="in">in</a></>; }
  return <MemoryRouter initialEntries={entries} initialIndex={index}><Routes><Route path="*" element={<Inner />} /></Routes></MemoryRouter>;
}

describe("Back / Forward", () => {
  it("renders nothing in a browser tab (it has its own) and does not take Alt+Left", () => {
    render(<Harness />);
    expect(screen.queryByTestId("history")).toBeNull();
    const ev = new KeyboardEvent("keydown", { key: "ArrowLeft", altKey: true, bubbles: true, cancelable: true });
    document.dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(false);
    expect(screen.getByTestId("where").textContent).toBe("/seats");
  });

  it("the desktop header buttons step through app history", async () => {
    installShell();
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Go back" }));
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/epics"));
    fireEvent.click(screen.getByRole("button", { name: "Go forward" }));
    fireEvent.click(screen.getByRole("button", { name: "Go forward" }));
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/library"));
  });

  it("Alt+Left and Alt+Right step through history in the desktop shell, other chords do not", async () => {
    installShell();
    render(<Harness />);
    const press = (init: KeyboardEventInit) => {
      const ev = new KeyboardEvent("keydown", { bubbles: true, cancelable: true, ...init });
      act(() => { document.dispatchEvent(ev); });
      return ev;
    };
    expect(press({ key: "ArrowLeft", altKey: true }).defaultPrevented).toBe(true);
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/epics"));
    press({ key: "ArrowRight", altKey: true });
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/seats"));
    expect(press({ key: "ArrowLeft" }).defaultPrevented).toBe(false); // caret movement
    expect(press({ key: "ArrowLeft", altKey: true, ctrlKey: true }).defaultPrevented).toBe(false);
    expect(screen.getByTestId("where").textContent).toBe("/seats");
  });

  it("disables a direction the Navigation API says is not there", () => {
    installShell();
    Object.defineProperty(window, "navigation", { configurable: true, value: { canGoBack: false, canGoForward: true } });
    try {
      render(<Harness />);
      expect(screen.getByRole("button", { name: "Go back" })).toBeDisabled();
      expect(screen.getByRole("button", { name: "Go forward" })).toBeEnabled();
    } finally { delete (window as unknown as { navigation?: unknown }).navigation; }
  });
});

describe("external clicks in the desktop shell", () => {
  beforeEach(() => { vi.spyOn(window, "open").mockImplementation(() => null); });

  it("hands an external link to the system browser through the bridge and keeps the window on the board", async () => {
    const api = installShell();
    render(<Harness />);
    const ev = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
    act(() => { screen.getByTestId("out").dispatchEvent(ev); });
    expect(ev.defaultPrevented).toBe(true);
    await waitFor(() => expect(api.open_external).toHaveBeenCalledWith("https://example.com/out"));
    expect(window.open).not.toHaveBeenCalled();
  });

  it("falls back to a new window (the shell's guard then opens the browser) when the bridge cannot", async () => {
    installShell({ open_external: vi.fn(async () => false) });
    render(<Harness />);
    act(() => { screen.getByTestId("out").dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 })); });
    await waitFor(() => expect(window.open).toHaveBeenCalledWith("https://example.com/out", "_blank", "noopener"));
  });

  it("leaves an in-app link alone", () => {
    const api = installShell();
    render(<Harness />);
    const ev = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
    act(() => { screen.getByTestId("in").dispatchEvent(ev); });
    expect(ev.defaultPrevented).toBe(false);
    expect(api.open_external).not.toHaveBeenCalled();
  });

  it("does nothing in a browser tab", () => {
    render(<Harness />);
    const ev = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
    act(() => { screen.getByTestId("out").dispatchEvent(ev); });
    expect(ev.defaultPrevented).toBe(false);
  });
});
