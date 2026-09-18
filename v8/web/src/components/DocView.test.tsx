import { describe, it, expect } from "vitest";
import { screen, waitFor, fireEvent, within } from "@testing-library/react";
import { HttpResponse } from "msw";
import { server } from "../test/setup";
import { http, okJson, renderRoute } from "../pages/testUtils";
import { DocView, stripScopeId } from "./DocView";
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

  it("requires explicit source selection and posts a structured local document comment", async () => {
    let body: Record<string, unknown> | null = null;
    server.use(http.get("/v1/docs/design-1/html", () => okJson(doc({ scope: "s-1" }))));
    server.use(
      http.post("/v1/docs/comments", async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return okJson({ message_id: "m1" }, "");
      }),
    );
    renderRoute("/x", "/x", <DocView docId="design-1" />);
    await screen.findByRole("option", { name: "Source work · epic-1" });
    fireEvent.change(screen.getByLabelText("Conversation source"), { target: { value: "epic-1" } });
    fireEvent.click(await screen.findByRole("button", { name: "Comment without requesting changes" }));
    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "looks good" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(body).not.toBeNull());
    expect(body).toMatchObject({ text: "looks good", ticket_id: "epic-1", design_ref: "design-1", reviewed_version: 2 });
    expect(await screen.findByText("Comment posted to the source conversation.")).toBeInTheDocument();
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

// Astra ruling #36 item (2): the side pane's blocks and the display-title id strip.
describe("DocView side pane (Astra #36 item 2)", () => {
  it("stripScopeId drops a trailing scope-id suffix only", () => {
    expect(stripScopeId("Folio craft bars (epic-1b289d63f9)")).toBe("Folio craft bars");
    expect(stripScopeId("Design (s-edb266895d)")).toBe("Design");
    expect(stripScopeId("Plan (t-1a2b3c)")).toBe("Plan");
    expect(stripScopeId("Plan (t-1a2b3c)  ")).toBe("Plan");
    expect(stripScopeId("Notes (draft)")).toBe("Notes (draft)");
    expect(stripScopeId("(s-1) leading stays")).toBe("(s-1) leading stays");
    expect(stripScopeId("No suffix")).toBe("No suffix");
  });

  it("renders the Georgia title without the scope id and the meta line (type · id · version)", async () => {
    server.use(http.get("/v1/docs/design-1/html", () => okJson(doc({ title: "The design (epic-1)" }))));
    renderRoute("/x", "/x", <DocView docId="design-1" />);
    const h1 = await screen.findByRole("heading", { level: 1, name: "The design" });
    expect(h1).toHaveAttribute("data-testid", "doc-title");
    expect(screen.getByTestId("doc-meta")).toHaveTextContent("design·design-1·v2 · latest");
  });

  it("outline lists h1/h2/h3 headings as buttons that scroll the matching body heading", async () => {
    const scrolled: string[] = [];
    Element.prototype.scrollIntoView = function (this: Element) {
      scrolled.push(this.textContent ?? "");
    };
    server.use(
      http.get("/v1/docs/design-1/html", () =>
        okJson(doc({ html: "<h1>Intro</h1><p>a</p><h2>Scope</h2><p>b</p><h3>Detail</h3><h4>Ignored</h4>" })),
      ),
    );
    renderRoute("/x", "/x", <DocView docId="design-1" />);
    const outline = await screen.findByTestId("doc-outline");
    const buttons = within(outline).getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual(["Intro", "Scope", "Detail"]);
    fireEvent.click(buttons[1]);
    expect(scrolled).toEqual(["Scope"]);
    // The target is the demoted body heading (h2 → h3), not the outline button.
    const target = document.querySelector(".doc-md h3");
    expect(target?.textContent).toBe("Scope");
  });

  it("renders no outline when the body has no headings", async () => {
    server.use(http.get("/v1/docs/design-1/html", () => okJson(doc())));
    renderRoute("/x", "/x", <DocView docId="design-1" />);
    await screen.findByText("Body text");
    expect(screen.queryByTestId("doc-outline")).not.toBeInTheDocument();
  });

  it("ownership lists type, owner and a scope link to the ticket", async () => {
    server.use(http.get("/v1/docs/design-1/html", () => okJson(doc({ scope: "s-9", doc_type: "strategy_ll" }))));
    const opened: string[] = [];
    renderRoute("/x", "/x", <DocView docId="design-1" onOpenTicket={(id) => opened.push(id)} />);
    const own = await screen.findByTestId("doc-ownership");
    const terms = Array.from(own.querySelectorAll("dt")).map((d) => d.textContent);
    const defs = Array.from(own.querySelectorAll("dd")).map((d) => d.textContent);
    expect(terms).toEqual(["Type", "Owner", "Scope"]);
    expect(defs).toEqual(["strategy ll", "architect", "s-9"]);
    const link = within(own).getByRole("link", { name: "s-9" });
    expect(link).toHaveAttribute("href", "/ticket/s-9");
    fireEvent.click(link);
    expect(opened).toEqual(["s-9"]); // the drawer intercepts it (no navigation)
  });

  it("history details lists every version with the latest marked and switches on click", async () => {
    server.use(
      http.get("/v1/docs/design-1/html", ({ request }) => {
        const v = new URL(request.url).searchParams.get("version");
        const n = v ? Number(v) : 3;
        return okJson(doc({ version: n, versions: [1, 2, 3], html: `<p>body v${n}</p>` }));
      }),
    );
    renderRoute("/x", "/x", <DocView docId="design-1" />);
    const history = await screen.findByTestId("doc-history");
    expect(history.tagName).toBe("DETAILS");
    expect(history).toHaveAttribute("aria-label", "Versions"); // e2e getByLabel("Versions") on the page
    const pills = within(history).getAllByTestId("version-pill");
    expect(pills.map((p) => p.textContent)).toEqual(["v1", "v2", "v3 · latest"]);
    expect(pills[2]).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(pills[0]);
    await screen.findByText("body v1");
    expect(screen.getByTestId("version-now")).toHaveTextContent("v1 · pinned (latest v3)");
  });

  it("the sign-off pane sits in the side pane, before the outline", async () => {
    server.use(
      http.get("/v1/docs/design-1/html", () =>
        okJson(doc({ html: "<h2>One</h2>", signoff_criterion: { id: "c-1", text: "accept", ticket_id: "s-1" } })),
      ),
    );
    renderRoute("/x", "/x", <DocView docId="design-1" />);
    const side = await screen.findByTestId("doc-side");
    const pane = within(side).getByLabelText("Your sign-off");
    const outline = within(side).getByTestId("doc-outline");
    expect(pane.compareDocumentPosition(outline) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

// The sign-off pane stays mounted after the ruling removes the criterion from the doc's list
// (DocView latch; c-a0b2f8ddda "Passed" without a navigation).
it("keeps the sign-off pane mounted when a refetched doc no longer lists the criterion", async () => {
  let serve = doc({ signoff_criteria: [{ id: "c-1", text: "Looks right", ticket_id: "s-1", checked_by: "owner" }] } as Partial<DocHtml>);
  server.use(http.get("/v1/docs/design-1/html", () => okJson(serve)));
  const { qc } = renderRoute("/x", "/x", <DocView docId="design-1" />);
  expect(await screen.findByTestId("signoff-pane")).toBeInTheDocument();
  serve = doc({ signoff_criteria: [] } as Partial<DocHtml>);
  await qc.invalidateQueries();
  await waitFor(() => expect(screen.getByTestId("doc-view")).toBeInTheDocument());
  await new Promise((r) => setTimeout(r, 50));
  expect(screen.getByTestId("signoff-pane")).toBeInTheDocument();
});
