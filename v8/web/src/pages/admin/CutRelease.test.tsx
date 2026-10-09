import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../../test/setup";
import { CutRelease } from "./CutRelease";

// S10 Cut release: owner-only (the board says can_cut), a dry run by default, a confirm dialog that states
// repo, tag and whether it publishes publicly; Cancel sends nothing, Confirm sends the exact body.

const ok = (value: unknown, hint = "") => HttpResponse.json({ ok: true, value, hint });
const VIEW = { can_cut: true, reason: null, repo: "acme/fork", default_ref: "main", token_set: true, last: null };

function mount(view: unknown = VIEW) {
  const bodies: unknown[] = [];
  server.use(
    http.get("/v1/admin/release", () => ok(view)),
    http.get("/v1/admin/updates", () => ok({ current: "0.10.1", latest: "0.10.1", available: false, url: null, checked: true, apply_refusal: null, last: { request: null, result: null, log: [] } })),
    http.post("/v1/admin/release/cut", async ({ request }) => {
      bodies.push(await request.json());
      return HttpResponse.json({ ok: true, value: { tag: "v0.10.0", runs_url: "https://github.com/acme/fork/actions/workflows/release.yml" }, hint: "dry run" }, { status: 202 });
    }),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={qc}><CutRelease /></QueryClientProvider>);
  return bodies;
}

const type = async (v: string) => fireEvent.change(await screen.findByTestId("cut-version"), { target: { value: v } });

describe("Cut release", () => {
  it("is disabled, with the board's reason, when the caller cannot cut", async () => {
    mount({ ...VIEW, can_cut: false, reason: "only the owner (owner) can cut a release" });
    expect(await screen.findByTestId("cut-release-refusal")).toHaveTextContent("Only the owner"); // S12-ui2: a sentence
    expect(screen.getByTestId("cut-version")).toBeDisabled();
    expect(screen.getByTestId("cut-release-open")).toBeDisabled();
  });

  it("S12-ui2 (m2): Version prefills the running version, and the no-token reason starts upper-case", async () => {
    mount({ ...VIEW, can_cut: false, token_set: false, reason: "no release token is set: add one under Settings → Updates → Release token" });
    expect((await screen.findByTestId("cut-release-refusal")).textContent).toBe("No release token is set: add one under Settings → Updates → Release token");
    await waitFor(() => expect(screen.getByTestId("cut-version")).toHaveValue("0.10.1"));
  });

  it("S12-ui2 (m2): the owner's own typing replaces the prefilled version", async () => {
    mount();
    await waitFor(() => expect(screen.getByTestId("cut-version")).toHaveValue("0.10.1"));
    await type("0.11.0");
    expect(screen.getByTestId("cut-version")).toHaveValue("0.11.0");
  });

  it("starts as a dry run with publish off and disabled, and needs a valid version", async () => {
    mount();
    await type("latest");
    expect(screen.getByTestId("cut-dry-run")).toBeChecked();
    expect(screen.getByTestId("cut-publish")).not.toBeChecked();
    expect(screen.getByTestId("cut-publish")).toBeDisabled();
    expect(screen.getByTestId("cut-release-open")).toBeDisabled();
    await type("0.10.0");
    expect(screen.getByTestId("cut-release-open")).not.toBeDisabled();
  });

  it("Cancel in the confirm dialog sends nothing", async () => {
    const bodies = mount();
    await type("0.10.0");
    fireEvent.click(screen.getByTestId("cut-release-open"));
    expect(await screen.findByTestId("cut-confirm-text")).toHaveTextContent("acme/fork · tag v0.10.0 · branch main");
    fireEvent.click(screen.getByTestId("cut-cancel"));
    await waitFor(() => expect(screen.queryByTestId("cut-confirm")).not.toBeInTheDocument());
    expect(bodies).toEqual([]);
  });

  it("Confirm sends the exact dry-run body and shows where to follow the run", async () => {
    const bodies = mount();
    await type("v0.10.0");
    fireEvent.click(screen.getByTestId("cut-release-open"));
    expect(await screen.findByTestId("cut-confirm")).toHaveTextContent("Nothing is tagged, built or published");
    fireEvent.click(screen.getByTestId("cut-confirm-go"));
    await waitFor(() => expect(bodies).toEqual([{ version: "0.10.0", dry_run: true, publish: false }]));
    expect(await screen.findByTestId("cut-release-done")).toHaveTextContent("actions/workflows/release.yml");
  });

  it("a real publish says so in the dialog and sends dry_run false, publish true", async () => {
    const bodies = mount();
    await type("0.10.0");
    fireEvent.click(screen.getByTestId("cut-dry-run"));
    fireEvent.click(screen.getByTestId("cut-publish"));
    fireEvent.click(screen.getByTestId("cut-release-open"));
    expect(await screen.findByTestId("cut-confirm")).toHaveTextContent("PUBLISHED publicly");
    fireEvent.click(screen.getByTestId("cut-confirm-go"));
    await waitFor(() => expect(bodies).toEqual([{ version: "0.10.0", dry_run: false, publish: true }]));
  });

  it("turning dry run back on clears publish", async () => {
    const bodies = mount();
    await type("0.10.0");
    fireEvent.click(screen.getByTestId("cut-dry-run"));
    fireEvent.click(screen.getByTestId("cut-publish"));
    fireEvent.click(screen.getByTestId("cut-dry-run"));
    expect(screen.getByTestId("cut-publish")).not.toBeChecked();
    fireEvent.click(screen.getByTestId("cut-release-open"));
    fireEvent.click(await screen.findByTestId("cut-confirm-go"));
    await waitFor(() => expect(bodies).toEqual([{ version: "0.10.0", dry_run: true, publish: false }]));
  });

  it("shows the board's refusal when GitHub says no", async () => {
    mount();
    server.use(http.post("/v1/admin/release/cut", () => HttpResponse.json({ ok: false, error: { code: "http", message: "GitHub refused the dispatch (422)" }, hint: "" }, { status: 502 })));
    await type("0.10.0");
    fireEvent.click(screen.getByTestId("cut-release-open"));
    fireEvent.click(await screen.findByTestId("cut-confirm-go"));
    expect(await screen.findByTestId("cut-release-error")).toHaveTextContent("GitHub refused");
  });
});
