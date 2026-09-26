import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import { RequestAccess } from "./RequestAccess";
import { Conversation } from "./Conversation";
import { TeammatesTab } from "../pages/admin/Teammates";
import type { MessageView } from "../api/types";

// t-882e4d2eeb: Request access on the sign-in page (c-c0bdff80eb), Admin → Teammates Requests + Remove and
// retired people greyed in history (c-0785f1b2b1). Pickers drop retired people server-side (/v1/me/people,
// /v1/seats people: tests/test_admin_access.py); here the SPA side of the same rule.

const ok = (value: unknown, hint = "") => HttpResponse.json({ ok: true, value, hint });

function wrap(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><MemoryRouter>{node}</MemoryRouter></QueryClientProvider>);
}

beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
});

describe("Request access (sign-in page)", () => {
  it("is off with the board's reason when Remote access is off", async () => {
    wrap(<RequestAccess />);
    expect(await screen.findByTestId("access-off")).toHaveTextContent("Remote access is off");
    expect(screen.queryByTestId("access-open")).toBeNull();
  });

  it("asks, waits, and signs the tab in once the admin approves: the code never enters a URL", async () => {
    const claims: string[] = [];
    const urls: string[] = [];
    let polls = 0;
    server.use(
      http.get("/v1/access-requests/available", () => ok({ enabled: true, reason: null, roles: ["owner", "engineer"] })),
      http.post("/v1/access-requests", async ({ request }) => {
        urls.push(request.url);
        const body = (await request.json()) as Record<string, string>;
        expect(body).toEqual({ name: "Dana Lee", role_wanted: "owner", note: "design review" });
        return ok({ id: "acc-1", claim_code: "c0de-xyz", poll_s: 2 });
      }),
      http.post("/v1/access-requests/claim", async ({ request }) => {
        urls.push(request.url);
        claims.push(((await request.json()) as { code: string }).code);
        polls += 1;
        return polls === 1 ? ok({ status: "pending", poll_s: 2 })
          : ok({ status: "approved", handle: "dana-lee", token: "dana-token", board_url: "http://b" });
      }),
    );
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, href: "http://localhost/ui/", assign });
    try {
      wrap(<RequestAccess />);
      fireEvent.click(await screen.findByTestId("access-open"));
      fireEvent.change(screen.getByTestId("access-name"), { target: { value: "Dana Lee" } });
      fireEvent.change(screen.getByTestId("access-note"), { target: { value: "design review" } });
      fireEvent.click(screen.getByTestId("access-submit"));
      expect(await screen.findByTestId("access-waiting")).toBeInTheDocument();
      await waitFor(() => expect(assign).toHaveBeenCalledTimes(1), { timeout: 5000 });
    } finally {
      vi.unstubAllGlobals();
    }
    expect(claims).toEqual(["c0de-xyz", "c0de-xyz"]);
    expect(urls.every((u) => !u.includes("c0de") && !u.includes("dana-token"))).toBe(true);
    expect(String(assign.mock.calls[0][0])).not.toContain("dana-token");
    expect(String(assign.mock.calls[0][0])).toContain("as=dana-lee");
    expect(sessionStorage.getItem("edp8.token")).toBe("dana-token");
    expect(sessionStorage.getItem("edp8.access.claim")).toBeNull(); // the claim is spent
  }, 10_000);

  it("says so when the admin declines", async () => {
    sessionStorage.setItem("edp8.access.claim", "c0de-2"); // a reload while waiting resumes the poll
    server.use(http.post("/v1/access-requests/claim", () => ok({ status: "denied" })));
    wrap(<RequestAccess />);
    expect(await screen.findByTestId("access-done")).toHaveTextContent("declined");
    expect(sessionStorage.getItem("edp8.access.claim")).toBeNull();
  });
});

const TEAM = [
  { id: "owner", handle: "owner", role: "owner", admin: true, init_human: true, has_token: true, last_seen: null, invite_expires: null, retired: false },
  { id: "carol", handle: "carol", role: "owner", admin: false, init_human: false, has_token: true, last_seen: null, invite_expires: null, retired: false },
  { id: "bob", handle: "bob", role: "owner", admin: false, init_human: false, has_token: false, last_seen: null, invite_expires: null, retired: true },
];
const TAILNET = { public_mode: true, auth_keys: { configured: false }, rows: [] };

describe("Admin → Teammates: requests and Remove", () => {
  it("lists a pending request under its own id and approves it", async () => {
    const approved: string[] = [];
    server.use(
      http.get("/v1/admin/teammates", () => ok(TEAM)),
      http.get("/v1/admin/tailnet", () => ok(TAILNET)),
      http.get("/v1/admin/tokens/agents", () => ok([])),
      http.get("/v1/admin/access-requests", () => ok([
        { id: "acc-1", created_at: "2026-09-27T01:00:00Z", name: "Dana Lee", role_wanted: "owner", note: "design", status: "pending",
          decided_by: null, decided_at: null, handle: null }])),
      http.post("/v1/admin/access-requests/:id/approve", async ({ params, request }) => {
        approved.push(`${params.id}:${JSON.stringify(await request.json())}`);
        return ok({ id: params.id, status: "approved", handle: "dana" });
      }),
    );
    const { container } = wrap(<TeammatesTab />);
    const row = await screen.findByTestId("access-request-acc-1");
    expect(container.querySelector("#acc-1")).toBe(row); // the attention trail's target
    expect(row).toHaveTextContent("Dana Lee asks for access as member");
    fireEvent.change(within(row).getByTestId("access-request-acc-1-handle"), { target: { value: "dana" } });
    fireEvent.click(within(row).getByTestId("access-request-acc-1-approve"));
    await waitFor(() => expect(approved).toEqual(['acc-1:{"handle":"dana"}']));
  });

  it("hides removed teammates until asked, and Remove needs a confirm step", async () => {
    const removed: string[] = [];
    server.use(
      http.get("/v1/admin/teammates", () => ok(TEAM)),
      http.get("/v1/admin/tailnet", () => ok(TAILNET)),
      http.get("/v1/admin/tokens/agents", () => ok([])),
      http.post("/v1/admin/teammates/:handle/remove", ({ params }) => {
        removed.push(String(params.handle));
        return ok({ handle: params.handle, removed: true }, "their token is refused and they no longer appear in pickers");
      }),
    );
    wrap(<TeammatesTab />);
    await screen.findByTestId("teammate-carol");
    expect(screen.queryByTestId("teammate-bob")).toBeNull();
    fireEvent.click(screen.getByTestId("teammates-show-removed"));
    expect(screen.getByTestId("teammate-bob")).toHaveTextContent("removed");
    expect(screen.queryByTestId("teammate-bob-remove")).toBeNull();
    expect(screen.queryByTestId("teammate-owner-remove")).toBeNull(); // the init human is never removable

    fireEvent.click(screen.getByTestId("teammate-carol-remove"));
    expect(removed).toEqual([]); // nothing happens before the confirm
    const confirm = screen.getByTestId("teammate-carol-remove-confirm");
    fireEvent.click(within(confirm).getByTestId("teammate-carol-remove-no"));
    expect(screen.queryByTestId("teammate-carol-remove-confirm")).toBeNull();
    fireEvent.click(screen.getByTestId("teammate-carol-remove"));
    fireEvent.click(screen.getByTestId("teammate-carol-remove-yes"));
    await waitFor(() => expect(removed).toEqual(["carol"]));
    expect(await screen.findByTestId("teammate-action-done")).toHaveTextContent("no longer appear in pickers");
  });
});

describe("History keeps a retired person's name, greyed", () => {
  it("greys the author a /v1/seats `retired` row names, and only them", async () => {
    server.use(http.get("/v1/seats", () => ok({ seats: [], people: [{ id: "carol", handle: "carol", role: "owner" }], retired: [{ id: "bob", handle: "bob" }] })));
    const msgs: MessageView[] = [
      { id: "m-1", by: "bob", to: null, kind: "note", text: "old note", at: "2026-09-20T05:00:00Z", reply_to: null },
      { id: "m-2", by: "carol", to: null, kind: "note", text: "new note", at: "2026-09-21T05:00:00Z", reply_to: null },
    ];
    const historyProp = { messages: msgs, total: 2, listRef: { current: null }, more: false, loading: false, error: null, load: () => {} };
    wrap(<Conversation ticketId="epic-1" history={historyProp as never} order="oldest" onToggleOrder={() => {}} onReply={() => {}}
      viewer="owner" composer={<textarea aria-label="Message" />} />);
    const greyed = await screen.findByTestId("retired-author");
    expect(greyed).toHaveTextContent("bob");
    expect(greyed).toHaveAttribute("title", "No longer on this board");
    expect(screen.getAllByTestId("retired-author")).toHaveLength(1);
    expect(screen.getByText("carol").tagName).toBe("STRONG");
  });
});
