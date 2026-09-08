import { describe, it, expect } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { HttpResponse } from "msw";
import { server } from "../test/setup";
import { http, okJson, renderRoute } from "../pages/testUtils";
import { LinkDocControl, AskRoleControl } from "./TicketAsks";

// Link-doc + ask-a-role (design §16): link POSTs /v1/links from the ticket to the doc; ask POSTs a
// question to a role on the ticket thread. Both surface the board's hint on refusal.

describe("LinkDocControl", () => {
  it("links a doc to the ticket with the chosen relation", async () => {
    let body: unknown = null;
    server.use(
      http.post("/v1/links", async ({ request }) => {
        body = await request.json();
        return okJson({ id: "lk-9" });
      }),
    );
    renderRoute("/x", "/x", <LinkDocControl ticketId="s-1" />);
    fireEvent.change(screen.getByPlaceholderText("document id"), { target: { value: "design-2" } });
    fireEvent.change(screen.getByTestId("link-relation"), { target: { value: "design_ref" } });
    fireEvent.click(screen.getByRole("button", { name: "Link" }));
    await waitFor(() =>
      expect(body).toEqual({ from_id: "s-1", to_id: "design-2", relation: "design_ref" }),
    );
    expect(await screen.findByTestId("link-doc-ok")).toBeInTheDocument();
  });

  it("surfaces the board's refusal hint on a failed link", async () => {
    server.use(
      http.post("/v1/links", () =>
        HttpResponse.json({ ok: false, error: "no such doc", hint: "no such doc" }, { status: 400 }),
      ),
    );
    renderRoute("/x", "/x", <LinkDocControl ticketId="s-1" />);
    fireEvent.change(screen.getByPlaceholderText("document id"), { target: { value: "nope" } });
    fireEvent.click(screen.getByRole("button", { name: "Link" }));
    expect(await screen.findByTestId("link-doc-error")).toBeInTheDocument();
  });
});

describe("AskRoleControl", () => {
  it("asks a role a question on the ticket thread", async () => {
    let body: Record<string, unknown> | null = null;
    server.use(
      http.post("/v1/messages", async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return okJson({ id: "m-9", unresolved_mentions: [] });
      }),
    );
    renderRoute("/x", "/x", <AskRoleControl ticketId="s-1" />);
    fireEvent.change(screen.getByTestId("ask-role-select"), { target: { value: "qa" } });
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "can you re-run it?" } });
    fireEvent.click(screen.getByRole("button", { name: /Ask the/ }));
    await waitFor(() =>
      expect(body).toEqual({ ticket_id: "s-1", kind: "question", to: "qa", text: "can you re-run it?" }),
    );
    expect(await screen.findByTestId("ask-role-ok")).toBeInTheDocument();
  });

  it("surfaces the board's refusal hint on a failed ask", async () => {
    server.use(
      http.post("/v1/messages", () =>
        HttpResponse.json({ ok: false, error: "not allowed", hint: "not allowed" }, { status: 403 }),
      ),
    );
    renderRoute("/x", "/x", <AskRoleControl ticketId="s-1" />);
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "why?" } });
    fireEvent.click(screen.getByRole("button", { name: /Ask the/ }));
    expect(await screen.findByTestId("ask-role-error")).toBeInTheDocument();
  });
});
