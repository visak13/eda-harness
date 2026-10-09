import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { flashInSlot, slotRef, slotVisible, useSlotFlash } from "./statusSlot";

// qa fail 8: a confirmation takes the composer's status slot for a few seconds, then the slot restores itself.
function Slot(): React.JSX.Element {
  const flash = useSlotFlash();
  return <span data-testid="slot" ref={(el) => { if (el) { el.getClientRects = () => [{}] as unknown as DOMRectList; slotRef(el); } }}>{flash ?? "nobody is woken"}</span>;
}

describe("status slot", () => {
  afterEach(() => vi.useRealTimers());

  it("with no slot on screen it shows nothing and says so", () => {
    expect(slotVisible()).toBe(false);
    expect(flashInSlot("Requirement marked.")).toBe(false);
  });

  it("shows the text in the slot, then restores it", () => {
    vi.useFakeTimers();
    render(<Slot />);
    expect(screen.getByTestId("slot")).toHaveTextContent("nobody is woken");
    let shown = false;
    act(() => { shown = flashInSlot("Requirement marked.", 6000); });
    expect(shown).toBe(true);
    expect(screen.getByTestId("slot")).toHaveTextContent("Requirement marked.");
    act(() => { vi.advanceTimersByTime(6001); });
    expect(screen.getByTestId("slot")).toHaveTextContent("nobody is woken");
  });
});
