import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import { UsageWidget, usageTime } from "./UsageWidget";
import type { Usage, UsageWindow } from "../api/usage";

const window = (key: string, minutes: number | null, used: number | null): UsageWindow => ({
  key, window_minutes: minutes, used_percent: used, resets_at: used === null ? null : 4102444800,
  observed_at: null, status: used === null ? "unavailable" : "stale", reason: "Observation time unknown",
});
const fixture = (): Usage => ({ providers: [
  { provider: "claude", account_binding: "Linked account", source: "Claude Code statusline",
    received_at: "2026-09-18T08:56:52Z", retry_after_seconds: 30,
    windows: [window("five_hour", 300, 0), window("seven_day", 10080, 15), window("fable", null, null)] },
  { provider: "codex", account_binding: "Linked account", source: "Codex App Server",
    received_at: null, retry_after_seconds: 30,
    windows: [window("five_hour", 300, null), window("seven_day", 10080, 92)] },
] });

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(<QueryClientProvider client={qc}>
    <textarea aria-label="Source draft" defaultValue="Keep this draft" />
    <UsageWidget actor="owner" /><button>Outside</button>
  </QueryClientProvider>);
  return { qc, ...view };
}
beforeEach(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
  server.use(http.get("/v1/me/usage", () => HttpResponse.json({ ok: true, value: fixture() })));
});

describe("subscription Usage widget", () => {
  it("does not fetch closed; opens nonmodal with zero != unavailable, Fable under Claude", async () => {
    const request = vi.fn();
    server.use(http.get("/v1/me/usage", ({ request: req }) => {
      request(); expect(req.headers.get("X-Participant")).toBe("owner");
      return HttpResponse.json({ ok: true, value: fixture() });
    }));
    mount();
    expect(request).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Usage" }));
    const dialog = screen.getByRole("dialog", { name: "Subscription usage" });
    expect(dialog).not.toHaveAttribute("aria-modal", "true");
    expect(await screen.findByText("0% used")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Claude" })).getByText("Fable")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Codex" })).queryByText("Fable")).toBeNull();
    expect(screen.getAllByRole("meter")).toHaveLength(3);
    expect(screen.getByRole("button", { name: /Refresh in/ })).toBeDisabled();
    expect(request).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/times are local/i)).toBeInTheDocument();
  });

  it("Escape and Close return trigger focus without altering draft or URL; outside focus leaves freely", async () => {
    mount();
    const url = location.href;
    const trigger = screen.getByRole("button", { name: "Usage" });
    fireEvent.click(trigger);
    await screen.findByText("0% used");
    const close = screen.getByRole("button", { name: "Close Subscription usage" });
    close.focus(); fireEvent.keyDown(close, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull(); expect(trigger).toHaveFocus();
    expect(screen.getByRole("textbox")).toHaveValue("Keep this draft");
    expect(location.href).toBe(url);
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("button", { name: "Close Subscription usage" }));
    expect(trigger).toHaveFocus();
    fireEvent.click(trigger); screen.getByRole("button", { name: "Outside" }).focus();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByRole("button", { name: "Outside" })).toHaveFocus();
  });

  it("ordinary source updates add and remove Codex 5h without remounting", async () => {
    const { qc } = mount(); fireEvent.click(screen.getByRole("button", { name: "Usage" }));
    await screen.findByText("92% used");
    const data = fixture(); data.providers[1].windows[0] = window("five_hour", 300, 8);
    server.use(http.get("/v1/me/usage", () => HttpResponse.json({ ok: true, value: data })));
    await qc.refetchQueries({ queryKey: ["usage", "owner"] });
    expect(await screen.findByText("8% used")).toBeInTheDocument();
    server.use(http.get("/v1/me/usage", () => HttpResponse.json({ ok: true, value: fixture() })));
    await qc.refetchQueries({ queryKey: ["usage", "owner"] });
    await waitFor(() => expect(screen.queryByText("8% used")).toBeNull());
  });

  it("failure hides cached numbers, 401 opens identity panel", async () => {
    const { qc } = mount(); fireEvent.click(screen.getByRole("button", { name: "Usage" }));
    await screen.findByText("0% used");
    server.use(http.get("/v1/me/usage", () => HttpResponse.json({ ok: false, hint: "failed" }, { status: 500 })));
    await qc.refetchQueries({ queryKey: ["usage", "owner"] });
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be refreshed");
    expect(screen.queryByText("0% used")).toBeNull();
    server.use(http.get("/v1/me/usage", () => HttpResponse.json({ ok: false }, { status: 401 })));
    await qc.refetchQueries({ queryKey: ["usage", "owner"] });
    expect(await screen.findByTestId("identity-panel")).toBeInTheDocument();
  });

  it("expired reset never becomes new-period zero; reset includes timezone", async () => {
    const data = fixture(); data.providers[0].windows[0].resets_at = 1;
    server.use(http.get("/v1/me/usage", () => HttpResponse.json({ ok: true, value: data })));
    mount(); fireEvent.click(screen.getByRole("button", { name: "Usage" }));
    expect(await screen.findByText("Reset elapsed; awaiting source update")).toBeInTheDocument();
    expect(screen.queryByText("0% used")).toBeNull();
    expect(usageTime(null)).toBe("Unknown"); expect(usageTime("invalid")).toBe("Unknown");
    expect(usageTime(4102444800)).not.toBe("Unknown");
  });
});
