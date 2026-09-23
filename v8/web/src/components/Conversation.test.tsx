import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Conversation } from "./Conversation";
import type { MessageView } from "../api/types";

// S17 c-7a3c3ec439 / c-b1f32f8b33: the message box collapses Word-style WITHOUT unmounting the
// composer (draft kept), remembered per viewer; a message with board `html` renders as Markdown.
const msg: MessageView = { id: "m-1", by: "arch", to: null, kind: "note", text: "**hi**", html: "<p><strong>hi</strong></p>", at: "2026-09-23T05:00:00Z", reply_to: null };
function mount() {
  const history = { messages: [msg], total: 1, listRef: { current: null }, more: false, loading: false, error: null, load: () => {} };
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
});
