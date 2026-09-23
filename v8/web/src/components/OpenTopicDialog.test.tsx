import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import { OpenTopicDialog, parseHandles } from "./OpenTopicDialog";

// t-f5bf848f0f (owner m-30d50df723): the Open-topic dialog mirrors NewEpicDialog.test.tsx — the POST body
// is asserted (words verbatim, tags, seed, the sme model + effort from the catalog), then the experts added
// one by one with their one-time links shown, a failed expert retried without opening the topic twice,
// busy/dismissal guarded, and a11y parity (labelled dialog, title focused, described inputs).
function mount(onClose = () => {}, onOpened: (id: string) => void = () => {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/library/topics"]}>
        <OpenTopicDialog open onClose={onClose} onOpened={onOpened} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const opened = (id: string) => HttpResponse.json({ ok: true, value: { topic: { id }, seat: { participant: `sme.${id}`, state: "queued" } }, hint: "queued" });

describe("OpenTopicDialog (t-f5bf848f0f)", () => {
  it("opens the topic with the words verbatim, tags, seed and the sme model + effort, then lands on the topic", async () => {
    let body: Record<string, unknown> | null = null;
    server.use(http.post("/v1/topics", async ({ request }) => { body = (await request.json()) as Record<string, unknown>; return opened("topic-9"); }));
    const onOpened = vi.fn();
    const onClose = vi.fn();
    mount(onClose, onOpened);
    const dialog = await screen.findByRole("dialog", { name: "Open topic" });
    expect(dialog).toBeInTheDocument();
    expect(screen.getByTestId("topic-open-title")).toHaveFocus();
    expect(screen.getByTestId("topic-open-create")).toBeDisabled();
    const raw = "  Keep our pytest craft current.\nFixtures, markers, CI.  ";
    fireEvent.change(screen.getByTestId("topic-open-title"), { target: { value: "  Python testing  " } });
    expect(screen.getByText("18/80 — required")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("topic-open-words"), { target: { value: raw } });
    fireEvent.change(screen.getByTestId("topic-open-tags"), { target: { value: " Python, testing" } });
    expect(screen.getByTestId("topic-open-tags-help")).toHaveTextContent("Tagged python, testing; the sme adds its own");
    fireEvent.change(screen.getByTestId("topic-open-seed"), { target: { value: "https://docs.pytest.org/en/stable/" } });
    // the sme row: the catalog's sme models, prefilled with its default; effort beside it
    const model = await screen.findByTestId("topic-open-model-sme") as HTMLSelectElement;
    expect(Array.from(model.options).map((o) => o.value)).toEqual(["claude-opus-5-5", "gpt-6-sol"]);
    expect(model.value).toBe("claude-opus-5-5");
    const effort = screen.getByTestId("topic-open-effort-sme") as HTMLSelectElement;
    expect(effort.value).toBe("medium");
    expect(Array.from(effort.options).find((o) => o.value === "high")!.disabled).toBe(true); // Claude: medium max
    expect(screen.getByTestId("topic-open-row-sme").querySelector("[data-role-icon='sme']")).not.toBeNull();
    fireEvent.change(model, { target: { value: "gpt-6-sol" } });
    fireEvent.change(screen.getByTestId("topic-open-effort-sme"), { target: { value: "high" } });
    expect(screen.getByTestId("topic-open-preview")).toHaveTextContent(/verbatim.*gpt-6-sol at effort high.*No expert is added now/);
    expect(screen.getByTestId("topic-open-create")).toHaveTextContent("Open the topic");
    fireEvent.click(screen.getByTestId("topic-open-create"));
    await waitFor(() => expect(onOpened).toHaveBeenCalledWith("topic-9"));
    expect(body).toEqual({
      title: "Python testing", words: raw, tags: ["python", "testing"],
      seed_url: "https://docs.pytest.org/en/stable/", model: "gpt-6-sol", effort: "high",
    });
    expect(onClose).toHaveBeenCalled();
  });

  it("adds each expert after the topic opens and shows every one-time link, instead of navigating away", async () => {
    const experts: string[] = [];
    server.use(
      http.post("/v1/topics", () => opened("topic-e")),
      http.post("/v1/topics/:id/experts", async ({ request, params }) => {
        const h = ((await request.json()) as { handle: string }).handle;
        experts.push(`${params.id}:${h}`);
        return HttpResponse.json({ ok: true, value: { expert: { id: h, handle: h }, token: `tok-${h}`,
          link: `/ui/library/topics/topic-e?as=${h}&token=tok-${h}` } });
      }),
    );
    const onOpened = vi.fn();
    mount(undefined, onOpened);
    await screen.findByRole("dialog", { name: "Open topic" });
    fireEvent.change(screen.getByTestId("topic-open-title"), { target: { value: "Rust async" } });
    fireEvent.change(screen.getByTestId("topic-open-experts"), { target: { value: "@Priya, dana priya" } });
    expect(screen.getByTestId("topic-open-preview")).toHaveTextContent("Then adds 2 experts (priya, dana)");
    expect(screen.getByTestId("topic-open-create")).toHaveTextContent("Open the topic and add experts");
    fireEvent.click(screen.getByTestId("topic-open-create"));
    const links = await screen.findAllByTestId("topic-open-link");
    expect(experts).toEqual(["topic-e:priya", "topic-e:dana"]);
    expect(links.map((l) => l.textContent)).toEqual([
      expect.stringContaining("/ui/library/topics/topic-e?as=priya&token=tok-priya"),
      expect.stringContaining("/ui/library/topics/topic-e?as=dana&token=tok-dana")]);
    expect(screen.getByTestId("topic-open-done")).toHaveTextContent("not shown again");
    expect(onOpened).not.toHaveBeenCalled(); // the links show once: the owner leaves when ready
    expect(screen.getByTestId("topic-open-title")).toBeDisabled();
    expect(screen.getByTestId("topic-open-create")).toHaveTextContent("Go to the topic");
    fireEvent.click(screen.getByTestId("topic-open-create"));
    await waitFor(() => expect(onOpened).toHaveBeenCalledWith("topic-e"));
  });

  it("retries a failed expert without opening the topic twice", async () => {
    let opens = 0, tries = 0;
    server.use(
      http.post("/v1/topics", () => { opens++; return opened("topic-r"); }),
      http.post("/v1/topics/:id/experts", async ({ request }) => {
        const h = ((await request.json()) as { handle: string }).handle;
        tries++;
        if (h === "dana" && tries <= 2) return HttpResponse.json({ ok: false, hint: "no tokens.json on this board" }, { status: 400 });
        return HttpResponse.json({ ok: true, value: { expert: { id: h, handle: h }, token: "t", link: `/ui/x?as=${h}` } });
      }),
    );
    mount();
    fireEvent.change(screen.getByTestId("topic-open-title"), { target: { value: "Retry" } });
    fireEvent.change(screen.getByTestId("topic-open-experts"), { target: { value: "priya, dana" } });
    fireEvent.click(screen.getByTestId("topic-open-create"));
    expect(await screen.findByTestId("topic-open-experts-failed")).toHaveTextContent("dana: no tokens.json on this board");
    expect(screen.getAllByTestId("topic-open-link")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Retry experts" })).not.toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Retry experts" }));
    await waitFor(() => expect(screen.getAllByTestId("topic-open-link")).toHaveLength(2));
    expect(screen.queryByTestId("topic-open-experts-failed")).toBeNull();
    expect(opens).toBe(1);
    expect(tries).toBe(3); // priya once, dana twice — priya is never re-added
  });

  it("refuses bad expert handles and a non-https seed before any request", async () => {
    let posts = 0;
    server.use(http.post("/v1/topics", () => { posts++; return opened("x"); }));
    mount();
    fireEvent.change(screen.getByTestId("topic-open-title"), { target: { value: "T" } });
    fireEvent.change(screen.getByTestId("topic-open-experts"), { target: { value: "owner, a" } });
    expect(screen.getByTestId("topic-open-experts-invalid")).toHaveTextContent("Not a handle: owner, a");
    expect(screen.getByTestId("topic-open-experts")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByTestId("topic-open-create")).toBeDisabled();
    fireEvent.change(screen.getByTestId("topic-open-experts"), { target: { value: "priya" } });
    fireEvent.change(screen.getByTestId("topic-open-seed"), { target: { value: "http://tokio.rs" } });
    expect(screen.getByRole("alert")).toHaveTextContent("must start with https://");
    expect(screen.getByTestId("topic-open-create")).toBeDisabled();
    fireEvent.submit(screen.getByTestId("topic-open-dialog"));
    expect(posts).toBe(0);
  });

  it("blocks duplicate pending submits and dismissal, then keeps a failed draft", async () => {
    let finish!: () => void;
    const wait = new Promise<void>((resolve) => { finish = resolve; });
    let posts = 0;
    server.use(http.post("/v1/topics", async () => { posts++; await wait; return HttpResponse.json({ ok: false, hint: "Open failed" }, { status: 503 }); }));
    const close = vi.fn();
    mount(close);
    fireEvent.change(screen.getByTestId("topic-open-title"), { target: { value: "Title" } });
    fireEvent.change(screen.getByTestId("topic-open-words"), { target: { value: "  raw purpose  " } });
    fireEvent.submit(screen.getByTestId("topic-open-dialog"));
    fireEvent.submit(screen.getByTestId("topic-open-dialog"));
    await waitFor(() => expect(screen.getByTestId("topic-open-create")).toHaveTextContent("Opening…"));
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.mouseDown(screen.getByTestId("topic-open-scrim"));
    await waitFor(() => expect(posts).toBe(1));
    expect(close).not.toHaveBeenCalled();
    finish();
    expect(await screen.findByTestId("topic-open-error")).toHaveTextContent("Open failed");
    expect(screen.getByTestId("topic-open-title")).toHaveValue("Title");
    expect(screen.getByTestId("topic-open-words")).toHaveValue("  raw purpose  ");
  });

  it("when the catalog cannot load, says so and opens on the sme default (no model sent)", async () => {
    let body: Record<string, unknown> | null = null;
    server.use(
      http.get("/v1/models", () => HttpResponse.json({ ok: false, hint: "no catalog" }, { status: 503 })),
      http.post("/v1/topics", async ({ request }) => { body = (await request.json()) as Record<string, unknown>; return opened("topic-d"); }),
    );
    mount();
    expect(await screen.findByTestId("topic-open-models-error")).toHaveTextContent("runs on its role's default");
    fireEvent.change(screen.getByTestId("topic-open-title"), { target: { value: "Default" } });
    fireEvent.click(screen.getByTestId("topic-open-create"));
    await waitFor(() => expect(body).not.toBeNull());
    expect(body).toMatchObject({ model: null, effort: null, words: null });
  });

  it("parses expert handles: @ dropped, lower-cased, comma or space separated, deduped", () => {
    expect(parseHandles(" @Priya, dana  priya,,Lee ")).toEqual(["priya", "dana", "lee"]);
  });
});
