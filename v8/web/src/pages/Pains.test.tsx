import { describe, it, expect } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { server } from "../test/setup";
import { http, okJson, renderRoute } from "./testUtils";
import { LibraryPage } from "./Library";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const painsCss = readFileSync(resolve(__dirname, "Pains.module.css"), "utf-8");

// e0cec S6: the Pains view lists the one pain store, filters by status, and links each pain to the commit
// that fixed it or the ticket that owns the fix.
const ROWS = [
  { id: "p-aaaaaaa1", ts: "2026-09-30T10:00:00Z", severity: "medium", area: "tools", role: "sme", symptom: "doc_read drops proposed docs", status: "open" },
  { id: "p-bbbbbbb2", ts: "2026-09-29T10:00:00Z", severity: "high", area: "board", role: "qa", symptom: "a dead checker strands the criterion", status: "fixed",
    fixed_commit: "4644c81abc", commit_url: "https://github.com/o/r/commit/4644c81abc" },
  { id: "p-ccccccc3", ts: "2026-09-28T10:00:00Z", severity: "low", area: "tools", role: "engineer", symptom: "artifact_upload refused", status: "ticket", ticket_ref: "s-6c2f5a8593" },
  { id: "p-ddddddd4", ts: "2026-09-27T10:00:00Z", severity: "low", area: "tools", role: "engineer", symptom: "artifact_upload refused again", status: "duplicate", dup_of: "p-ccccccc3" },
];

function serve(seen: string[] = []) {
  server.use(http.get("/v1/pains", ({ request }) => {
    const u = new URL(request.url);
    seen.push(u.search);
    const st = u.searchParams.get("status") ?? "open";
    return okJson(st === "all" ? ROWS : ROWS.filter((r) => r.status === st));
  }));
}

describe("Pains view", () => {
  it("lists open pains by default and says how many", async () => {
    const seen: string[] = [];
    serve(seen);
    renderRoute("/library/pains", "/library/:section", <LibraryPage />);
    expect(await screen.findByText("doc_read drops proposed docs")).toBeInTheDocument();
    expect(screen.getAllByTestId("pain-row")).toHaveLength(1);
    expect(screen.getByTestId("pains-count")).toHaveTextContent("1 pain");
    expect(screen.getByTestId("pains-status")).toHaveValue("open");
    expect(seen[0]).toContain("status=open");
    expect(screen.getByRole("link", { name: "Pains" })).toBeInTheDocument();
    // S12-ui2 (m1): sentence-case column headers
    expect(Array.from(screen.getByTestId("pains-table").querySelectorAll("th")).map((th) => th.textContent))
      .toEqual(["Id", "Severity", "Area", "Symptom", "Status", "Commit or ticket"]);
  });

  it("filters by status and links a fixed pain to its commit and a ticketed pain to its ticket", async () => {
    serve();
    renderRoute("/library/pains", "/library/:section", <LibraryPage />);
    await screen.findByTestId("pains-table");
    fireEvent.change(screen.getByTestId("pains-status"), { target: { value: "fixed" } });
    const row = await screen.findByText("a dead checker strands the criterion");
    const commit = within(row.closest("tr")!).getByRole("link", { name: "commit 4644c81abc" });
    expect(commit).toHaveAttribute("href", "https://github.com/o/r/commit/4644c81abc");
    expect(commit).toHaveTextContent("4644c81abc");
    expect(screen.queryByText("doc_read drops proposed docs")).toBeNull();

    fireEvent.change(screen.getByTestId("pains-status"), { target: { value: "ticket" } });
    const t = await screen.findByText("artifact_upload refused");
    const ticket = within(t.closest("tr")!).getByRole("link", { name: "s-6c2f5a8593" });
    expect(ticket).toHaveAttribute("href", "/ticket/s-6c2f5a8593");
    expect(within(t.closest("tr")!).getByTestId("pain-status")).toHaveTextContent("Ticketed");
  });

  it("m11: a commit without a URL stays muted text, and commit and ticket refs use the link styling", async () => {
    server.use(http.get("/v1/pains", () => okJson([{ ...ROWS[1], commit_url: null }])));
    renderRoute("/library/pains?status=fixed", "/library/:section", <LibraryPage />);
    const sha = await screen.findByTestId("pain-commit-unlinked");
    expect(sha).toHaveTextContent("4644c81abc");
    expect(within(sha.closest("tr")!).queryByRole("link")).toBeNull();
    const a = /\.ref a\s*\{([^}]*)\}/.exec(painsCss)?.[1] ?? "";
    expect(a).toMatch(/color:\s*var\(--accentink\)/);
    expect(a).toMatch(/text-decoration:\s*underline/);
    const code = [...painsCss.matchAll(/\.ref code\s*\{([^}]*)\}/g)].map((m) => m[1]).join("");
    expect(code).toMatch(/color:\s*var\(--muted\)/);
  });

  it("all shows every status with a word each, and a duplicate names its original", async () => {
    serve();
    renderRoute("/library/pains?status=all", "/library/:section", <LibraryPage />);
    await waitFor(() => expect(screen.getAllByTestId("pain-row")).toHaveLength(4));
    expect(screen.getAllByTestId("pain-status").map((n) => n.textContent)).toEqual(["Open", "Fixed", "Ticketed", "Duplicate"]);
    const dup = screen.getByText("artifact_upload refused again").closest("tr")!;
    expect(dup).toHaveTextContent("of p-ccccccc3");
  });

  it("an empty filter says so, and a failed read shows the board's message", async () => {
    serve();
    renderRoute("/library/pains?status=invalid", "/library/:section", <LibraryPage />);
    expect(await screen.findByText("No invalid pains.")).toBeInTheDocument();
  });

  it("shows the board's error", async () => {
    server.use(http.get("/v1/pains", () => new Response(JSON.stringify({ ok: false, hint: "pain store offline" }), { status: 503 })));
    renderRoute("/library/pains", "/library/:section", <LibraryPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/pain store offline/);
  });
});
