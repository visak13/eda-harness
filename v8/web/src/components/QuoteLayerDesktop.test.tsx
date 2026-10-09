import { afterEach, beforeEach, expect, it } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { server } from "../test/setup";
import { http, okJson } from "../pages/testUtils";
import { QuoteLayer, quoteRegionRef } from "./QuoteLayer";
import { quoteTray } from "./quoteTray";

// S11 (s-9277bcebc9): quoting in the desktop window. The cause was the shell, not the page: pywebview's default
// text_select=False injected `user-select: none`, so a drag selected nothing and QuoteLayer (mouseup + getSelection)
// never saw a selection. This pins the page side — a selection inside a message region, released with a mouseup,
// opens the popover and lands in the thread's message box — with the desktop shell's globals present, so the same flow
// is proved in both shells; the shell side (text_select=True, real drag in WebView2) is in tests/test_desktop.py and
// scripts/probe_desktop_shell.py.

const TICKET = "epic-quote-desktop";
const TEXT = "Select this sentence to quote it from the desktop window.";

beforeEach(() => {
  // jsdom has no layout: a Range answers no rectangle, which the popover placement needs
  Range.prototype.getBoundingClientRect = () => ({ left: 20, top: 20, right: 300, bottom: 44, width: 280, height: 24, x: 20, y: 20, toJSON: () => ({}) });
  sessionStorage.clear(); localStorage.clear();
  for (const q of quoteTray.get(TICKET)) quoteTray.remove(TICKET, q.key);
  (window as unknown as { pywebview: unknown }).pywebview = { api: {} };
  server.use(http.get("/v1/describe/message", () => okJson({ contract: "message(text, quotes[])" })));
});
afterEach(() => {
  delete (window as unknown as { pywebview?: unknown }).pywebview;
  window.getSelection()?.removeAllRanges();
});

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <p ref={quoteRegionRef({ kind: "message", id: "m-quote-1", ticketId: TICKET, author: "owner", text: TEXT })} data-testid="msg">{TEXT}</p>
      <QuoteLayer />
    </QueryClientProvider>,
  );
}

function select(from: number, to: number) {
  const node = screen.getByTestId("msg").firstChild as Text;
  const range = document.createRange();
  range.setStart(node, from); range.setEnd(node, to);
  const sel = window.getSelection()!;
  sel.removeAllRanges(); sel.addRange(range);
}

it("a drag selection in a message opens the Quote popover and the quote lands in the thread's message box", async () => {
  mount();
  select(0, TEXT.length);
  // the layer listens once the board's quote support answers; release the mouse until it does
  await waitFor(() => { fireEvent.mouseUp(screen.getByTestId("msg")); expect(screen.getByTestId("quote-popover")).toBeInTheDocument(); });
  const add = await screen.findByTestId("quote-add");
  fireEvent.click(add);
  await screen.findByTestId("quote-added");
  const got = quoteTray.get(TICKET);
  expect(got).toHaveLength(1);
  expect(got[0].quote).toMatchObject({ source: "message", id: "m-quote-1", text: TEXT, locator: { char_start: 0, char_end: TEXT.length } });
});

it("with nothing selected (user-select: none in the old window) no popover opens", async () => {
  mount();
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 50)); });
  act(() => { fireEvent.mouseUp(screen.getByTestId("msg")); });
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 50)); });
  expect(screen.queryByTestId("quote-popover")).toBeNull();
  expect(quoteTray.get(TICKET)).toHaveLength(0);
});
