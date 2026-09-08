import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Term } from "./Term";
import { StatusChip } from "./StatusChip";

// The tooltip contract (design §15, criterion c-581d50496d): a glossary term shows its plain label,
// exposes the one-line meaning via aria-describedby, and the trigger is reachable by keyboard focus.

describe("Term", () => {
  it("renders the plain label and attaches the meaning as a keyboard-reachable tooltip", () => {
    render(<Term category="gate" value="design_signoff" />);
    const trigger = screen.getByText("Design sign-off");
    // Keyboard reachable.
    expect(trigger).toHaveAttribute("tabindex", "0");
    // aria-describedby points at a role=tooltip element carrying the meaning verbatim.
    const tipId = trigger.getAttribute("aria-describedby");
    expect(tipId).toBeTruthy();
    const tip = document.getElementById(tipId!);
    expect(tip).toHaveAttribute("role", "tooltip");
    expect(tip).toHaveTextContent("Decide whether a design can proceed.");
  });

  it("falls back to the de-underscored raw value with no tooltip when a value is not glossed", () => {
    render(<Term category="gate" value="mystery_gate" />);
    const el = screen.getByText("mystery gate");
    expect(el).not.toHaveAttribute("aria-describedby");
  });

  it("renders check and role labels from the glossary", () => {
    render(
      <>
        <Term category="check" value="look" />
        <Term category="role" value="qa" />
      </>,
    );
    expect(screen.getByText("Look")).toHaveAttribute("aria-describedby");
    expect(screen.getByText("QA")).toHaveAttribute("aria-describedby");
  });
});

describe("StatusChip glossary tooltip", () => {
  it("shows the status word and its meaning, reachable by focus", () => {
    render(<StatusChip status="in_review" />);
    const chip = screen.getByTestId("status-chip");
    expect(chip).toHaveTextContent("In review");
    expect(chip).toHaveAttribute("tabindex", "0");
    const tip = document.getElementById(chip.getAttribute("aria-describedby")!);
    expect(tip).toHaveTextContent("Evidence is ready to check.");
  });

  it("keeps its data-status hook for downstream tests", () => {
    render(<StatusChip status="blocked" />);
    expect(screen.getByTestId("status-chip")).toHaveAttribute("data-status", "blocked");
  });
});
