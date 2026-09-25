import { describe, it, expect, beforeEach } from "vitest";
import { useState } from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import type { PersonRow } from "../api/types";
import { MentionInput } from "./MentionInput";
import { QuoteChips } from "./QuoteCard";
import { quoteTray } from "./quoteTray";

// C23 (s-93ddb7fd1a): a quote note takes the composer's @ picker, same keys.
const people: PersonRow[] = [
  { id: "vishal", handle: "vishal", type: "human", role: "owner", seat_ticket: null, seat_state: null, label: "person", self: false },
  { id: "architect.s-1", handle: "architect.s-1", type: "agent", role: "architect", seat_ticket: "s-1", seat_state: "alive", label: "architect seat", self: false },
];

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

function Note({ onEnter }: { onEnter?: () => void }) {
  const [v, setV] = useState("");
  return <MentionInput value={v} onValue={setV} data-testid="note" onKeyDown={(e) => { if (e.key === "Enter") onEnter?.(); }} />;
}

function typeAt(el: HTMLInputElement, value: string) {
  fireEvent.change(el, { target: { value } });
  el.setSelectionRange(value.length, value.length);
  fireEvent.keyUp(el, { key: "x" });
}

beforeEach(() => {
  server.use(http.get("/v1/me/people", () => HttpResponse.json({ ok: true, value: people })));
});

describe("MentionInput", () => {
  it("'@vi' opens the picker; Enter picks '@vishal ' and does not reach the field's own Enter", async () => {
    let entered = 0;
    wrap(<Note onEnter={() => entered++} />);
    const el = screen.getByTestId("note") as HTMLInputElement;
    await waitFor(() => { typeAt(el, "see @vi"); expect(screen.getByTestId("note-mentions-menu")).toBeInTheDocument(); });
    expect(el.getAttribute("aria-expanded")).toBe("true");
    expect(el.getAttribute("aria-activedescendant")).toBeTruthy();
    fireEvent.keyDown(el, { key: "Enter" });
    expect(el.value).toBe("see @vishal ");
    expect(entered).toBe(0);
    expect(screen.queryByTestId("note-mentions-menu")).toBeNull();
    fireEvent.keyDown(el, { key: "Enter" }); // closed list: Enter is the field's again
    expect(entered).toBe(1);
  });

  it("an IME-composing Enter does not pick (the host's Enter handler gets it and checks isComposing)", async () => {
    let entered = 0;
    wrap(<Note onEnter={() => entered++} />);
    const el = screen.getByTestId("note") as HTMLInputElement;
    await waitFor(() => { typeAt(el, "@vi"); expect(screen.getByTestId("note-mentions-menu")).toBeInTheDocument(); });
    fireEvent.keyDown(el, { key: "Enter", isComposing: true });
    expect(el.value).toBe("@vi");
    expect(entered).toBe(1); // the host's own handler sees it and must check isComposing itself (QuoteLayer does)
  });

  it("arrows move the highlight, Tab picks, Escape closes", async () => {
    wrap(<Note />);
    const el = screen.getByTestId("note") as HTMLInputElement;
    await waitFor(() => { typeAt(el, "@"); expect(screen.getAllByRole("option")).toHaveLength(2); });
    fireEvent.keyDown(el, { key: "ArrowDown" });
    expect(screen.getAllByRole("option")[1].getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(el, { key: "Tab" });
    expect(el.value).toBe("@architect.s-1 ");
    typeAt(el, "@architect.s-1 @v");
    await waitFor(() => expect(screen.getByTestId("note-mentions-menu")).toBeInTheDocument());
    fireEvent.keyDown(el, { key: "Escape" });
    expect(screen.queryByTestId("note-mentions-menu")).toBeNull();
    expect(el.value).toBe("@architect.s-1 @v");
  });

  it("the composer's quote chip note has the picker and writes the tray", async () => {
    quoteTray.add("s-9", { source: "message", id: "m-1", text: "passage", locator: { char_start: 0, char_end: 7 } }, "m-1");
    wrap(<QuoteChips ticketId="s-9" />);
    const el = screen.getByTestId("quote-chip-note") as HTMLInputElement;
    await waitFor(() => { typeAt(el, "@vi"); expect(screen.getByTestId("note-mentions-menu")).toBeInTheDocument(); });
    fireEvent.keyDown(el, { key: "Enter" });
    expect(quoteTray.get("s-9")[0].quote.note).toBe("@vishal ");
  });
});
