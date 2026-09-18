import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { FeedEvent } from "./feed";
import { DraftGuardProvider, useDraftGuard } from "./useDraftGuard";
let fire: ((e: FeedEvent) => void) | null = null;
vi.mock("./feed", () => ({ subscribeFeed: (cb: (e: FeedEvent) => void) => { fire = cb; return () => { fire = null; }; } }));
function Harness() {
  const { pending, flush, setDirty } = useDraftGuard();
  return <div><span data-testid="pending">{pending}</span><textarea aria-label="Draft" />
    <button onClick={() => setDirty("c1", true)}>dirty</button>
    <button onClick={() => setDirty("a", true, "other")}>dirty A</button>
    <button onClick={() => setDirty("b", true, "untouched")}>dirty B</button>
    <button onClick={() => setDirty("a", false)}>clean A</button>
    <button onClick={() => setDirty("c1", false)}>clean</button><button onClick={flush}>flush</button></div>;
}
function mount() {
  const qc = new QueryClient();
  for (const key of [["ticket", "other"], ["ticket", "untouched"], ["avatar", "owner"]]) qc.setQueryData(key, {});
  const invalidate = vi.spyOn(qc, "invalidateQueries");
  render(<QueryClientProvider client={qc}><DraftGuardProvider><Harness /></DraftGuardProvider></QueryClientProvider>);
  return invalidate;
}
beforeEach(() => { fire = null; vi.useFakeTimers(); });
afterEach(() => vi.useRealTimers());
const event = (seq = 1): FeedEvent => ({ seq, kind: "message_sent", subject_id: "other" });
const tick = () => act(() => vi.advanceTimersByTime(250));
describe("scoped draft guard", () => {
  it("releases clean A while unrelated B stays dirty", () => {
    const invalidate = mount();
    fireEvent.click(screen.getByText("dirty A")); fireEvent.click(screen.getByText("dirty B"));
    act(() => { fire!(event()); fire!({ ...event(2), subject_id: "untouched" }); }); tick();
    expect(invalidate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("clean A")); tick();
    expect(invalidate).toHaveBeenCalledExactlyOnceWith({ queryKey: ["ticket", "other"], exact: true });
    expect(screen.getByTestId("pending")).not.toHaveTextContent(/^0$/);
  });
  it("coalesces the characterized 20-event global storm to one affected key within 250ms", () => {
    const invalidate = mount();
    const node = screen.getByTestId("pending");
    act(() => { for (let i = 1; i <= 20; i++) fire!(event(i)); });
    expect(invalidate).not.toHaveBeenCalled(); tick();
    expect(invalidate).toHaveBeenCalledExactlyOnceWith({ queryKey: ["ticket", "other"], exact: true });
    expect(screen.getByTestId("pending")).toBe(node);
  });
  it("holds affected keys and flushes on clean", () => {
    const invalidate = mount(); fireEvent.click(screen.getByText("dirty"));
    act(() => { fire!(event()); fire!(event(2)); }); tick();
    expect(invalidate).not.toHaveBeenCalled(); expect(screen.getByTestId("pending")).toHaveTextContent("2");
    fireEvent.click(screen.getByText("clean")); tick();
    expect(invalidate).toHaveBeenCalledTimes(1); expect(screen.getByTestId("pending")).toHaveTextContent("0");
  });
  it("explicit flush keeps draft DOM, text, caret and focus", () => {
    const invalidate = mount(); fireEvent.click(screen.getByText("dirty"));
    const draft = screen.getByRole("textbox") as HTMLTextAreaElement;
    fireEvent.change(draft, { target: { value: "unsent words" } }); draft.focus(); draft.setSelectionRange(3, 5);
    act(() => fire!(event())); fireEvent.click(screen.getByText("flush"));
    expect(invalidate).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("textbox")).toBe(draft); expect(draft.value).toBe("unsent words");
    expect(draft.selectionStart).toBe(3); expect(draft.selectionEnd).toBe(5); expect(draft).toHaveFocus();
  });
  it("unknown-event fallback is coalesced and excludes identity/avatar/resolve data", () => {
    const invalidate = mount(); act(() => { for (let seq = 1; seq <= 20; seq++) fire!({ seq }); }); tick();
    expect(invalidate).toHaveBeenCalledTimes(2);
    expect(invalidate.mock.calls.every(([filter]) => filter?.queryKey?.[0] === "ticket")).toBe(true);
  });
});
