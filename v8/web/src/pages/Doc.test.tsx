import { describe, it, expect } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { server } from "../test/setup";
import { http, okJson, renderRoute } from "./testUtils";
import { DocPage } from "./Doc";
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
    html: "<h1>Design</h1><p>Safe body</p>",
    signoff_criterion: null,
    ...over,
  };
}

describe("DocPage", () => {
  it("renders the doc title and its sanitised HTML", async () => {
    server.use(http.get("/v1/docs/design-1/html", () => okJson(doc())));
    renderRoute("/doc/design-1", "/doc/:id", <DocPage />);
    await screen.findByRole("heading", { level: 1, name: "The design" });
    await waitFor(() => expect(screen.getByText("Safe body")).toBeInTheDocument());
  });

  it("DOMPurify strips an injected <script> and an onerror handler from a hostile fixture", async () => {
    const hostile = '<p>ok</p><script>window.__pwned=1</script><img src=x onerror="window.__pwned=2">';
    server.use(http.get("/v1/docs/design-1/html", () => okJson(doc({ html: hostile }))));
    renderRoute("/doc/design-1", "/doc/:id", <DocPage />);
    await waitFor(() => expect(screen.getByText("ok")).toBeInTheDocument());
    // The script element never reaches the sanitised body, and no onerror attribute survives.
    expect(document.querySelector(".doc-md script")).toBeNull();
    const img = document.querySelector(".doc-md img");
    expect(img?.getAttribute("onerror") ?? null).toBeNull();
  });

  it("version pills show the versions with the latest marked", async () => {
    localStorage.setItem("edp8.doc.reader", "0"); // the pills live in the side panel (reader mode hides it)
    server.use(http.get("/v1/docs/design-1/html", () => okJson(doc())));
    renderRoute("/doc/design-1", "/doc/:id", <DocPage />);
    // Human #30: versions collapse to "vN · latest" on the meta line + a menu holding every pill
    await screen.findByTestId("version-now");
    expect(screen.getByTestId("version-now")).toHaveTextContent("v2 · latest");
    const pills = screen.getAllByTestId("version-pill");
    expect(pills.map((p) => p.textContent)).toEqual(["v1", "v2 · latest"]);
  });
});
