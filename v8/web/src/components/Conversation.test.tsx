import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Conversation } from "./Conversation";
import type { MessageView } from "../api/types";

// S17 c-7a3c3ec439 / c-b1f32f8b33: the message box collapses Word-style WITHOUT unmounting the
// composer (draft kept), remembered per viewer; a message with board `html` renders as Markdown.
const msg: MessageView = { id: "m-1", by: "arch", to: null, kind: "note", text: "**hi**", html: "<p><strong>hi</strong></p>", at: "2026-09-23T05:00:00Z", reply_to: null };
function mount(m: MessageView = msg) {
  const history = { messages: [m], total: 1, listRef: { current: null }, more: false, loading: false, error: null, load: () => {} };
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <Conversation ticketId="epic-1" history={history as never} order="newest" onToggleOrder={() => {}} onReply={() => {}}
          viewer="owner" composer={<textarea aria-label="Message" defaultValue="" />} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Conversation (S17)", () => {
  beforeEach(() => localStorage.clear());

  it("renders the board's Markdown html for a message", () => {
    mount();
    expect(screen.getByTestId("message-md").querySelector("strong")?.textContent).toBe("hi");
  });

  it("collapses the message box, keeps the draft mounted, and remembers it per viewer", () => {
    mount();
    const box = screen.getByRole("textbox", { name: "Message" });
    fireEvent.change(box, { target: { value: "half-written draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Collapse message box" }));
    expect(screen.queryByRole("textbox", { name: "Message" })).toBeNull(); // hidden from the a11y tree
    expect(box.isConnected).toBe(true);
    expect(screen.getByTestId("composer-collapsed-bar")).toBeInTheDocument();
    expect(localStorage.getItem("edp8.ui.owner.composer-collapsed")).toBe("1");
    cleanup();
    mount();
    expect(screen.getByRole("button", { name: "Expand message box" })).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(screen.getByTestId("composer-collapsed-bar"));
    expect(screen.getByRole("textbox", { name: "Message" })).toBeVisible();
  });

  it("t-8e94ffd3ad: a has_content=false attachment is labelled with its uri, never fetched or offered as Open", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    mount({ ...msg, id: "m-2", html: undefined, text: "see art-b35d8e652d", artifacts: ["art-b35d8e652d"],
      attachments: [{ id: "art-b35d8e652d", form: "image", filename: "", content_type: "image/png", note: "S17 shot",
        has_content: false, uri: "workspace:v8/web/shots/s17.png" }] });
    const card = screen.getByTestId("attachment-card");
    expect(card).toHaveTextContent("not uploaded — workspace:v8/web/shots/s17.png");
    expect(screen.queryByRole("button", { name: /View image|Open file/ })).toBeNull();
    fireEvent.click(screen.getByTestId("copy-path"));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("workspace:v8/web/shots/s17.png"));
    expect(fetchSpy.mock.calls.some(([u]) => String(u).includes("/content"))).toBe(false);
    fetchSpy.mockRestore();
  });

  it("an uploaded attachment (has_content true) keeps its View/Open action", () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 404 }));
    mount({ ...msg, id: "m-3", html: undefined, text: "pdf", artifacts: ["art-1"],
      attachments: [{ id: "art-1", form: "file", filename: "r.pdf", content_type: "application/pdf", note: "", has_content: true, uri: "/v1/artifacts/art-1/content" }] });
    expect(screen.getByRole("button", { name: /Open file/ })).toBeInTheDocument();
    expect(screen.queryByTestId("not-uploaded")).toBeNull();
    vi.restoreAllMocks();
  });

  it("S-UI c-cb386d6be1: minimized, the message box is one bar — the expand control IS the bar", () => {
    localStorage.setItem("edp8.ui.owner.composer-collapsed", "1");
    mount();
    const bar = screen.getByTestId("composer-collapsed-bar");
    expect(screen.getByRole("button", { name: "Expand message box" })).toBe(bar);
    expect(screen.queryByTestId("composer-collapse")).toBeNull();
    expect(screen.getByTestId("conversation-composer").querySelectorAll("button:not([hidden] *)")).toHaveLength(1);
  });
});
