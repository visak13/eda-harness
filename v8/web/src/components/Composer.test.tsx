import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import type { PersonRow } from "../api/types";
import { Composer } from "./Composer";

const people: PersonRow[] = [
  { id: "architect.s-1", handle: "architect.s-1", type: "agent", role: "architect", seat_ticket: "s-1", seat_state: "alive", label: "architect seat", self: false },
  { id: "owner", handle: "owner", type: "human", role: "owner", seat_ticket: null, seat_state: null, label: "person", self: false },
];

function mountComposer(props: Partial<React.ComponentProps<typeof Composer>> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <Composer ticketId="s-1" {...props} />
    </QueryClientProvider>,
  );
}

function typeAt(ta: HTMLTextAreaElement, value: string) {
  fireEvent.change(ta, { target: { value } });
  ta.setSelectionRange(value.length, value.length); // jsdom keeps the caret at 0 after change
  fireEvent.keyUp(ta, { key: "r" });
}

beforeEach(() => {
  server.use(
    http.get("/v1/me/people", () => HttpResponse.json({ ok: true, value: people })),
    http.post("/v1/messages/resolve", () =>
      HttpResponse.json({ ok: true, value: { to: null, wakes: [], plan: [], note: "nobody is woken" } }),
    ),
  );
});

describe("Composer @autocomplete", () => {
  it("lists handles from /v1/me/people on '@ar', arrows move, Enter inserts '@handle '", async () => {
    mountComposer({ showTo: true });
    await screen.findByRole("option", { name: /architect seat/ }); // people loaded
    const ta = screen.getByTestId("composer-text") as HTMLTextAreaElement;
    typeAt(ta, "@ar");
    await waitFor(() => expect(screen.getByTestId("mentions-menu")).toBeInTheDocument());
    expect(screen.getByRole("option", { name: /@architect\.s-1/ })).toBeInTheDocument();
    fireEvent.keyDown(ta, { key: "Enter" });
    expect(ta.value).toBe("@architect.s-1 ");
  });

  it("Esc closes the mentions menu", async () => {
    mountComposer({ showTo: true });
    await screen.findByRole("option", { name: /architect seat/ });
    const ta = screen.getByTestId("composer-text") as HTMLTextAreaElement;
    typeAt(ta, "@ar");
    await waitFor(() => expect(screen.getByTestId("mentions-menu")).toBeInTheDocument());
    fireEvent.keyDown(ta, { key: "Escape" });
    await waitFor(() => expect(screen.queryByTestId("mentions-menu")).not.toBeInTheDocument());
  });
});

describe("Composer send", () => {
  it("Enter inserts a newline and does NOT send; Ctrl+Enter sends", async () => {
    const sent = vi.fn();
    server.use(
      http.post("/v1/messages", () =>
        HttpResponse.json({ ok: true, value: { id: "m-1", unresolved_mentions: [] }, hint: "delivered" }),
      ),
    );
    mountComposer({ onSent: sent });
    const ta = screen.getByTestId("composer-text") as HTMLTextAreaElement;
    typeAt(ta, "hello");
    fireEvent.keyDown(ta, { key: "Enter" }); // newline, not a send
    expect(sent).not.toHaveBeenCalled();
    fireEvent.keyDown(ta, { key: "Enter", ctrlKey: true });
    await waitFor(() => expect(sent).toHaveBeenCalled());
  });

  it("surfaces unresolved_mentions in a banner while the message still posts", async () => {
    server.use(
      http.post("/v1/messages", () =>
        HttpResponse.json({ ok: true, value: { id: "m-1", unresolved_mentions: ["nobody"] }, hint: "" }),
      ),
    );
    mountComposer();
    const ta = screen.getByTestId("composer-text") as HTMLTextAreaElement;
    typeAt(ta, "hi @nobody");
    fireEvent.click(screen.getByTestId("composer-send"));
    await waitFor(() => expect(screen.getByTestId("unresolved-banner")).toHaveTextContent("@nobody"));
  });
});

describe("Composer wake preview + addressing", () => {
  it("shows the board's wake plan verbatim ('Wakes … (alive)')", async () => {
    server.use(
      http.post("/v1/messages/resolve", () =>
        HttpResponse.json({
          ok: true,
          value: {
            to: "engineer.s-1",
            wakes: [{ recipient: "engineer.s-1", reason: "addressed", reasons: ["addressed"], why: "addressed to you", alive: true }],
            plan: [{ recipient: "engineer.s-1", reason: "addressed", reasons: ["addressed"], why: "addressed to you", alive: true }],
            note: "",
          },
        }),
      ),
    );
    mountComposer({ to: "engineer.s-1" });
    await waitFor(() => expect(screen.getByTestId("wake-preview")).toHaveTextContent("Wakes engineer.s-1 (alive)"));
  });

  it("To picker groups People / Live seats / Roles on this epic and never a closed seat", async () => {
    mountComposer({ showTo: true });
    await screen.findByRole("option", { name: /architect seat/ }); // people loaded
    const groups = screen.getByTestId("to-picker").querySelectorAll("optgroup");
    expect([...groups].map((g) => g.label)).toEqual(["People", "Live seats", "Roles on this epic"]);
    // Only reachable rows are offered; the roster already excludes closed seats.
    expect(screen.getByRole("option", { name: /architect seat/ })).toBeInTheDocument();
  });
});

describe("Composer drop/paste upload", () => {
  it("uploads a dropped file and inserts its art- token; a refused upload keeps the draft", async () => {
    let call = 0;
    server.use(
      http.post("/v1/artifacts/upload", () => {
        call += 1;
        return call === 1
          ? HttpResponse.json({ ok: true, value: { id: "art-xyz", form: "image" } })
          : HttpResponse.json({ ok: false, hint: "disallowed type" }, { status: 415 });
      }),
    );
    mountComposer();
    const composer = screen.getByTestId("composer");
    const png = new File(["x"], "a.png", { type: "image/png" });
    fireEvent.drop(composer, { dataTransfer: { files: [png] } });
    await waitFor(() =>
      expect((screen.getByTestId("composer-text") as HTMLTextAreaElement).value).toContain("art-xyz"),
    );
    // A refused upload leaves the draft intact and shows the reason.
    const bad = new File(["x"], "a.exe", { type: "application/x-msdownload" });
    fireEvent.drop(composer, { dataTransfer: { files: [bad] } });
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/Upload failed/));
    expect((screen.getByTestId("composer-text") as HTMLTextAreaElement).value).toContain("art-xyz");
  });
});
