import { describe, it, expect } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { server } from "../test/setup";
import { http, okJson, renderRoute } from "../pages/testUtils";
import { AddCriterion, RewordCriterion } from "./CriterionControls";

// Criterion controls (design §16): add posts to /v1/criteria with the derived checked_by left to
// the board; reword PATCHes the same criterion. Both surface the board's hint on refusal.

describe("AddCriterion", () => {
  it("posts a new criterion with its text and check, then invalidates the ticket", async () => {
    let posted: Record<string, unknown> | null = null;
    server.use(
      http.post("/v1/criteria", async ({ request }) => {
        posted = (await request.json()) as Record<string, unknown>;
        return okJson({ id: "c-9", text: posted.text });
      }),
    );
    renderRoute("/x", "/x", <AddCriterion ticketId="s-1" />);
    fireEvent.change(screen.getByLabelText("New acceptance criterion"), {
      target: { value: "the sheet renders" },
    });
    fireEvent.change(screen.getByTestId("add-criterion-check"), { target: { value: "look" } });
    fireEvent.click(screen.getByRole("button", { name: "Add criterion" }));
    await waitFor(() =>
      expect(posted).toEqual({ ticket_id: "s-1", text: "the sheet renders", check: "look" }),
    );
  });

  it("shows the board hint when the write is refused", async () => {
    // a refusal is a non-ok envelope carrying the board's plain-sentence hint
    server.use(
      http.post("/v1/criteria", () =>
        new Response(JSON.stringify({ ok: false, hint: "only the architect adds criteria here" }), {
          status: 403,
          headers: { "content-type": "application/json" },
        }),
      ),
    );
    renderRoute("/x", "/x", <AddCriterion ticketId="s-1" />);
    fireEvent.change(screen.getByLabelText("New acceptance criterion"), {
      target: { value: "x" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add criterion" }));
    expect(await screen.findByTestId("add-criterion-error")).toHaveTextContent("only the architect");
  });
});

describe("RewordCriterion", () => {
  it("PATCHes the criterion text and calls onDone", async () => {
    let patched: Record<string, unknown> | null = null;
    let done = false;
    server.use(
      http.patch("/v1/criteria/c-1", async ({ request }) => {
        patched = (await request.json()) as Record<string, unknown>;
        return okJson({ id: "c-1" });
      }),
    );
    renderRoute(
      "/x",
      "/x",
      <RewordCriterion criterionId="c-1" ticketId="s-1" current="old text" onDone={() => (done = true)} />,
    );
    fireEvent.change(screen.getByLabelText("Reword this criterion"), {
      target: { value: "new text" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save wording" }));
    await waitFor(() => expect(patched).toEqual({ text: "new text" }));
    expect(done).toBe(true);
  });

  it("skips the write and just closes when the text is unchanged", async () => {
    let done = false;
    renderRoute(
      "/x",
      "/x",
      <RewordCriterion criterionId="c-1" ticketId="s-1" current="same" onDone={() => (done = true)} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Save wording" }));
    expect(done).toBe(true);
  });
});
