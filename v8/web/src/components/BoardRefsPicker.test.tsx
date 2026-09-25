import { describe, it, expect, beforeEach } from "vitest";
import { useState } from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import { Composer } from "./Composer";
import { MentionInput } from "./MentionInput";
import { linkifyMessageHtml } from "./Markdown";
import { RefText } from "./RefText";

// C24 (s-5d1b171d57): the $ picker in the composer and in a quote note (board UI), and the chips.
const EPIC = "epic-52edacd059";
const tickets = [
  { id: EPIC, kind: "epic", title: "EDP chat in VS Code", status: "in_progress", epic_id: null },
  { id: "s-5d1b171d57", kind: "story", title: "C24 $-references", status: "in_progress", epic_id: EPIC },
  { id: "s-93ddb7fd1a", kind: "story", title: "C23 Quote notes take @mentions", status: "in_review", epic_id: EPIC },
];
let findCalls: string[] = [];

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={qc}><MemoryRouter initialEntries={["/ticket/s-5d1b171d57"]}><Routes><Route path="/ticket/:id" element={ui} /></Routes></MemoryRouter></QueryClientProvider>);
}

function typeAt(el: HTMLInputElement | HTMLTextAreaElement, value: string) {
  fireEvent.change(el, { target: { value } });
  el.setSelectionRange(value.length, value.length);
  fireEvent.keyUp(el, { key: "x" });
}

beforeEach(() => {
  findCalls = [];
  server.use(
    http.get("/v1/me/people", () => HttpResponse.json({ ok: true, value: [] })),
    http.post("/v1/messages/resolve", () => HttpResponse.json({ ok: true, value: { to: null, wakes: [], plan: [], note: "" } })),
    http.get("/v1/tickets/:id", ({ params }) => HttpResponse.json({ ok: true, value: tickets.find((t) => t.id === params.id) })),
    http.get("/v1/tickets", ({ request }) => {
      expect(new URL(request.url).searchParams.get("epic_id")).toBe(EPIC);
      return HttpResponse.json({ ok: true, value: tickets.slice(1) });
    }),
    http.get("/v1/docs", () => HttpResponse.json({ ok: true, value: [
      { id: "design-10b21760d9", doc_type: "design", title: "EDP chat design" }, { id: "note-23c452b368", doc_type: "note", title: "C24 plan" }] })),
    http.get("/v1/decisions", () => HttpResponse.json({ ok: true, value: { decisions: [
      { id: "dec-bf6aab8b73", text: "C3 no longer waits on the Code tab's S6 review", status: "live" }] } })),
    http.get("/v1/epics/summary", () => HttpResponse.json({ ok: true, value: [{ id: "epic-91fcd3b370", title: "Code tab C2 other", status: "in_progress" }] })),
    http.get("/v1/find", ({ request }) => {
      findCalls.push(new URL(request.url).searchParams.get("q") ?? "");
      return HttpResponse.json({ ok: true, value: [{ type: "ticket", id: "s-0000000001", title: "C2 elsewhere", status: "ready" }] });
    }),
  );
});

function Note() {
  const [v, setV] = useState("");
  return <MentionInput value={v} onValue={setV} data-testid="note" />;
}

describe("$ picker in a quote note", () => {
  it("'$C2' lists this epic's rows first, then the board's; Enter inserts '$<id> (<title>) '", async () => {
    wrap(<Note />);
    const el = screen.getByTestId("note") as HTMLInputElement;
    await waitFor(() => {
      typeAt(el, "see $C2");
      const rows = screen.getAllByRole("option");
      expect(rows.map((r) => r.getAttribute("data-ref"))).toEqual(["s-5d1b171d57", "s-93ddb7fd1a", "s-0000000001", "epic-91fcd3b370"]);
    });
    const rows = screen.getAllByRole("option");
    expect(rows[0].textContent).toContain("story $s-5d1b171d57");
    expect(rows[0].textContent).toContain("C24 $-references");
    expect(rows[1].getAttribute("data-group")).toBe("scope");
    expect(rows[2].getAttribute("data-group")).toBe("board");
    expect(el.getAttribute("aria-activedescendant")).toBeTruthy();
    fireEvent.keyDown(el, { key: "ArrowDown" });
    fireEvent.keyDown(el, { key: "Enter" });
    expect(el.value).toBe("see $s-93ddb7fd1a (C23 Quote notes take ＠mentions) ");
    expect(screen.queryByTestId("note-refs-menu")).toBeNull();
    expect(findCalls).toContain("C2");
  });

  it("Tab picks a doc; Escape closes and keeps the typed text", async () => {
    wrap(<Note />);
    const el = screen.getByTestId("note") as HTMLInputElement;
    await waitFor(() => { typeAt(el, "$design"); expect(screen.getByTestId("note-refs-menu")).toBeInTheDocument(); });
    fireEvent.keyDown(el, { key: "Tab" });
    expect(el.value).toBe("$design-10b21760d9 (EDP chat design) ");
    typeAt(el, "x $EDP");
    await waitFor(() => expect(screen.getByTestId("note-refs-menu")).toBeInTheDocument());
    fireEvent.keyDown(el, { key: "Escape" });
    expect(screen.queryByTestId("note-refs-menu")).toBeNull();
    fireEvent.keyUp(el, { key: "Escape" });
    expect(screen.queryByTestId("note-refs-menu")).toBeNull();
    expect(el.value).toBe("x $EDP");
  });

  it("'$5' and '$env:X' open no picker", async () => {
    wrap(<Note />);
    const el = screen.getByTestId("note") as HTMLInputElement;
    typeAt(el, "$C2"); // warms the scope
    await waitFor(() => expect(screen.getByTestId("note-refs-menu")).toBeInTheDocument());
    for (const v of ["costs $5", "$env:X", "$env:"]) {
      typeAt(el, v);
      await new Promise((r) => setTimeout(r, 200));
      expect(screen.queryByTestId("note-refs-menu")).toBeNull();
    }
  });
});

describe("$ picker in the composer", () => {
  it("picks a decision; the sent text carries $<id>", async () => {
    let sent: { text?: string } = {};
    server.use(http.post("/v1/messages", async ({ request }) => {
      sent = (await request.json()) as { text?: string };
      return HttpResponse.json({ ok: true, value: { id: "m-1", ticket_id: "s-5d1b171d57", text: sent.text, unresolved_mentions: [] } });
    }));
    wrap(<Composer ticketId="s-5d1b171d57" />);
    const ta = screen.getByTestId("composer-text") as HTMLTextAreaElement;
    await waitFor(() => { typeAt(ta, "per $C3"); expect(screen.getByTestId("refs-menu")).toBeInTheDocument(); });
    expect(screen.getAllByRole("option")[0].getAttribute("data-ref")).toBe("dec-bf6aab8b73");
    // the textarea names the list and its active row (second opinion 20260925T194748Z-c11490bb)
    expect(ta.getAttribute("aria-expanded")).toBe("true");
    expect(ta.getAttribute("aria-controls")).toBe(screen.getByTestId("refs-menu").id);
    const active = () => document.getElementById(ta.getAttribute("aria-activedescendant") ?? "");
    expect(active()?.getAttribute("aria-selected")).toBe("true");
    const n = screen.getAllByRole("option").length;
    if (n > 1) {
      fireEvent.keyDown(ta, { key: "ArrowDown" });
      expect(active()).toBe(screen.getAllByRole("option")[1]);
      fireEvent.keyDown(ta, { key: "ArrowUp" });
    }
    expect(active()?.getAttribute("data-ref")).toBe("dec-bf6aab8b73");
    fireEvent.keyDown(ta, { key: "Enter" });
    expect(ta.getAttribute("aria-expanded")).toBe("false");
    expect(ta.hasAttribute("aria-activedescendant")).toBe(false);
    expect(ta.value).toBe("per $dec-bf6aab8b73 (C3 no longer waits on the Code tab's S6 review) ");
    fireEvent.keyDown(ta, { key: "Enter", ctrlKey: true });
    await waitFor(() => expect(sent.text).toBe("per $dec-bf6aab8b73 (C3 no longer waits on the Code tab's S6 review)"));
  });
});

function Where() {
  const l = useLocation();
  return <p data-testid="where">{`${l.pathname}${l.search}`}</p>;
}

describe("$ chips", () => {
  it("a message body renders each $<id> as a chip with its target", () => {
    const html = linkifyMessageHtml("<p>see $s-5d1b171d57 (C24 refs), $epic-52edacd059, $design-10b21760d9 and $dec-bf6aab8b73; <code>$s-93ddb7fd1a</code> costs $5</p>");
    const doc = new DOMParser().parseFromString(html, "text/html");
    const chips = Array.from(doc.querySelectorAll("a.ref-chip"));
    expect(chips.map((a) => [a.getAttribute("data-ref"), a.textContent])).toEqual([
      ["s-5d1b171d57", "story · C24 refs"], ["epic-52edacd059", "$epic-52edacd059"], ["design-10b21760d9", "$design-10b21760d9"], ["dec-bf6aab8b73", "$dec-bf6aab8b73"]]);
    const href = chips.map((a) => a.getAttribute("href") ?? "");
    expect(href[0]).toMatch(/\/ticket\/s-5d1b171d57$/);
    expect(href[1]).toMatch(/\/epic\/epic-52edacd059$/);
    expect(href[2]).toMatch(/\?doc=design-10b21760d9$/);
    expect(href[3]).toMatch(/\?view=history&category=decisions$/);
    expect(doc.querySelector("code")?.textContent).toBe("$s-93ddb7fd1a");
  });

  it("a note's chip navigates in the app (doc → the drawer over this page)", async () => {
    wrap(<><RefText text="read $design-10b21760d9 (EDP chat design) first" /><Where /></>);
    const chip = screen.getByTestId("ref-chip");
    expect(chip.textContent).toBe("design · EDP chat design");
    fireEvent.click(chip);
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/ticket/s-5d1b171d57?doc=design-10b21760d9"));
  });
});
