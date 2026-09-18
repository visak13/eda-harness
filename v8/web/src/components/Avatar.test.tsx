import { it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import { Avatar, bumpAvatarVersion } from "./Avatar";
let actor = "owner";
vi.mock("../auth/identity", () => ({ identity: () => actor, authHeaders: () => ({ "X-Participant": "owner", "X-Token": "s2-test-token" }) }));
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); actor = "owner"; });
it("shares authenticated bytes across instances, avoids rerender refetch and releases the last URL", async () => {
  let requests = 0;
  server.use(http.get("/v1/avatars/:id", ({ request }) => {
    requests++;
    if (request.headers.get("X-Participant") !== "owner" || request.headers.get("X-Token") !== "s2-test-token") return new HttpResponse(null, { status: 401 });
    return new HttpResponse("<svg/>", { headers: { "content-type": "image/svg+xml" } });
  }));
  const create = vi.fn(() => "blob:s2-avatar"), revoke = vi.fn();
  vi.stubGlobal("URL", class extends URL { static createObjectURL = create; static revokeObjectURL = revoke; });
  const view = render(<><Avatar id="owner" /><Avatar id="owner" /></>);
  await waitFor(() => expect(screen.getAllByTestId("avatar")[0]).toHaveAttribute("src", "blob:s2-avatar"));
  const node = screen.getAllByTestId("avatar")[0];
  view.rerender(<><Avatar id="owner" /><Avatar id="owner" /></>);
  expect(screen.getAllByTestId("avatar")[0]).toBe(node); expect(requests).toBe(1); expect(create).toHaveBeenCalledTimes(1);
  view.rerender(<Avatar id="owner" />);
  expect(revoke).not.toHaveBeenCalled(); // another consumer still owns the same URL
  view.unmount(); expect(revoke).toHaveBeenCalledExactlyOnceWith("blob:s2-avatar"); vi.unstubAllGlobals();
});
it("handle-authenticated save refreshes canonical-id avatars", async () => {
  actor = "@owner-handle";
  const urls: string[] = [];
  server.use(http.get("/v1/avatars/:id", ({ request }) => { urls.push(request.url); return new HttpResponse("<svg/>"); }));
  vi.stubGlobal("URL", class extends URL { static createObjectURL = () => `blob:${urls.length}`; static revokeObjectURL = vi.fn(); });
  const view = render(<Avatar id="canonical-owner" />);
  await waitFor(() => expect(screen.getByTestId("avatar")).toHaveAttribute("src", "blob:1"));
  act(() => bumpAvatarVersion("canonical-owner"));
  await waitFor(() => expect(urls).toHaveLength(2));
  expect(urls[1]).toContain("&v="); view.unmount();
});
it("a failed shared request is evicted so a new consumer can recover", async () => {
  let requests = 0;
  server.use(http.get("/v1/avatars/:id", () => ++requests === 1 ? new HttpResponse(null, { status: 503 }) : new HttpResponse("<svg/>")));
  vi.stubGlobal("URL", class extends URL { static createObjectURL = () => "blob:recovered"; static revokeObjectURL = vi.fn(); });
  const view = render(<Avatar id="recover" />);
  await waitFor(() => expect(requests).toBe(1));
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
  view.rerender(<><Avatar id="recover" /><Avatar id="recover" /></>);
  await waitFor(() => expect(screen.getAllByTestId("avatar")[1]).toHaveAttribute("src", "blob:recovered"));
  expect(requests).toBe(2); view.unmount();
});
