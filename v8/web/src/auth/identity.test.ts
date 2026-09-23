import { describe, it, expect, beforeEach, vi } from "vitest";
import { server } from "../test/setup";
import { http, HttpResponse } from "msw";

// identity.ts reads the URL exactly ONCE at module load, so each case sets the URL +
// sessionStorage, resets the module registry, then dynamically imports a fresh copy.
const loaded: Array<{ stopAnswering: () => void }> = [];
async function loadIdentity(href: string) {
  history.replaceState({}, "", href);
  vi.resetModules();
  const mod = await import("./identity");
  loaded.push(mod);
  await mod.sessionReady; // a copy still asking would adopt a LATER case's answer
  return mod;
}

beforeEach(async () => {
  // Each earlier copy is another "open tab" answering the session handshake: close them.
  for (const mod of loaded.splice(0)) mod.stopAnswering();
  sessionStorage.clear();
  history.replaceState({}, "", "/ui/");
});

describe("identity adapter", () => {
  it("reads ?as & ?token once, moves them to sessionStorage, strips token from the URL", async () => {
    const { identity, authHeaders } = await loadIdentity("/ui/?as=alice&token=s3cret");

    expect(identity()).toBe("alice");
    expect(sessionStorage.getItem("edp8.as")).toBe("alice");
    expect(sessionStorage.getItem("edp8.token")).toBe("s3cret");

    // token never survives in the address bar (history/bookmarks/shared deep links)
    expect(location.href).not.toContain("token");
    expect(new URL(location.href).searchParams.get("token")).toBeNull();
    // as is not stripped (links carry ?as= for parity)
    expect(new URL(location.href).searchParams.get("as")).toBe("alice");

    expect(authHeaders()).toEqual({ "X-Participant": "alice", "X-Token": "s3cret" });
  });

  it("every request carries X-Participant and X-Token", async () => {
    await loadIdentity("/ui/?as=bob&token=tok-9");
    const { api } = await import("../api/client");

    let seen: Record<string, string | null> = {};
    server.use(
      http.get("/v1/echo", ({ request }) => {
        seen = {
          participant: request.headers.get("X-Participant"),
          token: request.headers.get("X-Token"),
        };
        return HttpResponse.json({ ok: true, value: seen });
      }),
    );

    await api("/v1/echo");
    expect(seen).toEqual({ participant: "bob", token: "tok-9" });
  });

  it("defaults as=owner and sends no X-Token when none is provided", async () => {
    const { identity, authHeaders } = await loadIdentity("/ui/");

    expect(identity()).toBe("owner");
    const headers = authHeaders();
    expect(headers["X-Participant"]).toBe("owner");
    expect("X-Token" in headers).toBe(false);
  });

  it("falls back to the stored as when the URL omits it", async () => {
    sessionStorage.setItem("edp8.as", "carol");
    const { identity } = await loadIdentity("/ui/epics");
    expect(identity()).toBe("carol");
  });

  // S22 (t-f5d27a6f2e): a new tab has its own (empty) sessionStorage. A tab that holds the token
  // answers the same-origin handshake; the new tab adopts it before first render, URL untouched.
  it("a tab without a token receives the session from an open tab of the same identity", async () => {
    const first = await loadIdentity("/ui/?as=alice&token=s3cret");
    await first.sessionReady;
    sessionStorage.clear(); // the new tab's storage
    const second = await loadIdentity("/ui/epic/e-1?as=alice");
    await second.sessionReady;
    expect(second.authHeaders()).toEqual({ "X-Participant": "alice", "X-Token": "s3cret" });
    expect(location.href).not.toContain("token");
  });

  it("an open tab never hands its token to a tab asking for another identity", async () => {
    const first = await loadIdentity("/ui/?as=alice&token=s3cret");
    await first.sessionReady;
    sessionStorage.clear();
    const second = await loadIdentity("/ui/?as=bob");
    await second.sessionReady; // resolves on the timeout
    expect(second.authHeaders()).toEqual({ "X-Participant": "bob" });
  });

  it("a tab with no ?as adopts the answering tab's identity", async () => {
    const first = await loadIdentity("/ui/?as=carol&token=tok-c");
    await first.sessionReady;
    sessionStorage.clear();
    const second = await loadIdentity("/ui/epics");
    await second.sessionReady;
    expect(second.identity()).toBe("carol");
    expect(second.authHeaders()).toEqual({ "X-Participant": "carol", "X-Token": "tok-c" });
  });
});
