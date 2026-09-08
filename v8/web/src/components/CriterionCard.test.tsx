import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import type { CriterionView } from "../api/types";
import { CriterionCard } from "./CriterionCard";

const crit: CriterionView = {
  id: "c-abc123",
  text: "The featured card is the oldest pending owner sign-off.",
  check: "verdict",
  checked_by: "owner",
  verdict: "pending",
  evidence_ref: "report-1",
  evidence_version: 2,
};

function renderCard(props: Partial<React.ComponentProps<typeof CriterionCard>> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <CriterionCard criterion={crit} {...props} />
    </QueryClientProvider>,
  );
}

describe("CriterionCard", () => {
  it("shows the criterion text verbatim with the id on its own line, not inline", () => {
    renderCard();
    expect(screen.getByText(crit.text)).toBeInTheDocument();
    // The id renders in its own element (the mono line), never spliced into the sentence.
    expect(screen.getByText("c-abc123")).toBeInTheDocument();
    expect(screen.getByText(crit.text).textContent).not.toContain("c-abc123");
  });

  it("ruling mode: nothing preselected; Needs work disabled until a note is typed", () => {
    renderCard({ ruling: { evidenceVersion: 2 }, ticketId: "s-1" });
    expect(screen.getByTestId("verdict-chip")).toHaveTextContent("Pending");
    expect(screen.getByTestId("needs-work")).toBeDisabled();
    fireEvent.change(screen.getByLabelText("NOTE TO THE AUTHOR"), { target: { value: "needs a test" } });
    expect(screen.getByTestId("needs-work")).toBeEnabled();
  });

  it("Approve posts /v1/me/verdict with the criterion id + frozen evidence_version and flips to Passed", async () => {
    let body: Record<string, unknown> | null = null;
    server.use(
      http.post("/v1/me/verdict", async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ok: true, value: { criterion: {}, message: null } });
      }),
    );
    renderCard({ ruling: { evidenceVersion: 2 }, ticketId: "s-1" });
    fireEvent.click(screen.getByTestId("approve"));
    await waitFor(() => expect(screen.getByTestId("verdict-chip")).toHaveTextContent("Passed"));
    expect(body).toMatchObject({ criterion_id: "c-abc123", verdict: "pass", evidence_version: 2, ticket_id: "s-1" });
  });

  it("a failed POST keeps the typed note and shows a retryable error", async () => {
    server.use(http.post("/v1/me/verdict", () => HttpResponse.json({ ok: false, hint: "stale version" }, { status: 409 })));
    renderCard({ ruling: { evidenceVersion: 2 }, ticketId: "s-1" });
    fireEvent.change(screen.getByLabelText("NOTE TO THE AUTHOR"), { target: { value: "please redo" } });
    fireEvent.click(screen.getByTestId("needs-work"));
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect((screen.getByLabelText("NOTE TO THE AUTHOR") as HTMLTextAreaElement).value).toBe("please redo");
  });

  it("resets its ruling state when pointed at a different criterion (no leak across sign-offs)", async () => {
    server.use(http.post("/v1/me/verdict", () => HttpResponse.json({ ok: true, value: { criterion: {}, message: null } })));
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    const { rerender } = render(
      <QueryClientProvider client={qc}>
        <CriterionCard criterion={crit} ruling={{ evidenceVersion: 2 }} ticketId="s-1" />
      </QueryClientProvider>,
    );
    // Rule on criterion A → it latches "Recorded: Passed".
    fireEvent.change(screen.getByLabelText("NOTE TO THE AUTHOR"), { target: { value: "A note" } });
    fireEvent.click(screen.getByTestId("approve"));
    await waitFor(() => expect(screen.getByTestId("verdict-chip")).toHaveTextContent("Passed"));

    // The SAME card instance is now pointed at criterion B → it must NOT inherit A's state.
    const critB = { ...crit, id: "c-def456", text: "A different criterion.", verdict: "pending" as const };
    rerender(
      <QueryClientProvider client={qc}>
        <CriterionCard criterion={critB} ruling={{ evidenceVersion: 2 }} ticketId="s-1" />
      </QueryClientProvider>,
    );
    expect(screen.getByTestId("verdict-chip")).toHaveTextContent("Pending");
    expect(screen.getByTestId("approve")).toBeInTheDocument(); // ruling controls, not a "Recorded" latch
    expect((screen.getByLabelText("NOTE TO THE AUTHOR") as HTMLTextAreaElement).value).toBe("");
  });

  it("read-only mode (no ruling): shows the verdict word and opens evidence", () => {
    const onOpenEvidence = vi.fn();
    renderCard({ criterion: { ...crit, verdict: "pass" }, onOpenEvidence });
    expect(screen.getByTestId("verdict-chip")).toHaveTextContent("Passed");
    fireEvent.click(screen.getByText("Open evidence ↗"));
    expect(onOpenEvidence).toHaveBeenCalledWith("report-1");
  });
});
