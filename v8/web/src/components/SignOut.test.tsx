import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";

// t-882e4d2eeb c-7942213d3f: Sign out in the account menu clears the stored token (and asks the board to
// expire its cookie); the next API call is 401 and the app shows the sign-in page. identity.ts reads its
// session once at module load, so each case loads a fresh copy of the modules with a token in storage.

async function freshIdentity() {
  vi.resetModules();
  sessionStorage.clear();
  sessionStorage.setItem("edp8.as", "alice");
  sessionStorage.setItem("edp8.token", "alice-secret");
  sessionStorage.setItem("edp8.draft.t-1", "half a message");
  history.replaceState({}, "", "/ui/");
  const identity = await import("../auth/identity");
  await identity.sessionReady;
  return identity;
}

async function freshModules() {
  const identity = await freshIdentity();
  const shell = await import("./AppShell");
  const theme = await import("../theme/ThemeProvider"); // same module registry as the shell's context
  return { identity, AppShell: shell.AppShell, ThemeProvider: theme.ThemeProvider };
}

// The board: whoami answers only a request that carries alice's token.
function board(seen: { signout: number; whoami: Array<Record<string, string>> }) {
  server.use(
    http.post("/v1/signout", () => {
      seen.signout += 1;
      return new HttpResponse(JSON.stringify({ ok: true, value: { signed_out: true } }), {
        headers: { "content-type": "application/json", "set-cookie": "edp-code-guard=; Max-Age=0; Path=/" },
      });
    }),
    http.get("/v1/whoami", ({ request }) => {
      const h = { participant: request.headers.get("X-Participant") ?? "", token: request.headers.get("X-Token") ?? "" };
      seen.whoami.push(h);
      return h.token === "alice-secret"
        ? HttpResponse.json({ ok: true, value: { participant: { id: "alice", handle: "alice", role: "owner" }, tickets: [] } })
        : HttpResponse.json({ ok: false, error: "X-Participant header missing" }, { status: 401 });
    }),
    http.get("/v1/me/avatar", () => HttpResponse.json({ ok: true, value: { catalog: [] } })),
    http.get("/v1/describe/message", () => HttpResponse.json({ ok: true, value: {} })),
  );
}

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
  localStorage.clear();
});

describe("Sign out (t-882e4d2eeb)", () => {
  it("signOut() drops the token, the identity and drafts, tells the board, and fires the signed-out event", async () => {
    const seen = { signout: 0, whoami: [] as Array<Record<string, string>> };
    board(seen);
    const identity = await freshIdentity();
    expect(identity.authHeaders()).toEqual({ "X-Participant": "alice", "X-Token": "alice-secret" });
    const fired = vi.fn();
    window.addEventListener(identity.SIGNED_OUT_EVENT, fired);
    await identity.signOut();
    window.removeEventListener(identity.SIGNED_OUT_EVENT, fired);
    identity.stopAnswering();

    expect(seen.signout).toBe(1);
    expect(fired).toHaveBeenCalledTimes(1);
    expect(sessionStorage.getItem("edp8.token")).toBeNull();
    expect(sessionStorage.getItem("edp8.as")).toBe("");
    expect(sessionStorage.getItem("edp8.draft.t-1")).toBeNull();
    expect(identity.identity()).toBe("");
    expect(identity.authHeaders()).toEqual({ "X-Participant": "" }); // no token, no participant
  });

  it("the account menu's Sign out lands on the sign-in page: the next whoami carries no token and is 401", async () => {
    const seen = { signout: 0, whoami: [] as Array<Record<string, string>> };
    board(seen);
    const { identity, AppShell, ThemeProvider } = await freshModules();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <ThemeProvider>
          <MemoryRouter initialEntries={["/me"]}>
            <Routes>
              <Route element={<AppShell />}><Route path="me" element={<div>decisions body</div>} /></Route>
            </Routes>
          </MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("identity")).toHaveTextContent("alice"));
    fireEvent.click(screen.getByTestId("account-open"));
    fireEvent.click(await screen.findByTestId("sign-out"));

    expect(await screen.findByTestId("identity-panel")).toBeInTheDocument();
    expect(screen.getByTestId("signed-out")).toHaveTextContent("You are signed out");
    expect(seen.signout).toBe(1);
    const last = seen.whoami[seen.whoami.length - 1];
    expect(last).toEqual({ participant: "", token: "" });
    expect(sessionStorage.getItem("edp8.token")).toBeNull();
    identity.stopAnswering();
  });
});
