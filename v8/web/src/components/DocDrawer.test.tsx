import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import { DocDrawerProvider, useDocDrawer } from "./DocDrawer";

const ok = (value: unknown) => HttpResponse.json({ ok: true, value, hint: "" });
function docHtml(id: string, html: string) {
  return {
    id,
    title: `Doc ${id}`,
    doc_type: "design",
    scope: "epic-1",
    owner_role: "architect",
    version: 1,
    versions: [1],
    html,
    signoff_criterion: null,
  };
}

// A page-under-test that carries a draft (the composer stand-in) and a button to open a doc.
function Host(): React.JSX.Element {
  const drawer = useDocDrawer();
  return (
    <div>
      <textarea aria-label="draft" defaultValue="" />
      <button type="button" onClick={() => drawer.openDoc("d1")}>
        open d1
      </button>
    </div>
  );
}

function renderDrawer(initialPath = "/epic/epic-1") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialPath]}>
        <DocDrawerProvider>
          <Host />
        </DocDrawerProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("DocDrawer (§17)", () => {
  it("opens a doc in place, traps focus, and preserves the page draft; Esc closes it", async () => {
    server.use(http.get("/v1/docs/d1/html", () => ok(docHtml("d1", "<p>Doc one body</p>"))));
    renderDrawer();

    // Type a draft on the page, then open the doc.
    const draft = screen.getByLabelText("draft") as HTMLTextAreaElement;
    fireEvent.change(draft, { target: { value: "half-written reply" } });
    fireEvent.click(screen.getByRole("button", { name: "open d1" }));

    const panel = await screen.findByTestId("drawer-panel");
    await within(panel).findByText("Doc one body");
    expect(panel.contains(document.activeElement)).toBe(true); // focus moved in

    // Esc closes; the page draft is untouched (the page never unmounted).
    fireEvent.keyDown(panel, { key: "Escape" });
    await waitFor(() => expect(screen.queryByTestId("drawer-panel")).not.toBeInTheDocument());
    expect((screen.getByLabelText("draft") as HTMLTextAreaElement).value).toBe("half-written reply");
  });

  it("a nested doc link opens in the same drawer with a Back control", async () => {
    server.use(
      http.get("/v1/docs/d1/html", () => ok(docHtml("d1", '<p>one</p><a href="/doc/d2">go to d2</a>'))),
      http.get("/v1/docs/d2/html", () => ok(docHtml("d2", "<p>two body</p>"))),
    );
    renderDrawer();
    fireEvent.click(screen.getByRole("button", { name: "open d1" }));
    const panel = await screen.findByTestId("drawer-panel");
    fireEvent.click(await within(panel).findByText("go to d2"));
    await within(panel).findByText("two body");
    expect(within(panel).getByRole("button", { name: "Back" })).toBeInTheDocument();
  });

  it("a ?doc= deep link opens the drawer on mount", async () => {
    server.use(http.get("/v1/docs/d1/html", () => ok(docHtml("d1", "<p>deep linked</p>"))));
    renderDrawer("/epic/epic-1?doc=d1");
    const panel = await screen.findByTestId("drawer-panel");
    await within(panel).findByText("deep linked");
  });
});

// Astra ruling #36 item (2): the drawer header is the reader's toolbar — doc type, "Open as
// page", ONE version menu labelled "Versions" whose entries switch the reader's pinned version.
describe("DocDrawer toolbar (Astra #36 item 2)", () => {
  it("shows the doc type, the Open as page link and a Versions menu that switches the version", async () => {
    server.use(
      http.get("/v1/docs/d1/html", ({ request }) => {
        const v = new URL(request.url).searchParams.get("version");
        const n = v ? Number(v) : 2;
        return ok({ ...docHtml("d1", `<p>body v${n}</p>`), version: n, versions: [1, 2] });
      }),
    );
    renderDrawer("/epic/epic-1?doc=d1");
    const panel = await screen.findByTestId("drawer-panel");
    await within(panel).findByText("body v2");
    expect(within(panel).getByRole("heading", { level: 1, name: "Doc d1" })).toBeInTheDocument();
    const header = panel.querySelector("header")!;
    expect(within(header).getByText("design")).toBeInTheDocument(); // the toolbar's doc type
    expect(within(panel).getByRole("link", { name: "Open in tab" })).toHaveAttribute(
      "href",
      expect.stringContaining("/doc/d1?version=2&source=epic-1&as="),
    );
    // Exactly one "Versions"-labelled container in the drawer; it holds every entry.
    const menu = within(panel).getByLabelText("Versions");
    expect(menu.tagName).toBe("DETAILS");
    expect(menu.querySelector("summary")?.textContent).toContain("v2 · Latest");
    const entries = within(menu).getAllByTestId("version-entry");
    expect(entries.map((e) => e.textContent)).toEqual(["v1", "v2 · latest"]);
    // The History block keeps its own label so the toolbar menu is the one "Versions" element.
    expect(within(panel).getByTestId("doc-history")).toHaveAttribute("aria-label", "History");

    fireEvent.click(entries[0]);
    await within(panel).findByText("body v1");
    expect(within(panel).getByTestId("version-now")).toHaveTextContent("v1 · pinned (latest v2)");
    expect(menu.querySelector("summary")?.textContent).toContain("v1 · Pinned");
    expect(within(panel).getByRole("link", { name: "Open in tab" })).toHaveAttribute(
      "href",
      expect.stringContaining("/doc/d1?version=1&source=epic-1&as="),
    );
  });
});
