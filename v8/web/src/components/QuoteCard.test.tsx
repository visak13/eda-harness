import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import type { Quote, QuoteIn } from "../api/types";
import { Composer } from "./Composer";
import { QuoteCard, quoteSourceLabel, sectionLabel } from "./QuoteCard";
import { quoteTray } from "./quoteTray";

const docQ: QuoteIn = { source: "doc", id: "design-1", version: 3, locator: { line_start: 4, line_end: 5 }, text: "The board **validates** each quote" };
const msgQ: QuoteIn = { source: "message", id: "m-1", locator: { char_start: 0, char_end: 5 }, text: "hello", note: "why?" };

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={qc}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>);
}

beforeEach(() => {
  sessionStorage.clear();
  for (const t of ["s-q", "s-r"]) for (const r of quoteTray.get(t)) quoteTray.remove(t, r.key);
  server.use(
    http.get("/v1/me/people", () => HttpResponse.json({ ok: true, value: [] })),
    http.post("/v1/messages/resolve", () => HttpResponse.json({ ok: true, value: { to: null, wakes: [], plan: [], note: "" } })),
  );
});

describe("quoteTray", () => {
  it("keeps quotes in order per ticket; move, note, remove and removeSent", () => {
    quoteTray.add("s-q", docQ, "a");
    quoteTray.add("s-q", msgQ, "b");
    quoteTray.add("s-r", msgQ, "other");
    const [a, b] = quoteTray.get("s-q");
    quoteTray.move("s-q", b.key, -1);
    expect(quoteTray.get("s-q").map((r) => r.label)).toEqual(["b", "a"]);
    quoteTray.move("s-q", b.key, -1); // already first: no-op
    expect(quoteTray.get("s-q").map((r) => r.label)).toEqual(["b", "a"]);
    quoteTray.setNote("s-q", a.key, "mine");
    expect(quoteTray.get("s-q")[1].quote.note).toBe("mine");
    quoteTray.removeSent("s-q", [a.key]);
    expect(quoteTray.get("s-q").map((r) => r.label)).toEqual(["b"]);
    expect(quoteTray.get("s-r")).toHaveLength(1);
  });

  it("refuses a 21st quote (the board's per-message cap)", () => {
    for (let i = 0; i < 20; i++) expect(quoteTray.add("s-q", msgQ, `q${i}`)).toBe(true);
    expect(quoteTray.add("s-q", msgQ, "one too many")).toBe(false);
  });
});

describe("QuoteCard", () => {
  it("renders a doc quote with its passage, section/line source link and note", () => {
    const q: Quote = { ...docQ, locator: { heading: "14.5 Quotes: one message", line_start: 4, line_end: 5 }, note: "this line", sha: "x" };
    wrap(<QuoteCard q={q} />);
    expect(screen.getByTestId("quote-passage").textContent).toBe("The board validates each quote");
    expect(screen.getByTestId("quote-passage").getAttribute("title")).toBe(docQ.text); // the verified source
    const link = screen.getByTestId("quote-source");
    expect(link.textContent).toContain("design-1 v3 §14.5 L4-5");
    expect(link.getAttribute("href")).toBe("?doc=design-1&v=3&line=4-5");
    expect(screen.getByTestId("quote-note-text").textContent).toContain("this line");
  });

  it("renders a message quote linking to the message and a code quote as a code card", () => {
    wrap(<>
      <QuoteCard q={{ ...msgQ, author: "architect.e-1", sha: "x" }} />
      <QuoteCard q={{ source: "code", text: "x = 1", code: { repo_root: "C:/r", path: "a.py", line_start: 1, line_end: 1, commit: null, dirty: false, snippet: "x = 1", snippet_sha: "s" } }} />
    </>);
    const [msg, code] = screen.getAllByTestId("quote-card");
    expect(within(msg).getByTestId("quote-source").getAttribute("href")).toBe("#m-1");
    expect(within(msg).getByTestId("quote-source").textContent).toContain("m-1 (architect.e-1)");
    expect(within(code).getByTestId("code-card")).toBeInTheDocument();
  });

  it("labels sections like the board", () => {
    expect(sectionLabel("14.5 Quotes")).toBe("§14.5");
    expect(sectionLabel("5. Work breakdown")).toBe("§5");
    expect(sectionLabel("Risks")).toBe("§Risks");
    expect(quoteSourceLabel({ source: "doc", id: "d", version: 2, locator: { line_start: 7, line_end: 7 }, text: "t" })).toBe("d v2 L7");
  });
});

describe("Composer with quotes", () => {
  it("shows the thread's chips, reorders and removes them, and sends quotes[] in chip order with notes", async () => {
    let sent: any = null;
    server.use(http.post("/v1/messages", async ({ request }) => {
      sent = await request.json();
      return HttpResponse.json({ ok: true, value: { id: "m-new", unresolved_mentions: [] }, hint: "sent" });
    }));
    quoteTray.add("s-q", docQ, "design-1 v3 L4-5");
    quoteTray.add("s-q", msgQ, "m-1 (arch)");
    quoteTray.add("s-q", { ...docQ, locator: { line_start: 9, line_end: 9 }, text: "third" }, "design-1 v3 L9");
    wrap(<Composer ticketId="s-q" quotes />);
    expect(screen.getAllByTestId("quote-chip")).toHaveLength(3);
    fireEvent.click(screen.getAllByTestId("quote-chip-down")[0]); // doc ↓ → msg, doc, third
    fireEvent.click(screen.getAllByTestId("quote-chip-remove")[2]); // drop "third"
    fireEvent.change(screen.getAllByTestId("quote-chip-note")[1], { target: { value: "see here" } });
    expect(screen.getAllByTestId("quote-chip-label").map((e) => e.textContent)).toEqual(["m-1 (arch)", "design-1 v3 L4-5"]);
    fireEvent.change(screen.getByTestId("composer-text"), { target: { value: "My reply" } });
    fireEvent.click(screen.getByTestId("composer-send"));
    await waitFor(() => expect(sent).not.toBeNull());
    expect(sent.text).toBe("My reply");
    expect(sent.quotes.map((q: QuoteIn) => q.id)).toEqual(["m-1", "design-1"]);
    expect(sent.quotes[1].note).toBe("see here");
    await waitFor(() => expect(screen.queryAllByTestId("quote-chip")).toHaveLength(0));
  });

  it("keeps the chips and marks the one the board refused (422 quote_mismatch)", async () => {
    server.use(http.post("/v1/messages", () => HttpResponse.json(
      { ok: false, error: { code: "quote_mismatch", message: "quotes[1]: text does not occur in design-1 v3 L4-5" } }, { status: 422 })));
    quoteTray.add("s-q", msgQ, "m-1");
    quoteTray.add("s-q", docQ, "design-1");
    wrap(<Composer ticketId="s-q" quotes />);
    fireEvent.click(screen.getByTestId("composer-send")); // quotes alone may be sent
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("quotes[1]: text does not occur"));
    const chips = screen.getAllByTestId("quote-chip");
    expect(chips).toHaveLength(2);
    expect(chips[1].getAttribute("data-invalid")).toBe("true");
    expect(chips[0].getAttribute("data-invalid")).toBeNull();
  });

  it("a composer without `quotes` shows no chips and sends none", () => {
    quoteTray.add("s-q", docQ, "design-1");
    wrap(<Composer ticketId="s-q" />);
    expect(screen.queryByTestId("quote-chips")).toBeNull();
  });
});
