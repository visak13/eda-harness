import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import { ACTION_GLOSS, PAGES, RULES, SIDEBAR } from "./pages";
import { GLOSSARY } from "./glossary";
import { GlossaryPanel } from "../components/GlossaryPanel";
import { SeatsPage } from "../pages/Seats";

// qa m-aa62e7bd8e and the architect's review (m-c4ff88ebae): help, glossary and page copy is written for the owner. It
// carries no finding reference, no API path, no product code name, no board id, no word for the process a seat runs in,
// and no "not equal" sign. A failure names the string and the pattern it tripped.
const FORBIDDEN: Array<[string, RegExp]> = [
  ["a finding reference (#36)", /#\d+/],
  ["an API path (/v1/)", /\/v1\//],
  ["a code name (Astra)", /Astra/],
  ["a board id", /\b(?:s|m|t|epic|c|design|report)-[0-9a-f]{10}\b/],
  ["the word shell", /\bshells?\b/i],
  ["a not-equal sign", /≠/],
  ["an HTTP verb on a path", /\b(?:GET|POST|PUT|PATCH|DELETE) \//],
  ["a bare dash standing alone as a value", /^\s*—\s*$/],
  ["a reference to the copy itself", /\bthe copy\b/i],
  ["a definition written with an equals sign", / = /],
  // qa report-689ceb50f0 fail 7: jargon the owner has to decode, and a retired gate kind
  ["the jargon word fold", /\bfold(?:s|ed)?\b/i],
  ["the jargon phrase phase ladder", /phase ladder/i],
  ["the jargon word rail", /\brail(?:'s)?\b/i],
  ["the jargon phrase source-bound", /source-bound/i],
  ["the jargon word lint", /\blint\b/i],
  ["the retired demo gate", /\bdemo\b/i],
  ["a request header name (the board's admin refusal names them)", /X-Token|X-Participant/],
  ["the board-init bootstrap note", /init human/i],
  ["a third-person 'the owner's words' (the page speaks to the owner: 'your words')", /\bowner's words\b/i],
];

function offences(label: string, text: string): string[] {
  return FORBIDDEN.filter(([, re]) => re.test(text)).map(([why]) => `${label}: ${why} in "${text.slice(0, 120)}"`);
}

describe("user copy", () => {
  it("the copy tables are free of internal wording", () => {
    const found: string[] = [];
    for (const page of [...Object.values(PAGES), SIDEBAR]) {
      found.push(...offences(`${page.key}.framing`, page.framing));
      for (const i of page.items) found.push(...offences(`${page.key}.${i.key}`, `${i.label} ${i.text}`));
    }
    for (const i of RULES) found.push(...offences(`rules.${i.key}`, `${i.label} ${i.text}`));
    for (const [page, glosses] of Object.entries(ACTION_GLOSS)) for (const [k, text] of Object.entries(glosses)) found.push(...offences(`gloss.${page}.${k}`, text));
    for (const [cat, table] of Object.entries(GLOSSARY)) for (const [k, t] of Object.entries(table)) found.push(...offences(`glossary.${cat}.${k}`, `${t.label} ${t.meaning}`));
    expect(found).toEqual([]);
  });

  it("the help panel, rendered for every page, is free of internal wording", () => {
    const found: string[] = [];
    for (const key of Object.keys(PAGES)) {
      const qc = new QueryClient();
      const { container, unmount } = render(
        <QueryClientProvider client={qc}><MemoryRouter><GlossaryPanel open onClose={() => {}} framing="" terms={[]} page={key} /></MemoryRouter></QueryClientProvider>,
      );
      found.push(...offences(`panel(${key})`, container.ownerDocument.body.textContent ?? ""));
      unmount();
    }
    expect(found).toEqual([]);
  });

  it("the help panel never shows a heading with nothing under it (On this page was empty at 390)", () => {
    const found: string[] = [];
    for (const key of Object.keys(PAGES)) {
      const qc = new QueryClient();
      const { container, unmount } = render(
        <QueryClientProvider client={qc}><MemoryRouter><GlossaryPanel open onClose={() => {}} framing="" terms={[]} page={key} /></MemoryRouter></QueryClientProvider>,
      );
      for (const sec of Array.from(container.ownerDocument.querySelectorAll("section"))) {
        if (!sec.querySelector("dt")) found.push(`panel(${key}): "${sec.querySelector("h3")?.textContent}" has no entries`);
      }
      unmount();
    }
    expect(found).toEqual([]);
  });

  it("the Seats page, rendered with every kind of seat, is free of internal wording", async () => {
    const seat = (id: string, state: string | null, over: Record<string, unknown> = {}) => ({ id, handle: id, role: id.split(".")[0], state, ticket_id: state === "dead" ? null : "s-1", ticket_title: "A ticket", last_output_at: null, presence_stale_since: null, reason: state === "dead" ? "closed by owner" : "", latest_status: null, ...over });
    server.use(
      http.get("/v1/seats", () => HttpResponse.json({ ok: true, value: { seats: [seat("engineer.s-1", "alive"), seat("qa.s-2", "dead"), seat("sme.s-3", "parked"), seat("architect.epic-x", null, { ticket_id: null })], people: [] } })),
      http.get("/v1/pool/capabilities", () => HttpResponse.json({ ok: true, value: { resume_parked: true, resume_closed: false, park: true, spawn: false } })),
      http.get("/v1/me/people", () => HttpResponse.json({ ok: true, value: [] })),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container, findByText } = render(<QueryClientProvider client={qc}><MemoryRouter><SeatsPage /></MemoryRouter></QueryClientProvider>);
    await findByText("Not visible here");
    expect(offences("seats", container.textContent ?? "")).toEqual([]);
  });
});
