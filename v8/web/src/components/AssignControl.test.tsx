import { describe, it, expect } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { server } from "../test/setup";
import { http, okJson, renderRoute } from "../pages/testUtils";
import { AssignControl } from "./AssignControl";

// Assign / spawn (design §16): assign PATCHes the ticket; spawn shows only when the pool reports it
// can, and reports the board's plain-sentence reason when it can't.

const caps = (over: Record<string, unknown> = {}) =>
  http.get("/v1/pool/capabilities", () =>
    okJson({ resume_parked: true, resume_closed: false, park: true, spawn: true, ...over }),
  );

describe("AssignControl", () => {
  it("assigns an existing participant by PATCHing the ticket", async () => {
    let patched: unknown = null;
    server.use(caps());
    server.use(
      http.patch("/v1/tickets/s-1", async ({ request }) => {
        patched = await request.json();
        return okJson({ id: "s-1", assignee: "ravi" });
      }),
    );
    renderRoute("/x", "/x", <AssignControl ticketId="s-1" currentAssignee={null} />);
    expect(screen.getByTestId("assign-current")).toHaveTextContent("no one yet");
    fireEvent.change(screen.getByLabelText("Assign an existing seat or person"), {
      target: { value: "ravi" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Assign" }));
    await waitFor(() => expect(patched).toEqual({ assignee: "ravi" }));
  });

  it("offers spawn only when the pool reports it can", async () => {
    server.use(caps({ spawn: false, reason: "no pool is attached in this environment" }));
    renderRoute("/x", "/x", <AssignControl ticketId="s-1" currentAssignee="engineer.s-1" />);
    // wait for the capabilities query to resolve, then the pool's own reason is shown
    await screen.findByText("no pool is attached in this environment");
    expect(screen.getByTestId("spawn-unavailable")).toBeInTheDocument();
    expect(screen.queryByTestId("spawn-seat")).not.toBeInTheDocument();
  });

  it("spawns a fresh engineer seat for the ticket when the pool can", async () => {
    let body: Record<string, unknown> | null = null;
    server.use(caps({ spawn: true }));
    server.use(
      http.post("/v1/sessions/spawn", async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return okJson({ ok: true, session: "sid-2" });
      }),
    );
    renderRoute("/x", "/x", <AssignControl ticketId="s-1" currentAssignee={null} />);
    fireEvent.click(await screen.findByTestId("spawn-seat"));
    await waitFor(() =>
      expect(body).toEqual({ role: "engineer", participant_id: "engineer.s-1", ticket_id: "s-1" }),
    );
  });
});
