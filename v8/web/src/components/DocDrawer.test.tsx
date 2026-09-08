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
