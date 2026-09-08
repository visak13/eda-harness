import { describe, it, expect } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { server } from "../test/setup";
import { http, okJson, renderRoute } from "../pages/testUtils";
import { DocControls } from "./DocControls";

// Doc controls (design §16): request review posts a question to a role on the doc's scope thread;
// new version PATCHes the doc body. Both surface the board's hint on refusal.

describe("DocControls", () => {
  it("requests a review by posting a question to the chosen role on the scope thread", async () => {
    let body: Record<string, unknown> | null = null;
    server.use(
      http.post("/v1/messages", async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return okJson({ id: "m-9", unresolved_mentions: [] }, "");
      }),
    );
    renderRoute("/x", "/x", <DocControls docId="design-1" scope="epic-1" version={3} scopeIsThread />);
    fireEvent.change(screen.getByTestId("review-role"), { target: { value: "qa" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask for a review" }));
    await waitFor(() => expect(body).not.toBeNull());
    expect(body).toMatchObject({ ticket_id: "epic-1", kind: "question", to: "qa" });
    expect(String((body as Record<string, unknown>).text)).toContain("[doc design-1 v3]");
    expect(await screen.findByTestId("doc-review-asked")).toBeInTheDocument();
  });

  it("hides request-review when the doc's scope is not a thread", () => {
    renderRoute("/x", "/x", <DocControls docId="d1" scope="global" version={1} scopeIsThread={false} />);
    expect(screen.queryByTestId("doc-request-review")).not.toBeInTheDocument();
    expect(screen.getByTestId("doc-new-version-open")).toBeInTheDocument();
  });

  it("publishes a new version by PATCHing the doc body", async () => {
    let patched: Record<string, unknown> | null = null;
    server.use(
      http.patch("/v1/docs/d1", async ({ request }) => {
        patched = (await request.json()) as Record<string, unknown>;
        return okJson({ id: "d1", version: 2 });
      }),
    );
    renderRoute("/x", "/x", <DocControls docId="d1" scope="global" version={1} scopeIsThread={false} />);
    fireEvent.click(screen.getByTestId("doc-new-version-open"));
    fireEvent.change(screen.getByLabelText(/New version/), { target: { value: "# v2\nnew body" } });
    fireEvent.click(screen.getByRole("button", { name: "Publish new version" }));
    await waitFor(() => expect(patched).toEqual({ body_md: "# v2\nnew body" }));
  });
});
