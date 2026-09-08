import { describe, it, expect } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { server } from "../test/setup";
import { http, HttpResponse, okJson, renderRoute } from "../pages/testUtils";
import { StatusControl } from "./StatusControl";
import type { TicketTransitions } from "../api/types";

// StatusControl (design §16): the legal set and each blocked reason come from the SERVER; the
// control only renders them and reports the board's resolution note when a move is refused.

const TRANSITIONS: TicketTransitions = {
  status: "in_review",
  transitions: [
    { to: "done", allowed: false, reason: "done is set by the checker (reviewer/qa/owner) or the coordinator" },
    { to: "in_progress", allowed: true, reason: null },
    { to: "partial", allowed: true, reason: null },
  ],
};

function mount(over: Partial<TicketTransitions> = {}) {
  server.use(http.get("/v1/tickets/s-1/transitions", () => okJson({ ...TRANSITIONS, ...over })));
  renderRoute("/x", "/x", <StatusControl ticketId="s-1" currentStatus="in_review" />);
}

describe("StatusControl", () => {
  it("renders each server-offered move with the current status first", async () => {
    mount();
    await screen.findByTestId("status-control");
    expect(screen.getByTestId("status-now")).toHaveTextContent("In review");
    const moves = screen.getAllByTestId("status-move").map((m) => m.getAttribute("data-to"));
    expect(moves).toEqual(["done", "in_progress", "partial"]);
    expect(screen.getByTestId("status-move-in_progress")).toBeEnabled();
  });

  it("disables a blocked move and shows the board's own reason", async () => {
    mount();
    await screen.findByTestId("status-control");
    expect(screen.getByTestId("status-move-done")).toBeDisabled();
    expect(screen.getByTestId("status-move-reason")).toHaveTextContent(/checker/);
  });

  it("moves the ticket by PATCHing status, then invalidates the ticket", async () => {
    let patched: unknown = null;
    server.use(
      http.patch("/v1/tickets/s-1", async ({ request }) => {
        patched = await request.json();
        return okJson({ id: "s-1", status: "in_progress" });
      }),
    );
    mount();
    await screen.findByTestId("status-control");
    fireEvent.click(screen.getByTestId("status-move-in_progress"));
    await waitFor(() => expect(patched).toEqual({ status: "in_progress" }));
  });

  it("surfaces the board hint when a move is refused", async () => {
    server.use(
      http.patch("/v1/tickets/s-1", () =>
        HttpResponse.json({ ok: false, hint: "in_progress needs an assignee" }, { status: 409 }),
      ),
    );
    mount();
    await screen.findByTestId("status-control");
    fireEvent.click(screen.getByTestId("status-move-in_progress"));
    expect(await screen.findByTestId("status-move-error")).toHaveTextContent("needs an assignee");
  });
});
