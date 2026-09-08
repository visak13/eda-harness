import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { AgentLine } from "./AgentLine";

// Agent-text framing (design §15): name-first with the id after in mono, the role word, and a
// reader-relative tag that depends on whether a question is addressed to the viewer.

describe("AgentLine", () => {
  it("frames a question addressed to the viewer as 'Waiting on you', name first, id after", () => {
    render(<AgentLine by="engineer.s-1" kind="question" to="owner" viewer="owner" at="2026-09-08T10:00:00Z" />);
    expect(screen.getByTestId("agent-line")).toHaveTextContent("engineer"); // name (role prefix)
    expect(screen.getByTestId("agent-id")).toHaveTextContent("engineer.s-1"); // id after, in mono
    expect(screen.getByTestId("reader-tag")).toHaveTextContent("Waiting on you");
    expect(screen.getByText("Question")).toBeInTheDocument(); // glossary label for the kind
  });

  it("frames anything not addressed to the viewer as 'For your information'", () => {
    render(<AgentLine by="architect.epic-1" kind="note" to={null} viewer="owner" />);
    expect(screen.getByTestId("reader-tag")).toHaveTextContent("For your information");
  });

  it("a question addressed to someone else is not 'Waiting on you' for this viewer", () => {
    render(<AgentLine by="engineer.s-1" kind="question" to="reviewer.s-1" viewer="owner" />);
    expect(screen.getByTestId("reader-tag")).toHaveTextContent("For your information");
  });
});
