import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import type { Quote } from "../api/types";
import type { RequirementRow } from "../api/requirements";
import { QuoteCard, QuoteChips } from "./QuoteCard";
import { QuoteLayer, quoteRegionRef } from "./QuoteLayer";
import { quoteTray } from "./quoteTray";
import { GateHeldCaption, RequirementsSection, useOpenRequirements } from "./Requirements";

/** The open count the epic header's Needs attention field shows (the page used to insert its own line for it). */
function OpenCount({ epicId }: { epicId: string }): React.JSX.Element { return <span data-testid="requirements-chip-tally">{useOpenRequirements(epicId)}</span>; }

const req = (over: Partial<RequirementRow>): RequirementRow => ({
  id: "req-1", state: "open", epic: "epic-1", ticket: "epic-1", source: "m-1", char_start: 0, char_end: 5, text: "make it work",
  by: "owner", at: "2026-10-09T10:00:00+00:00", ...over,
});
const wrap = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={qc}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>);
};
const msgQuote: Quote = { source: "message", id: "m-1", author: "owner", locator: { char_start: 4, char_end: 9 }, text: "hello", sha: "x" };

describe("Mark as requirement on the quote card", () => {
  it("posts the message id and character range, sends no chat message, and says it is marked", async () => {
    const posts: unknown[] = [];
    let messages = 0;
    server.use(
      http.post("/v1/requirements", async ({ request }) => { posts.push(await request.json()); return HttpResponse.json({ ok: true, value: req({ char_start: 4, char_end: 9, text: "hello" }) }); }),
      http.post("/v1/messages", () => { messages += 1; return HttpResponse.json({ ok: true, value: {} }); }),
    );
    wrap(<QuoteCard q={msgQuote} />);
    const btn = screen.getByTestId("quote-mark-requirement");
    expect(btn).toHaveTextContent("Mark as requirement");
    fireEvent.click(btn);
    await waitFor(() => expect(btn).toHaveTextContent("Marked as requirement"));
    expect(posts).toEqual([{ message_id: "m-1", char_start: 4, char_end: 9, text: "hello" }]);
    expect(btn).toBeDisabled();
    expect(messages).toBe(0);
  });

  it("shows the board's refusal and lets the person try again", async () => {
    server.use(http.post("/v1/requirements", () => HttpResponse.json({ ok: false, error: { code: "scope", message: "not on an epic's tree" } }, { status: 403 })));
    wrap(<QuoteCard q={msgQuote} />);
    fireEvent.click(screen.getByTestId("quote-mark-requirement"));
    expect(await screen.findByTestId("quote-mark-error")).toHaveTextContent("not on an epic's tree");
    expect(screen.getByTestId("quote-mark-requirement")).not.toBeDisabled();
  });

  it("is offered on a message quote only, not on a doc or code quote", () => {
    wrap(<QuoteCard q={{ source: "doc", id: "design-1", version: 2, locator: { line_start: 1, line_end: 1 }, text: "x" }} />);
    expect(screen.queryByTestId("quote-mark-requirement")).toBeNull();
  });
});

describe("Requirements list", () => {
  const serve = (value: unknown) => server.use(http.get("/v1/epics/epic-1/requirements", () => HttpResponse.json({ ok: true, value })));

  it("lists open first, names the state in a word and what covers a linked one", async () => {
    serve({ digests: [], blocked_reason: "1 open requirement (req-1)", requirements: [
      req({ id: "req-2", state: "linked", text: "second words", criterion: "c-9" }),
      req({ id: "req-3", state: "linked", text: "third words", doc: { id: "design-1", version: 2, heading: "Buttons" } }),
      req({ id: "req-1", text: "first words" }),
    ] });
    wrap(<RequirementsSection epicId="epic-1" />);
    const rows = await screen.findAllByTestId("req-row");
    expect(rows.map((r) => r.dataset.req)).toEqual(["req-1", "req-2", "req-3"]);
    expect(within(rows[0]).getByTestId("req-state")).toHaveTextContent("open");
    expect(within(rows[1]).getByTestId("req-link")).toHaveTextContent("Covered by c-9");
    expect(within(rows[2]).getByRole("link", { name: /design-1 v2 · Buttons/ })).toHaveAttribute("href", "/doc/design-1?v=2");
    expect(screen.getByTestId("requirements-tally")).toHaveTextContent("3 requirements · 1 open");
  });

  it("says so when nothing is marked", async () => {
    serve({ requirements: [], digests: [] });
    wrap(<RequirementsSection epicId="epic-1" />);
    expect(await screen.findByTestId("requirements-empty")).toBeInTheDocument();
  });

  it("the open count and the gate caption show only while something is open, with the board's sentence without its ids", async () => {
    serve({ digests: [], blocked_reason: "2 open requirements (req-1, req-2)", requirements: [req({}), req({ id: "req-2" })] });
    wrap(<><OpenCount epicId="epic-1" /><GateHeldCaption epicId="epic-1" /></>);
    await waitFor(() => expect(screen.getByTestId("requirements-chip-tally")).toHaveTextContent("2"));
    expect(screen.getByTestId("gate-blocked-reason").textContent).toBe("2 open requirements"); // ids are for agents, not the page
  });

  it("counts none and renders no caption when all are linked", async () => {
    serve({ digests: [], requirements: [req({ state: "linked", criterion: "c-1" })] });
    wrap(<><OpenCount epicId="epic-1" /><GateHeldCaption epicId="epic-1" /></>);
    await waitFor(() => expect(screen.getByTestId("requirements-chip-tally")).toHaveTextContent("0"));
    expect(screen.queryByTestId("gate-held")).toBeNull();
  });
});

describe("Mark as requirement before anything is posted (s-aa76 F2)", () => {
  it("is offered in the selection popup and on the unsent chip, and posts no message", async () => {
    Range.prototype.getBoundingClientRect = () => ({ left: 20, top: 20, right: 300, bottom: 44, width: 280, height: 24, x: 20, y: 20, toJSON: () => ({}) });
    const posts: unknown[] = [];
    let messages = 0;
    server.use(
      http.get("/v1/describe/message", () => HttpResponse.json({ ok: true, value: { contract: "message(text, quotes[])" } })),
      http.post("/v1/requirements", async ({ request }) => { posts.push(await request.json()); return HttpResponse.json({ ok: true, value: req({}) }); }),
      http.post("/v1/messages", () => { messages += 1; return HttpResponse.json({ ok: true, value: {} }); }),
    );
    const ticket = "epic-f2", text = "ship blue";
    wrap(<>
      <p data-testid="message" ref={quoteRegionRef({ kind: "message", id: "m-test", ticketId: ticket, text })}>{text}</p>
      <QuoteLayer /><QuoteChips ticketId={ticket} />
    </>);
    const node = screen.getByTestId("message").firstChild as Text;
    const range = document.createRange(); range.setStart(node, 0); range.setEnd(node, text.length);
    window.getSelection()!.removeAllRanges(); window.getSelection()!.addRange(range);
    await waitFor(() => { fireEvent.mouseUp(screen.getByTestId("message")); expect(screen.getByTestId("quote-popover")).toBeInTheDocument(); });
    fireEvent.click(screen.getByTestId("quote-popover-mark"));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatchObject({ message_id: "m-test", char_start: 0, char_end: 9, text });
    quoteTray.add(ticket, { source: "message", id: "m-test", locator: { char_start: 0, char_end: 9 }, text }, "m-test");
    const chip = await screen.findByTestId("quote-chip-mark");
    fireEvent.click(chip);
    await waitFor(() => expect(chip).toHaveTextContent("Marked as requirement"));
    expect(posts).toHaveLength(2);
    expect(messages).toBe(0);
  });
});
