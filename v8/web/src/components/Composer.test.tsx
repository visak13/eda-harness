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

  it("ArrowDown walks the list: Down, Down, Enter inserts the third candidate (m-a398600978)", async () => {
    server.use(
      http.get("/v1/me/people", () =>
        HttpResponse.json({
          ok: true,
          value: [
            ...people,
            { id: "qa.s-1", handle: "qa.s-1", type: "agent", role: "qa", seat_ticket: "s-1", seat_state: "alive", label: "qa seat", self: false },
            { id: "sme.s-1", handle: "sme.s-1", type: "agent", role: "sme", seat_ticket: "s-1", seat_state: "alive", label: "sme seat", self: false },
          ],
        }),
      ),
    );
    mountComposer({ showTo: true });
    await screen.findByRole("option", { name: /sme seat/ });
    const ta = screen.getByTestId("composer-text") as HTMLTextAreaElement;
    typeAt(ta, "@s"); // matches architect.s-1, qa.s-1, sme.s-1 (+ owner via the "person" label) — 3+ rows
    await waitFor(() => expect(screen.getByTestId("mentions-menu")).toBeInTheDocument());
    const names = screen.getAllByRole("option", { name: /@/ }).map((o) => o.querySelector("span")?.textContent ?? "");
    expect(names.length).toBeGreaterThanOrEqual(3);
    for (const key of ["ArrowDown", "ArrowDown"]) {
      fireEvent.keyDown(ta, { key });
      fireEvent.keyUp(ta, { key }); // the keyup refresh must not reset the highlight
    }
    const active = screen.getAllByRole("option", { name: /@/ }).findIndex((o) => o.getAttribute("aria-selected") === "true");
    expect(active).toBe(2);
    fireEvent.keyDown(ta, { key: "Enter" });
    expect(ta.value).toBe(`${names[2]} `); // "@qa.s-1 " — the THIRD candidate, not the second
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
  it("shows the board's wake plan as 'Will notify …' with the per-recipient reasons in the title", async () => {
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
    await waitFor(() => expect(screen.getByTestId("wake-preview")).toHaveTextContent("Will notify engineer.s-1"));
    expect(screen.getByTestId("wake-preview").getAttribute("title")).toMatch(/engineer\.s-1 — addressed to you/);
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
  it("uploads a dropped file as an attachment chip (never a raw art- token in the text); a refused upload keeps the draft", async () => {
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
    fireEvent.change(screen.getByTestId("composer-text"), { target: { value: "see the shot" } });
    fireEvent.drop(composer, { dataTransfer: { files: [png] } });
    const chip = await screen.findByTestId("attachment-chip");
    expect(chip).toHaveTextContent("a.png");
    expect((screen.getByTestId("composer-text") as HTMLTextAreaElement).value).toBe("see the shot");
    // A refused upload leaves the draft and the chip intact and shows the reason.
    const bad = new File(["x"], "a.exe", { type: "application/x-msdownload" });
    fireEvent.drop(composer, { dataTransfer: { files: [bad] } });
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/Upload failed/));
    expect((screen.getByTestId("composer-text") as HTMLTextAreaElement).value).toBe("see the shot");
    expect(screen.getAllByTestId("attachment-chip")).toHaveLength(1);
  });
});

describe("Composer recipient from @mention (human defect #9, m-a7e74d81b0)", () => {
  it("derives `to` from the first @handle, shows it in the picker, and sends it — no tag stays a broadcast", async () => {
    let sent: any = null;
    server.use(
      http.post("/v1/messages", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json({ ok: true, value: { id: "m-1", unresolved_mentions: [] }, hint: "Sent." });
      }),
    );
    mountComposer();
    const ta = screen.getByTestId("composer-text") as HTMLTextAreaElement;
    typeAt(ta, "plain note, nobody tagged");
    expect(screen.queryByTestId("to-picker")).toBeNull(); // broadcast: no recipient, no picker
    typeAt(ta, "hey @architect.s-1 please look, and @owner too");
    const picker = (await screen.findByTestId("to-picker")) as HTMLSelectElement;
    await waitFor(() => expect(picker.value).toBe("architect.s-1"));
    fireEvent.click(screen.getByTestId("composer-send"));
    await waitFor(() => expect(sent).not.toBeNull());
    expect(sent.to).toBe("architect.s-1");
  });

  it("a hand-picked recipient is not overridden by the text", async () => {
    mountComposer({ showTo: true });
    await screen.findByRole("option", { name: /architect seat/ });
    const picker = screen.getByTestId("to-picker") as HTMLSelectElement;
    fireEvent.change(picker, { target: { value: "owner" } });
    const ta = screen.getByTestId("composer-text") as HTMLTextAreaElement;
    typeAt(ta, "@architect.s-1 fyi");
    await new Promise((r) => setTimeout(r, 20));
    expect(picker.value).toBe("owner");
  });
});

// Adversary round 2 (2026-09-10): #7 the preview carries the draft's @mentions; #8 Ctrl+Enter
// while a send is pending is a no-op and only the SUBMITTED draft is cleared; #14 Esc dismisses the
// mention menu and the keyup on the same token does not reopen it.
describe("Composer round 2", () => {
  it("#7 the wake preview is asked with the draft text", async () => {
    const seen: string[] = [];
    server.use(
      http.post("/v1/messages/resolve", async ({ request }) => {
        const b = (await request.json()) as { text?: string };
        seen.push(b.text ?? "");
        return HttpResponse.json({ ok: true, value: { to: null, wakes: [], plan: [], note: "nobody is woken" } });
      }),
    );
    mountComposer();
    const ta = screen.getByTestId("composer-text") as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: "please coordinate with @owner" } });
    await waitFor(() => expect(seen).toContain("please coordinate with @owner"), { timeout: 2000 });
  });

  it("#8 a second Ctrl+Enter while pending does not post twice; text typed meanwhile survives", async () => {
    let posts = 0;
    let release: () => void = () => {};
    server.use(
      http.post("/v1/messages", async () => {
        posts += 1;
        await new Promise<void>((r) => (release = r));
        return HttpResponse.json({ ok: true, value: { id: "m1", unresolved_mentions: [] }, hint: "Sent." });
      }),
    );
    mountComposer();
    const ta = screen.getByTestId("composer-text") as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: "first" } });
    fireEvent.keyDown(ta, { key: "Enter", ctrlKey: true });
    fireEvent.keyDown(ta, { key: "Enter", ctrlKey: true });
    await waitFor(() => expect(posts).toBe(1));
    fireEvent.change(ta, { target: { value: "second draft" } });
    release();
    await screen.findByTestId("sent-note");
    expect(posts).toBe(1);
    expect(ta.value).toBe("second draft");
  });

  it("#14 Esc closes the mention menu and the same token's keyup keeps it closed", async () => {
    mountComposer({ showTo: true });
    await screen.findByRole("option", { name: /architect seat/ });
    const ta = screen.getByTestId("composer-text") as HTMLTextAreaElement;
    typeAt(ta, "@ar");
    await waitFor(() => expect(screen.getByTestId("mentions-menu")).toBeInTheDocument());
    fireEvent.keyDown(ta, { key: "Escape" });
    fireEvent.keyUp(ta, { key: "Escape" });
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByTestId("mentions-menu")).not.toBeInTheDocument();
    typeAt(ta, "@arc"); // a new partial reopens it
    await waitFor(() => expect(screen.getByTestId("mentions-menu")).toBeInTheDocument());
  });
});

// Promise #16: a "?" popover explains wake / seat / role once, in plain words; every kind and
// role option carries a one-line "who it wakes" gloss.
describe("Composer help (promise #16)", () => {
  it("the ? button opens a dialog explaining wake, seat and role; ✕ and Esc close it", async () => {
    mountComposer({ kinds: ["note", "question"] });
    const toggle = screen.getByRole("button", { name: "How sending works" });
    expect(screen.queryByRole("dialog", { name: "How sending works" })).not.toBeInTheDocument();
    fireEvent.click(toggle);
    const dialog = screen.getByRole("dialog", { name: "How sending works" });
    expect(dialog).toHaveTextContent(/wakes that seat's shell/);
    expect(dialog).toHaveTextContent(/one running agent shell bound to one ticket, named role\.ticket/);
    expect(dialog).toHaveTextContent(/architect, engineer, reviewer, qa, owner or coordinator/);
    fireEvent.click(screen.getByRole("button", { name: "Close help" }));
    expect(screen.queryByRole("dialog", { name: "How sending works" })).not.toBeInTheDocument();
    fireEvent.click(toggle);
    fireEvent.keyDown(screen.getByRole("dialog", { name: "How sending works" }), { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "How sending works" })).not.toBeInTheDocument();
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("kind and role options say who they wake (title; the kind gloss shows with the ? help)", async () => {
    mountComposer({ kinds: ["note", "question"], showTo: true });
    await screen.findByRole("option", { name: /architect seat/ });
    const kindSel = screen.getByLabelText("Message kind") as HTMLSelectElement;
    const note = [...kindSel.options].find((o) => o.value === "note")!;
    expect(note.title).toMatch(/wakes the seats working this ticket/);
    expect(note.textContent).toBe("Message"); // the render's Type: Message; the gloss is the title + help line
    fireEvent.click(screen.getByRole("button", { name: "How sending works" }));
    expect(screen.getByTestId("kind-gloss")).toHaveTextContent(/wakes the seats working this ticket/);
    fireEvent.change(kindSel, { target: { value: "question" } });
    expect(screen.getByTestId("kind-gloss")).toHaveTextContent(/wakes the seat or role you address/);
    const toSel = screen.getByTestId("to-picker") as HTMLSelectElement;
    const roleOpt = [...toSel.options].find((o) => o.value === "architect")!;
    expect(roleOpt.title).toMatch(/wakes the architect on this epic/);
    expect(roleOpt.textContent).toMatch(/wakes the architect on this epic/);
  });
});
