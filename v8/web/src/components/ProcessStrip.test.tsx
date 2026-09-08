import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { ProcessStrip, nextActionFor } from "./ProcessStrip";

// The process strip (design §16 / §21 amendment 2): ordered stages, the current one marked, and a
// named next action.

describe("ProcessStrip", () => {
  it("renders the seven stages in order and marks the current one", () => {
    render(<ProcessStrip status="in_review" />);
    const strip = screen.getByTestId("process-strip");
    const stages = within(strip)
      .getAllByRole("listitem")
      .filter((li) => li.getAttribute("aria-hidden") !== "true" && !li.textContent?.includes("→"));
    expect(stages.map((s) => s.textContent?.replace(" · current", "").trim())).toEqual([
      "Drafted", "Designed", "Signed off", "Ready", "In progress", "In review", "Done",
    ]);
    const current = screen.getByTestId("stage-current");
    expect(current).toHaveTextContent("In review");
    expect(current).toHaveAttribute("aria-current", "step");
  });

  it("names the next action for the current stage", () => {
    render(<ProcessStrip status="in_review" />);
    expect(screen.getByTestId("next-action")).toHaveTextContent(nextActionFor("in_review"));
    expect(screen.getByTestId("next-action")).toHaveTextContent("Review the evidence");
  });

  it("accepts a linked next-action node (a control), overriding the default sentence", () => {
    render(<ProcessStrip status="ready" nextAction={<a href="#spawn">Spawn a seat</a>} />);
    expect(within(screen.getByTestId("next-action")).getByRole("link", { name: "Spawn a seat" })).toBeInTheDocument();
  });

  it("shows an off-line state for blocked/partial/dropped instead of a false position", () => {
    render(<ProcessStrip status="blocked" />);
    expect(screen.queryByTestId("stage-current")).not.toBeInTheDocument();
    expect(screen.getByTestId("off-line-state")).toHaveTextContent("Blocked");
  });
});
