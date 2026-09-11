import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import type { SignoffRow } from "../api/types";
import { RulingDrawer } from "./RulingDrawer";
import { uploadArtifact } from "../api/endpoints";

// The upload's multipart body cannot be read back in an msw handler under jsdom (request.text() /
// formData() never resolve), so the ticket the drop uploads against is asserted on the endpoint
// call itself: a pass-through spy on uploadArtifact.
vi.mock("../api/endpoints", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../api/endpoints")>();
  return { ...orig, uploadArtifact: vi.fn(orig.uploadArtifact) };
});

const signoff: SignoffRow = {
  criterion: {
    id: "c-1",
    text: "The report proves the criterion from cold.",
    check: "verdict",
    checked_by: "owner",
    verdict: "pending",
    evidence_ref: "report-1",
    evidence_version: 1,
  },
  ticket: { id: "s-1", title: "G1a backend", epic_id: "epic-1", epic_title: "Board redesign", assignee: "engineer.s-1" },
  doc: { id: "report-1", title: "G1a engineer report", doc_type: "report", version: 1 },
  excerpt: "The backend endpoints…",
};

function docHtml(version: number, versions: number[]) {
  return {
    ok: true,
    value: {
      id: "report-1",
      title: "G1a engineer report",
      doc_type: "report",
      scope: "s-1",
      owner_role: "engineer",
      version,
      versions,
      html: `<p data-v="${version}">report body v${version}</p>`,
      signoff_criterion: null,
    },
  };
}

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <RulingDrawer signoff={signoff} kOfN={{ k: 1, n: 3 }} onClose={vi.fn()} onRuled={vi.fn()} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("RulingDrawer", () => {
  it("freezes the opened version: fetches ?version=1 and shows that body + the criterion", async () => {
    let requestedUrl = "";
    server.use(
      http.get("/v1/docs/:id/html", ({ request }) => {
        requestedUrl = request.url;
        return HttpResponse.json(docHtml(1, [1]));
      }),
    );
    mount();
    expect(screen.getByTestId("drawer-panel")).toBeInTheDocument();
    expect(screen.getByText("1 of 3 sign-offs")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("report body v1")).toBeInTheDocument());
    expect(new URL(requestedUrl).searchParams.get("version")).toBe("1");
    expect(screen.getByText(signoff.criterion.text)).toBeInTheDocument();
    expect(screen.getByTestId("approve")).toBeInTheDocument(); // ruling enabled (current version)
  });

  it("a newer version → banner, content NOT swapped, and ruling requires 'rule anyway'", async () => {
    server.use(http.get("/v1/docs/:id/html", () => HttpResponse.json(docHtml(1, [1, 2]))));
    mount();
    await waitFor(() => expect(screen.getByTestId("newer-version-banner")).toBeInTheDocument());
    // The reader still shows the frozen v1 body — never silently swapped to v2.
    expect(screen.getByText("report body v1")).toBeInTheDocument();
    // No verdict button until the owner explicitly accepts ruling on the older version.
    expect(screen.queryByTestId("approve")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Rule on v1 anyway"));
    expect(screen.getByTestId("approve")).toBeInTheDocument();
  });

  it("sends stale_ok=true when ruling on the older version after acknowledging", async () => {
    let body: Record<string, unknown> | null = null;
    server.use(
      http.get("/v1/docs/:id/html", () => HttpResponse.json(docHtml(1, [1, 2]))),
      http.post("/v1/me/verdict", async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ok: true, value: { criterion: {}, message: null } });
      }),
    );
    mount();
    await waitFor(() => expect(screen.getByTestId("newer-version-banner")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Rule on v1 anyway"));
    fireEvent.click(screen.getByTestId("approve"));
    await waitFor(() => expect(body).not.toBeNull());
    expect(body).toMatchObject({ criterion_id: "c-1", verdict: "pass", evidence_version: 1, stale_ok: true });
  });
});

// Promise #19: the ruling body is a drop target — the composer's upload path; the artifact is
// staged with the note and posted with the verdict.
describe("RulingDrawer drop target (promise #19)", () => {
  it("drag-over paints the veil; a dropped file is uploaded against the ticket and staged with the note", async () => {
    vi.mocked(uploadArtifact).mockClear();
    let verdictBody: Record<string, unknown> | null = null;
    server.use(
      http.get("/v1/docs/:id/html", () => HttpResponse.json(docHtml(1, [1]))),
      // the multipart body is never read back here: request.text()/formData() hang under jsdom
      http.post("/v1/artifacts/upload", () => HttpResponse.json({ ok: true, value: { id: "art-rule01", form: "image" } })),
      http.post("/v1/me/verdict", async ({ request }) => {
        verdictBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ok: true, value: { criterion: {}, message: null } });
      }),
    );
    mount();
    const grid = screen.getByTestId("ruling-grid");
    fireEvent.dragOver(grid);
    expect(screen.getByTestId("drop-veil")).toBeInTheDocument();
    fireEvent.dragLeave(grid);
    expect(screen.queryByTestId("drop-veil")).not.toBeInTheDocument();

    fireEvent.drop(grid, { dataTransfer: { files: [new File(["x"], "proof.png", { type: "image/png" })] } });
    await waitFor(() => expect(vi.mocked(uploadArtifact)).toHaveBeenCalled());
    expect(await screen.findByTestId("staged-artifact")).toHaveTextContent("art-rule01");
    expect(vi.mocked(uploadArtifact).mock.calls[0]?.[1]).toBe("s-1");

    fireEvent.change(screen.getByTestId("note"), { target: { value: "see the screenshot" } });
    fireEvent.click(screen.getByTestId("approve"));
    await waitFor(() => expect(verdictBody).not.toBeNull());
    expect(verdictBody!.note).toBe("see the screenshot art-rule01");
  });

  it("a refused upload keeps the note and shows the reason", async () => {
    server.use(
      http.get("/v1/docs/:id/html", () => HttpResponse.json(docHtml(1, [1]))),
      http.post("/v1/artifacts/upload", () => HttpResponse.json({ ok: false, hint: "disallowed type" }, { status: 415 })),
    );
    mount();
    fireEvent.change(screen.getByTestId("note"), { target: { value: "kept" } });
    fireEvent.drop(screen.getByTestId("ruling-grid"), {
      dataTransfer: { files: [new File(["x"], "a.exe", { type: "application/x-msdownload" })] },
    });
    expect(await screen.findByRole("alert")).toHaveTextContent(/Upload failed/);
    expect(screen.getByTestId("note")).toHaveValue("kept");
    expect(screen.queryByTestId("staged-artifact")).not.toBeInTheDocument();
  });
});
