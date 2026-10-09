// s-aa76c83998 (owner m-9834482f32, architect m-e4d66cbb38): the selection popover is two rows. Row 1 is the note
// input, row 2 an actions row with Mark as requirement (secondary) then Quote (primary), same height and font.
import { expect, it } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { server } from "../test/setup";
import { http, HttpResponse } from "msw";
import { QuoteLayer, quoteRegionRef } from "./QuoteLayer";

function mount(kind: "message" | "doc") {
  Range.prototype.getBoundingClientRect = () => ({ left: 20, top: 20, right: 300, bottom: 44, width: 280, height: 24, x: 20, y: 20, toJSON: () => ({}) });
  server.use(
    http.get("/v1/me/people", () => HttpResponse.json({ ok: true, value: { people: [], roles: [] } })),
    http.get("/v1/describe/message", () => HttpResponse.json({ ok: true, value: { contract: "message(text, quotes[])" } })),
  );
  const text = "first second";
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}>
    <p data-testid="msg" ref={quoteRegionRef({ kind, id: "m-test", ticketId: "epic-test", text })}>{text}</p>
    <QuoteLayer />
  </QueryClientProvider>);
  // the layer listens only once the board is known to take quotes, so select again until the popover opens
  return waitFor(() => {
    const node = screen.getByTestId("msg").firstChild as Text;
    fireEvent.mouseDown(screen.getByTestId("msg"));
    const range = document.createRange(); range.setStart(node, 0); range.setEnd(node, 5);
    window.getSelection()!.removeAllRanges(); window.getSelection()!.addRange(range);
    fireEvent.mouseUp(screen.getByTestId("msg"));
    expect(screen.getByTestId("quote-popover")).toBeInTheDocument();
  });
}

it("on a message, Mark as requirement (secondary) and Quote (primary) sit in one actions row, after the note", async () => {
  await mount("message");
  const pop = await screen.findByTestId("quote-popover");
  const actions = within(pop).getByTestId("quote-actions");
  const mark = within(actions).getByTestId("quote-popover-mark");
  const quote = within(actions).getByTestId("quote-add");
  expect(Array.from(actions.children)).toEqual([mark, quote]); // one row, Mark first, Quote last (primary at the right)
  expect(mark.className).toMatch(/secondary/);
  expect(quote.className).toMatch(/primary/);
  expect(mark.className).not.toBe(quote.className);
  // the note is row 1: a sibling of the actions row, before it, not inside it
  const note = within(pop).getByTestId("quote-note");
  expect(actions.contains(note)).toBe(false);
  expect(note.compareDocumentPosition(actions) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(note.getAttribute("placeholder")).toBe("Add a note (optional) — @ to notify");
});

it("on a doc, the actions row holds Quote alone", async () => {
  await mount("doc");
  const pop = await screen.findByTestId("quote-popover");
  const actions = within(pop).getByTestId("quote-actions");
  expect(Array.from(actions.children).map((c) => c.getAttribute("data-testid"))).toEqual(["quote-add"]);
  expect(within(pop).queryByTestId("quote-popover-mark")).toBeNull();
});

it("a failed mark shows one error line under the actions row, not inside it", async () => {
  server.use(http.post("/v1/requirements", () => HttpResponse.json({ ok: false, error: { code: "scope", message: "not on an epic's tree" } }, { status: 400 })));
  await mount("message");
  const pop = await screen.findByTestId("quote-popover");
  fireEvent.click(within(pop).getByTestId("quote-popover-mark"));
  const err = await waitFor(() => within(pop).getByTestId("quote-error"));
  expect(err).toHaveAttribute("role", "alert");
  expect(within(pop).getByTestId("quote-actions").contains(err)).toBe(false);
  expect(within(pop).queryByTestId("quote-mark-error")).toBeNull();
});


it("while the popover is open the page carries data-quote-popover, and drops it when it closes", async () => {
  await mount("message");
  await screen.findByTestId("quote-popover");
  expect(document.documentElement.getAttribute("data-quote-popover")).toBe("open");
  fireEvent.keyDown(document, { key: "Escape" });
  await waitFor(() => expect(screen.queryByTestId("quote-popover")).toBeNull());
  expect(document.documentElement.hasAttribute("data-quote-popover")).toBe(false);
});
