import { describe, it, expect } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { HttpResponse } from "msw";
import { server } from "../test/setup";
import { http, okJson, renderRoute } from "../pages/testUtils";
import { DocView } from "./DocView";
import type { DocHtml } from "../api/types";

function doc(over: Partial<DocHtml> = {}): DocHtml {
  return {
    id: "design-1",
    title: "The design",
    doc_type: "design",
    scope: "epic-1",
    owner_role: "architect",
    version: 2,
    versions: [1, 2],
    html: "<p>Body text</p>",
    signoff_criterion: null,
    ...over,
  };
}

describe("DocView", () => {
  it("shows the loading state, then an error banner on failure", async () => {
    server.use(http.get("/v1/docs/design-1/html", () => new HttpResponse(null, { status: 500 })));
    renderRoute("/x", "/x", <DocView docId="design-1" />);
    expect(screen.getByText("Loading document…")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent(/Could not load design-1/);
  });

  it("renders the comment box for a ticket-scoped doc and posts a comment", async () => {
    let body: Record<string, unknown> | null = null;
    server.use(http.get("/v1/docs/design-1/html", () => okJson(doc({ scope: "s-1" }))));
    server.use(
      http.post("/v1/messages", async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return okJson({ id: "m1", unresolved_mentions: [] }, "");
      }),
    );
    renderRoute("/x", "/x", <DocView docId="design-1" />);
    const box = await screen.findByLabelText("Comment");
    fireEvent.change(box, { target: { value: "looks good" } });
    fireEvent.click(screen.getByRole("button", { name: "Comment" }));
    await waitFor(() => expect(body).not.toBeNull());
    expect(String(body!.text)).toContain("[doc design-1 v2] looks good");
    expect(await screen.findByText("Comment posted to the thread.")).toBeInTheDocument();
  });

  it("hides the comment box and request-review for a global-scoped doc", async () => {
    server.use(http.get("/v1/docs/design-1/html", () => okJson(doc({ scope: "global", versions: [1], version: 1 }))));
    renderRoute("/x", "/x", <DocView docId="design-1" />);
    await screen.findByText("Body text");
    expect(screen.queryByLabelText("Comment")).not.toBeInTheDocument();
    expect(screen.queryByTestId("doc-request-review")).not.toBeInTheDocument();
    // single version → no version pills
    expect(screen.queryByLabelText("Versions")).not.toBeInTheDocument();
  });

  it("intercepts a nested doc link so it opens in the same surface", async () => {
    const opened: string[] = [];
    server.use(
      http.get("/v1/docs/design-1/html", () =>
        okJson(doc({ html: '<a href="/doc/design-9">see design-9</a>' })),
      ),
    );
    renderRoute("/x", "/x", <DocView docId="design-1" onOpenDoc={(id) => opened.push(id)} />);
    fireEvent.click(await screen.findByText("see design-9"));
    expect(opened).toEqual(["design-9"]);
  });

  it("intercepts a nested ticket link", async () => {
    const opened: string[] = [];
    server.use(
      http.get("/v1/docs/design-1/html", () =>
        okJson(doc({ html: '<a href="/ticket/s-7">go to s-7</a>' })),
      ),
    );
    renderRoute("/x", "/x", <DocView docId="design-1" onOpenTicket={(id) => opened.push(id)} />);
    fireEvent.click(await screen.findByText("go to s-7"));
    expect(opened).toEqual(["s-7"]);
  });

  it("renders the inline sign-off pane when the board reports a pending criterion", async () => {
    server.use(
      http.get("/v1/docs/design-1/html", () =>
        okJson(doc({ signoff_criterion: { id: "c-1", text: "accept the design", ticket_id: "s-1" } })),
      ),
    );
    renderRoute("/x", "/x", <DocView docId="design-1" />);
    expect(await screen.findByTestId("signoff-pane")).toBeInTheDocument();
    expect(screen.getByText("accept the design")).toBeInTheDocument();
  });
});

// Adversary round 2 #2 (2026-09-10): once "latest" resolves the reader is pinned to that explicit
// version; a refetch of the shared "latest" key (a feed invalidation, or the full page's own query)
// must not advance the body under the reader.
describe("DocView pins the opened version (round 2 #2)", () => {
  it("keeps showing v1 after the board publishes v2 and every query is invalidated", async () => {
    let latest = 1;
    server.use(
      http.get("/v1/docs/design-1/html", ({ request }) => {
        const v = new URL(request.url).searchParams.get("version");
        const n = v ? Number(v) : latest;
        return okJson(doc({ version: n, versions: Array.from({ length: latest }, (_, i) => i + 1), html: `<p>body of version ${n}</p>` }));
      }),
    );
    const { qc } = renderRoute("/doc/design-1", "/doc/:id", <DocView docId="design-1" />);
    await screen.findByText("body of version 1");
    latest = 2;
    await qc.invalidateQueries();
    await new Promise((r) => setTimeout(r, 50));
    await qc.refetchQueries();
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.getByText("body of version 1")).toBeInTheDocument();
    expect(screen.queryByText("body of version 2")).toBeNull();
  });
});
