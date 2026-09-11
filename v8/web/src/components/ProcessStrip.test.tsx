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
      .filter((li) => li.getAttribute("aria-hidden") !== "true");
    expect(stages.map((s) => s.textContent?.replace(/current$/, "").trim())).toEqual([
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

  it("omits the 'Next:' sentence when showNext is false (epic page, Astra #36) but keeps the steps", () => {
    render(<ProcessStrip status="in_progress" showNext={false} />);
    expect(screen.queryByTestId("next-action")).not.toBeInTheDocument();
    expect(screen.getByTestId("stage-current")).toHaveTextContent("In progress");
  });

  it("shows an off-line state for blocked/partial/dropped instead of a false position", () => {
    render(<ProcessStrip status="blocked" />);
    expect(screen.queryByTestId("stage-current")).not.toBeInTheDocument();
    expect(screen.getByTestId("off-line-state")).toHaveTextContent("Blocked");
  });
});

// Coverage pass (c-7c51c6b69b): every stage sentence in `nextActionFor`, plus the unknown-status
// fallbacks (empty sentence; an unglossed off-line status renders with no meaning text).
describe("nextActionFor", () => {
  it("names a next action for every happy-path and off-line status, and nothing for an unknown one", () => {
    expect(nextActionFor("drafted")).toMatch(/Draft a design/);
    expect(nextActionFor("designed")).toMatch(/Sign off the design/);
    expect(nextActionFor("signed_off")).toMatch(/Mark it Ready/);
    expect(nextActionFor("ready")).toMatch(/Assign or spawn/);
    expect(nextActionFor("in_progress")).toMatch(/attach evidence/);
    expect(nextActionFor("in_review")).toMatch(/Review the evidence/);
    expect(nextActionFor("done")).toMatch(/Complete/);
    expect(nextActionFor("blocked")).toMatch(/Clear what blocks/);
    expect(nextActionFor("partial")).toMatch(/remaining work/);
    expect(nextActionFor("dropped")).toMatch(/stopped/);
    expect(nextActionFor("mystery")).toBe("");
  });

  it("an unglossed status is off-line with the raw word and an empty meaning", () => {
    render(<ProcessStrip status="mystery_state" />);
    const off = screen.getByTestId("off-line-state");
    expect(off).toHaveTextContent("mystery state");
    expect(screen.getByTestId("next-action")).toHaveTextContent("Next:");
  });
});
