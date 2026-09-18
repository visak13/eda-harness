import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { FeedEvent } from "./feed";
import { DraftGuardProvider, useDraftGuard } from "./useDraftGuard";

// Control the feed: capture the provider's onEvent callback so a test can fire events on demand.
let fire: ((e: FeedEvent) => void) | null = null;
vi.mock("./feed", () => ({
  subscribeFeed: (cb: (e: FeedEvent) => void) => {
    fire = cb;
    return () => {
      fire = null;
    };
  },
}));

function Harness(): React.JSX.Element {
  const { pending, flush, setDirty } = useDraftGuard();
  return (
    <div>
      <span data-testid="pending">{pending}</span>
      <button onClick={() => setDirty("c1", true)}>dirty</button>
      <button onClick={() => setDirty("c1", false)}>clean</button>
      <button onClick={flush}>flush</button>
    </div>
  );
}

let qc: QueryClient;
let invalidate: ReturnType<typeof vi.spyOn>;

function mount() {
  qc = new QueryClient();
  invalidate = vi.spyOn(qc, "invalidateQueries");
  render(
    <QueryClientProvider client={qc}>
      <DraftGuardProvider>
        <Harness />
      </DraftGuardProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  fire = null;
});

describe("useDraftGuard", () => {
  it("refreshes immediately when no composer is dirty", () => {
    mount();
    act(() => fire!({ seq: 1 }));
    expect(invalidate).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("pending")).toHaveTextContent("0");
  });

  it("characterizes the pre-S2 burst: one global invalidation per event, stable child DOM", () => {
    mount();
    const node = screen.getByTestId("pending");
    act(() => { for (let seq = 1; seq <= 20; seq++) fire!({ seq, kind: "message_sent", subject_id: "other" }); });
    expect(invalidate).toHaveBeenCalledTimes(20);
    expect(invalidate.mock.calls.every((args) => args.length === 0)).toBe(true);
    expect(screen.getByTestId("pending")).toBe(node);
  });

  it("holds the refresh while a composer is dirty and counts 'N new'", () => {
    mount();
    fireEvent.click(screen.getByText("dirty"));
    act(() => fire!({ seq: 1 }));
    act(() => fire!({ seq: 2 }));
    expect(invalidate).not.toHaveBeenCalled();
    expect(screen.getByTestId("pending")).toHaveTextContent("2");
  });

  it("delivers the held refresh when the last composer clears", () => {
    mount();
    fireEvent.click(screen.getByText("dirty"));
    act(() => fire!({ seq: 1 }));
    fireEvent.click(screen.getByText("clean"));
    expect(invalidate).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("pending")).toHaveTextContent("0");
  });

  it("flush refreshes and resets the count", () => {
    mount();
    fireEvent.click(screen.getByText("dirty"));
    act(() => fire!({ seq: 1 }));
    fireEvent.click(screen.getByText("flush"));
    expect(invalidate).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("pending")).toHaveTextContent("0");
  });
});
