// s-aa76c83998 Astra recheck F2 (report-43106b45d4): each new selection gets a fresh Mark button.
import { expect, it } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { server } from "../test/setup";
import { http, HttpResponse } from "msw";
import { QuoteLayer, quoteRegionRef } from "./QuoteLayer";

it("F2 recheck: two consecutive selections can both be marked without sending chat", async () => {
  Range.prototype.getBoundingClientRect = () => ({ left: 20, top: 20, right: 300, bottom: 44, width: 280, height: 24, x: 20, y: 20, toJSON: () => ({}) });
  const posts: any[] = [];
  let messages = 0;
  server.use(
    http.get("/v1/me/people", () => HttpResponse.json({ ok: true, value: { people: [], roles: [] } })),
    http.get("/v1/describe/message", () => HttpResponse.json({ ok: true, value: { contract: "message(text, quotes[])" } })),
    http.post("/v1/requirements", async ({ request }) => {
      posts.push(await request.json());
      return HttpResponse.json({ ok: true, value: { id: `req-${posts.length}`, epic: "epic-test" } });
    }),
    http.post("/v1/messages", () => { messages++; return HttpResponse.json({ ok: true, value: {} }); }),
  );
  const text = "first second";
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}>
    <p data-testid="msg" ref={quoteRegionRef({ kind: "message", id: "m-test", ticketId: "epic-test", text })}>{text}</p>
    <QuoteLayer />
  </QueryClientProvider>);
  const select = (from: number, to: number) => {
    const node = screen.getByTestId("msg").firstChild as Text;
    fireEvent.mouseDown(screen.getByTestId("msg"));
    const range = document.createRange(); range.setStart(node, from); range.setEnd(node, to);
    window.getSelection()!.removeAllRanges(); window.getSelection()!.addRange(range);
    fireEvent.mouseUp(screen.getByTestId("msg"));
  };
  await waitFor(() => { select(0, 5); expect(screen.getByTestId("quote-popover-mark")).toBeInTheDocument(); });
  fireEvent.click(screen.getByTestId("quote-popover-mark"));
  // qa fail 8: once the mark succeeds the popover closes (it covered the text) and a toast says so
  await waitFor(() => expect(screen.queryByTestId("quote-popover")).not.toBeInTheDocument());
  expect(screen.getByTestId("quote-added")).toHaveTextContent("Requirement marked.");
  expect(posts).toEqual([{ message_id: "m-test", char_start: 0, char_end: 5, text: "first" }]);
  select(6, 12);
  expect(window.getSelection()!.toString()).toBe("second");
  await waitFor(() => expect(screen.getByTestId("quote-popover-mark")).toBeEnabled());
  fireEvent.click(screen.getByTestId("quote-popover-mark"));
  await waitFor(() => expect(posts).toHaveLength(2));
  expect(posts[1]).toEqual({ message_id: "m-test", char_start: 6, char_end: 12, text: "second" });
  expect(messages).toBe(0);
});
