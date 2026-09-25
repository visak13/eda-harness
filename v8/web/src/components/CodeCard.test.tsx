import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Conversation } from "./Conversation";
import { codeHref } from "./CodeCard";
import type { CodeContext, MessageView } from "../api/types";

// epic-91fcd3b370 S4 (c-7e7a4d002c): a message with code_context renders a code card on the ticket
// page — path, lines, short sha, monospace snippet, an "Open in Code" deep link — and the snippet is
// literal text, never HTML.
const SHA = "0123456789abcdef0123456789abcdef01234567";
const HOSTILE = `<script>window.__pwned = 1</script>\n<img src=x onerror="window.__pwned = 2">`;

function cc(over: Partial<CodeContext> = {}): CodeContext {
  return { repo_root: "C:/Projects/Learning/eda-base3/v8", path: "src/edp8/board.py", line_start: 10, line_end: 20,
    commit: SHA, dirty: false, snippet: "def f():\n    return 1", snippet_sha: "x", ...over };
}

function mount(code_context: CodeContext | null) {
  const msg: MessageView = { id: "m-1", by: "owner", to: "engineer.s-1", kind: "question", text: "why this?",
    at: "2026-09-25T05:00:00Z", reply_to: null, code_context };
  const history = { messages: [msg], total: 1, listRef: { current: null }, more: false, loading: false, error: null, load: () => {} };
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <Conversation ticketId="s-1" history={history as never} order="newest" onToggleOrder={() => {}} onReply={() => {}}
          viewer="owner" composer={<textarea aria-label="Message" defaultValue="" />} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("CodeCard (S4)", () => {
  beforeEach(() => { localStorage.clear(); delete (window as { __pwned?: number }).__pwned; });

  it("shows path, lines, short sha and the snippet in monospace <pre><code>", () => {
    mount(cc());
    expect(screen.getByTestId("code-path")).toHaveTextContent("src/edp8/board.py");
    expect(screen.getByTestId("code-lines")).toHaveTextContent("L10–20");
    expect(screen.getByTestId("code-sha")).toHaveTextContent(/^0123456$/);
    const pre = screen.getByTestId("code-snippet");
    expect(pre.tagName).toBe("PRE");
    expect(pre.querySelector("code")?.textContent).toBe("def f():\n    return 1");
  });

  it("links Open in Code to the /code deep link with folder, file and line", () => {
    mount(cc());
    const a = screen.getByRole("link", { name: /Open in Code/ });
    const url = new URL(a.getAttribute("href")!, "http://x");
    expect(url.pathname).toBe("/code");
    expect(url.searchParams.get("folder")).toBe("C:/Projects/Learning/eda-base3/v8");
    expect(url.searchParams.get("file")).toBe("src/edp8/board.py");
    expect(url.searchParams.get("line")).toBe("10-20"); // S3: a range anchor carries its range
  });

  it("encodes awkward folder/file names so they survive the round-trip", () => {
    const href = codeHref(cc({ repo_root: "C:/My Repo & co", path: "a b/c#d?.py", line_start: 3 }));
    const url = new URL(href, "http://x");
    expect(url.searchParams.get("folder")).toBe("C:/My Repo & co");
    expect(url.searchParams.get("file")).toBe("a b/c#d?.py");
    expect(url.searchParams.get("line")).toBe("3-20");
  });

  it("renders a <script> / <img onerror> snippet as literal text — no DOM injection", () => {
    const { container } = mount(cc({ snippet: HOSTILE }));
    const card = screen.getByTestId("code-card");
    expect(card.querySelector("script")).toBeNull();
    expect(card.querySelector("img")).toBeNull();
    expect(container.querySelector("img[onerror]")).toBeNull();
    expect(screen.getByTestId("code-snippet").textContent).toBe(HOSTILE);
    expect((window as { __pwned?: number }).__pwned).toBeUndefined();
  });

  it("shows 'no git' for a non-git folder and a dirty flag only with a commit", () => {
    mount(cc({ commit: null, dirty: true }));
    expect(screen.getByTestId("code-sha")).toHaveTextContent("no git");
    expect(screen.queryByText("dirty")).toBeNull();
  });

  it("renders no card for a message without code_context", () => {
    mount(null);
    expect(screen.queryByTestId("code-card")).toBeNull();
  });
});
