import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { server } from "../test/setup";
import { http, okJson, renderRoute } from "../pages/testUtils";
import { Conversation } from "./Conversation";
import { TopicPage } from "../pages/TopicPage";
import convo from "./Conversation.module.css";
import topics from "../pages/Topics.module.css";
import type { MessageView, TopicPage as TopicPageData } from "../api/types";

// t-6129a95a3d (owner m-3818ff2a47): the epic, ticket and topic chats carry a very light 1px frame from the
// theme's --line token, so it is clear where the wheel scrolls the thread. jsdom applies no CSS, so the rule is
// read from the module source and the render checks each view puts the framed class on its thread list.
const src = (p: string) => readFileSync(new URL(p, import.meta.url), "utf-8");
const rule = (css: string, sel: string) => css.match(new RegExp(`(^|\\n)\\${sel}\\s*\\{([^}]*)\\}`))?.[2] ?? "";

describe("chat panes are framed (t-6129a95a3d)", () => {
  it("the thread scroll container has a 1px --line border and keeps its focus ring", () => {
    const css = src("./Conversation.module.css");
    const messages = rule(css, ".messages");
    expect(messages).toMatch(/border:\s*1px solid var\(--line\)/);
    expect(messages).toMatch(/overflow-y:\s*auto/);
    expect(rule(css, ".messages:focus-visible")).toMatch(/outline:\s*2px solid var\(--accentink\)/);
    expect(rule(src("../pages/Topics.module.css"), ".threadList")).toMatch(/border:\s*1px solid var\(--line\)/);
  });

  it("epic and ticket pages render their thread through Conversation's framed list", () => {
    for (const page of ["../pages/Epic.tsx", "../pages/Ticket.tsx"]) expect(src(page)).toMatch(/<Conversation\b/);
    const m: MessageView = { id: "m-1", by: "arch", to: null, kind: "note", text: "hi", at: "2026-09-23T05:00:00Z", reply_to: null };
    const history = { messages: [m], total: 1, listRef: { current: null }, more: false, loading: false, error: null, load: () => {} };
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <Conversation ticketId="epic-1" history={history as never} order="newest" onToggleOrder={() => {}} onReply={() => {}}
            viewer="owner" composer={<textarea aria-label="Message" defaultValue="" />} />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByTestId("thread").className).toContain(convo.messages);
  });

  it("the topic chat's thread list is framed", async () => {
    const page = {
      topic: { id: "topic-1", title: "T", tags: [], status: "open", created_at: "2026-09-24T10:00:00Z", created_by: "owner",
        seat: { participant: "sme.topic-1", state: "live" }, docs: 0, experts: 0, messages: 1, description: "" },
      seed_url: null, tags_set_by: null, docs: [], experts: [], seat: { participant: "sme.topic-1", state: "live" }, fetches: [],
      viewer: { id: "owner", role: "owner" },
      thread: [{ id: "m-1", created_at: "2026-09-24T10:06:00Z", created_by: "owner", to: null, kind: "question", text: "q",
        reply_to: null, from: { id: "owner", role: "owner", type: "human" } }],
    } as unknown as TopicPageData;
    server.use(http.get("/v1/topics/:id", () => okJson(page)));
    renderRoute("/library/topics/topic-1", "/library/topics/:id", <TopicPage />);
    const list = await screen.findByTestId("topic-thread-list");
    expect(list.className).toContain(topics.threadList);
  });
});
