import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it } from "vitest";
import { linkifyMessageHtml } from "./components/Markdown";
import { cleanRouteId, useRouteId } from "./routeId";

// S16 c-017559b2a9 (owner m-cc3a6656ee): the architect's direct link "…/ui/ticket/s-b153dc54eb." opened
// "ticket 's-b153dc54eb.' does not exist". The thread link must stop before the sentence's punctuation, and the
// route must forgive an id that still carries it.

function hrefs(html: string): string[] {
  const doc = new DOMParser().parseFromString(`<body>${html}</body>`, "text/html");
  return [...doc.querySelectorAll("a")].map(a => a.getAttribute("href") ?? "");
}

describe("thread linkifier keeps trailing punctuation outside the link", () => {
  it("a URL that ends a sentence links without the full stop, and the stop stays as text", () => {
    const out = linkifyMessageHtml("<p>Open http://127.0.0.1:9400/ui/ticket/s-b153dc54eb.</p>");
    expect(hrefs(out)).toEqual(["http://127.0.0.1:9400/ui/ticket/s-b153dc54eb"]);
    const p = new DOMParser().parseFromString(out, "text/html").querySelector("p");
    expect(p?.textContent).toBe("Open http://127.0.0.1:9400/ui/ticket/s-b153dc54eb.");
    expect(p?.querySelector("a")?.textContent).toBe("http://127.0.0.1:9400/ui/ticket/s-b153dc54eb");
  });

  it.each([
    ["comma", "see http://h.test/ui/doc/strategyhl-5af811e7bd, then", "http://h.test/ui/doc/strategyhl-5af811e7bd"],
    ["semicolon", "http://h.test/ui/doc/d-1; next", "http://h.test/ui/doc/d-1"],
    ["colon", "at http://h.test/ui/ticket/s-1: press Pass", "http://h.test/ui/ticket/s-1"],
    ["question", "did you open http://h.test/ui/ticket/s-1?", "http://h.test/ui/ticket/s-1"],
    ["exclamation", "open http://h.test/ui/ticket/s-1!", "http://h.test/ui/ticket/s-1"],
    ["paren", "(the doc: http://h.test/ui/doc/d-1)", "http://h.test/ui/doc/d-1"],
    ["paren + stop", "(http://h.test/ui/doc/d-1).", "http://h.test/ui/doc/d-1"],
    ["curly quote", "“http://h.test/ui/ticket/s-1”", "http://h.test/ui/ticket/s-1"],
    ["single curly quote", "‘http://h.test/ui/ticket/s-1’", "http://h.test/ui/ticket/s-1"],
    ["straight quote", "\"http://h.test/ui/ticket/s-1\"", "http://h.test/ui/ticket/s-1"],
  ])("%s", (_name, text, want) => {
    expect(hrefs(linkifyMessageHtml(`<p>${text}</p>`))).toEqual([want]);
  });

  it("keeps a URL's inner punctuation (query, path dots, port)", () => {
    const url = "https://h.test:9400/ui/doc/d-1?v=2&x=a.b";
    expect(hrefs(linkifyMessageHtml(`<p>${url}</p>`))).toEqual([url]);
  });
});

describe("the /ticket/:id and /doc/:id routes strip trailing punctuation from the id", () => {
  it.each([
    ["s-b153dc54eb.", "s-b153dc54eb"],
    ["s-b153dc54eb", "s-b153dc54eb"],
    ["strategyhl-5af811e7bd),", "strategyhl-5af811e7bd"],
    ["s-1%2E", "s-1"],
    ["s-1”", "s-1"],
    ["s-1!?", "s-1"],
  ])("%s → %s", (raw, want) => {
    expect(cleanRouteId(raw)).toBe(want);
  });

  it.each(["/ticket/s-b153dc54eb.", "/doc/s-b153dc54eb;"])("useRouteId reads %s as the bare id", (path) => {
    function Probe() { return <span data-testid="id">{useRouteId()}</span>; }
    render(
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/ticket/:id" element={<Probe />} />
          <Route path="/doc/:id" element={<Probe />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("id")).toHaveTextContent(/^s-b153dc54eb$/);
  });
});
