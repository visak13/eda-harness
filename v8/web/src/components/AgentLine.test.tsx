import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { AgentLine } from "./AgentLine";

// Agent-text framing (design §15): name-first with the id after in mono, the role word, and a
// reader-relative tag: "Waiting on you" only when the message is in the viewer's attention list (S20, the caller passes it).

describe("AgentLine", () => {
  it("frames a message waiting on the viewer as 'Waiting on you', name first, id after", () => {
    render(<AgentLine by="engineer.s-1" kind="question" waiting at="2026-09-08T10:00:00Z" />);
    expect(screen.getByTestId("agent-line")).toHaveTextContent("engineer"); // name (role prefix)
    expect(screen.getByTestId("agent-id")).toHaveTextContent("engineer.s-1"); // id after, in mono
    expect(screen.getByTestId("reader-tag")).toHaveTextContent("Waiting on you");
    expect(screen.getByText("Question")).toBeInTheDocument(); // glossary label for the kind
  });

  it("frames anything not addressed to the viewer as 'For your information'", () => {
    render(<AgentLine by="architect.epic-1" kind="note" />);
    expect(screen.getByTestId("reader-tag")).toHaveTextContent("For your information");
  });

  it("a question not in the viewer's attention list (answered, or for someone else) is not 'Waiting on you'", () => {
    render(<AgentLine by="engineer.s-1" kind="question" waiting={false} />);
    expect(screen.getByTestId("reader-tag")).toHaveTextContent("For your information");
  });
});
