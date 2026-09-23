import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { FeedEvent, FeedOptions } from "./feed";
import { DraftGuardProvider, useDraftGuard } from "./useDraftGuard";
import { onAttentionChanged } from "./notificationEvents";
let fire: ((e: FeedEvent) => void) | null = null;
let options: FeedOptions | undefined;
vi.mock("./feed", () => ({ subscribeFeed: (cb: (e: FeedEvent) => void, opts?: FeedOptions) => { fire = cb; options = opts; return () => { fire = null; }; } }));
function Harness() {
  const { setDirty, hasDirty } = useDraftGuard();
  const [seen, setSeen] = useState("unknown");
  return <div><textarea aria-label="Draft" /><button onClick={() => setSeen(String(hasDirty()))}>check</button>
    <button onClick={() => setDirty("c1", true, "other")}>dirty</button>
    <button onClick={() => setDirty("c1", false)}>clean</button>
    <output data-testid="dirty">{seen}</output></div>;
}
function mount() {
  const qc = new QueryClient();
  for (const key of [["ticket", "other"], ["ticket", "untouched"], ["avatar", "owner"]]) qc.setQueryData(key, {});
  const invalidate = vi.spyOn(qc, "invalidateQueries");
  render(<QueryClientProvider client={qc}><DraftGuardProvider><Harness /></DraftGuardProvider></QueryClientProvider>);
  return invalidate;
}
beforeEach(() => { fire = null; options = undefined; vi.useFakeTimers(); });
afterEach(() => vi.useRealTimers());
const event = (seq = 1): FeedEvent => ({ seq, kind: "message_sent", subject_id: "other" });
const tick = () => act(() => vi.advanceTimersByTime(250));
describe("live refresh (S19: drafts never hold it)", () => {
  it("subscribes to the page's view feed, not the wake-filtered seat feed", () => {
    mount();
    expect(options?.watch).toBe(true);
  });
  it("a dirty draft on the affected ticket does NOT hold its refresh (chat freeze)", () => {
    const invalidate = mount(); fireEvent.click(screen.getByText("dirty"));
    act(() => fire!(event())); tick();
    expect(invalidate).toHaveBeenCalledExactlyOnceWith({ queryKey: ["ticket", "other"], exact: true }, { cancelRefetch: false });
  });
  it("coalesces the characterized 20-event storm to one affected key within 250ms", () => {
    const invalidate = mount();
    act(() => { for (let i = 1; i <= 20; i++) fire!(event(i)); });
    expect(invalidate).not.toHaveBeenCalled(); tick();
    expect(invalidate).toHaveBeenCalledExactlyOnceWith({ queryKey: ["ticket", "other"], exact: true }, { cancelRefetch: false });
  });
  it("refresh under a draft keeps the draft DOM, text, caret and focus", () => {
    const invalidate = mount(); fireEvent.click(screen.getByText("dirty"));
    const draft = screen.getByRole("textbox") as HTMLTextAreaElement;
    fireEvent.change(draft, { target: { value: "unsent words" } }); draft.focus(); draft.setSelectionRange(3, 5);
    act(() => fire!(event())); tick();
    expect(invalidate).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("textbox")).toBe(draft); expect(draft.value).toBe("unsent words");
    expect(draft.selectionStart).toBe(3); expect(draft.selectionEnd).toBe(5); expect(draft).toHaveFocus();
  });
  it("keeps the dirty registry for leave-page guards", () => {
    mount(); fireEvent.click(screen.getByText("dirty")); fireEvent.click(screen.getByText("check"));
    expect(screen.getByTestId("dirty")).toHaveTextContent("true");
    fireEvent.click(screen.getByText("clean")); fireEvent.click(screen.getByText("check"));
    expect(screen.getByTestId("dirty")).toHaveTextContent("false");
  });
  it("pings notifications only for events that page this viewer", () => {
    mount(); const heard = vi.fn(); const off = onAttentionChanged(heard);
    act(() => fire!({ ...event(1), why: null }));
    expect(heard).not.toHaveBeenCalled();
    act(() => fire!({ ...event(2), why: "addressed to you" }));
    expect(heard).toHaveBeenCalledTimes(1); off();
  });
  it("unknown-event fallback is coalesced and excludes identity/avatar/resolve data", () => {
    const invalidate = mount(); act(() => { for (let seq = 1; seq <= 20; seq++) fire!({ seq }); }); tick();
    expect(invalidate).toHaveBeenCalledTimes(2);
    expect(invalidate.mock.calls.every(([filter]) => filter?.queryKey?.[0] === "ticket")).toBe(true);
  });

  // S22 (consult #2): 20 s of events every 150 ms against a 1 s API. Before: every 250 ms window
  // cancelled the in-flight refetch (cancelRefetch:true), so no refetch completed until the storm
  // ended. Now: never cancelled, one in flight per key, and a trailing refetch lands the newest event.
  it("a 20 s storm at 150 ms with a 1 s API: refetches complete during the storm, newest lands ≤ 2 s after", async () => {
    let server = 0; // the board's newest event seq
    let started = 0, completed = 0, aborted = 0;
    function Thread() {
      const q = useQuery({ queryKey: ["ticket", "other"], queryFn: ({ signal }) => {
        started++;
        const snapshot = server;
        return new Promise<number>((resolve, reject) => {
          const t = setTimeout(() => { completed++; resolve(snapshot); }, 1000);
          signal.addEventListener("abort", () => { clearTimeout(t); aborted++; reject(new DOMException("aborted", "AbortError")); });
        });
      } });
      return <output data-testid="shown">{q.data ?? "none"}</output>;
    }
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={qc}><DraftGuardProvider><Thread /></DraftGuardProvider></QueryClientProvider>);
    await act(async () => { await vi.advanceTimersByTimeAsync(1100); }); // first load
    expect(screen.getByTestId("shown")).toHaveTextContent("0");
    const during: number[] = [];
    for (let t = 0; t < 20_000; t += 150) {
      server++;
      act(() => fire!(event(server)));
      await act(async () => { await vi.advanceTimersByTimeAsync(150); });
      during.push(completed);
    }
    const last = server;
    expect(aborted).toBe(0); // no cancelled in-flight refetch loop
    expect(completed).toBeGreaterThanOrEqual(15); // ~one per second of storm, not zero
    expect(started - completed).toBeLessThanOrEqual(1); // never more than one in flight
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(screen.getByTestId("shown")).toHaveTextContent(String(last)); // newest within 2 s of the end
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    const settled = started;
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(started).toBe(settled); // coalesced after settle: no refetch loop on a quiet feed
  });
});
