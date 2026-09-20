import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Drawer } from "./Drawer";

describe("Drawer", () => {
  it("renders nothing while closed", () => {
    const { container } = render(
      <Drawer open={false} onClose={() => {}} title="T">
        <button type="button">inside</button>
      </Drawer>,
    );
    expect(container.firstChild).toBeNull();
  });

  it("opens with the title, moves focus in, and locks body scroll", () => {
    render(
      <Drawer open onClose={() => {}} title="My drawer">
        <button type="button">first</button>
        <button type="button">last</button>
      </Drawer>,
    );
    const panel = screen.getByTestId("drawer-panel");
    expect(panel).toHaveAttribute("aria-label", "My drawer");
    // focus moves to the first focusable inside the panel (the header Close button)
    expect(panel.contains(document.activeElement)).toBe(true);
    expect(document.body.style.overflow).toBe("hidden");
  });

  it("falls back to the generic label when the title is not a string", () => {
    render(
      <Drawer open onClose={() => {}} title={<em>rich</em>}>
        <button type="button">first</button>
      </Drawer>,
    );
    expect(screen.getByTestId("drawer-panel")).toHaveAttribute("aria-label", "Drawer");
  });

  it("Esc and the close button and scrim all call onClose", () => {
    const onClose = vi.fn();
    render(
      <Drawer open onClose={onClose} title="T">
        <button type="button">first</button>
      </Drawer>,
    );
    const panel = screen.getByTestId("drawer-panel");
    fireEvent.keyDown(panel, { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    fireEvent.mouseDown(screen.getByTestId("drawer-scrim"));
    expect(onClose).toHaveBeenCalledTimes(3);
  });

  it("a mousedown inside the panel does not close (stops propagation)", () => {
    const onClose = vi.fn();
    render(
      <Drawer open onClose={onClose} title="T">
        <button type="button">first</button>
      </Drawer>,
    );
    fireEvent.mouseDown(screen.getByTestId("drawer-panel"));
    expect(onClose).not.toHaveBeenCalled();
  });

  it("traps Tab within the panel (focus stays inside)", () => {
    render(
      <Drawer open onClose={() => {}} title="T">
        <button type="button">first</button>
        <button type="button">last</button>
      </Drawer>,
    );
    const panel = screen.getByTestId("drawer-panel");
    screen.getByRole("button", { name: "last" }).focus();
    fireEvent.keyDown(panel, { key: "Tab" });
    expect(panel.contains(document.activeElement)).toBe(true);
  });

  it("traps Shift+Tab within the panel (focus stays inside)", () => {
    render(
      <Drawer open onClose={() => {}} title="T">
        <button type="button">first</button>
      </Drawer>,
    );
    const panel = screen.getByTestId("drawer-panel");
    screen.getByRole("button", { name: "first" }).focus();
    fireEvent.keyDown(panel, { key: "Tab", shiftKey: true });
    expect(panel.contains(document.activeElement)).toBe(true);
  });

  it("a non-Tab, non-Esc key is ignored", () => {
    const onClose = vi.fn();
    render(
      <Drawer open onClose={onClose} title="T">
        <button type="button">first</button>
      </Drawer>,
    );
    fireEvent.keyDown(screen.getByTestId("drawer-panel"), { key: "a" });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("restores focus to the opening trigger when no returnFocusTo is given (finding 7)", () => {
    const trigger = document.createElement("button");
    document.body.appendChild(trigger);
    trigger.focus();
    const { rerender } = render(
      <Drawer open onClose={() => {}} title="T"><button type="button">first</button></Drawer>,
    );
    expect(document.activeElement).not.toBe(trigger); // focus moved into the drawer
    rerender(<Drawer open={false} onClose={() => {}} title="T"><button type="button">first</button></Drawer>);
    expect(document.activeElement).toBe(trigger); // Esc/close returns to the trigger, not body
    trigger.remove();
  });

  it("returns focus to the trigger even if returnFocusTo is cleared while open — never to body (finding 7)", () => {
    const trigger = document.createElement("button");
    document.body.appendChild(trigger);
    trigger.focus();
    const { rerender } = render(
      <Drawer open onClose={() => {}} title="T" returnFocusTo={trigger}><button type="button">first</button></Drawer>,
    );
    // A re-render clears returnFocusTo while the drawer is open (focus is inside it now); the opener
    // captured at open must not be overwritten with an in-drawer node, or close would land on body.
    rerender(<Drawer open onClose={() => {}} title="T" returnFocusTo={null}><button type="button">first</button></Drawer>);
    rerender(<Drawer open={false} onClose={() => {}} title="T" returnFocusTo={null}><button type="button">first</button></Drawer>);
    expect(document.activeElement).toBe(trigger);
    expect(document.activeElement).not.toBe(document.body);
    trigger.remove();
  });

  it("restores focus to returnFocusTo when it closes", () => {
    const returnTarget = document.createElement("button");
    document.body.appendChild(returnTarget);
    const { rerender } = render(
      <Drawer open onClose={() => {}} title="T" returnFocusTo={returnTarget}>
        <button type="button">first</button>
      </Drawer>,
    );
    rerender(
      <Drawer open={false} onClose={() => {}} title="T" returnFocusTo={returnTarget}>
        <button type="button">first</button>
      </Drawer>,
    );
    expect(document.activeElement).toBe(returnTarget);
    returnTarget.remove();
  });
});
