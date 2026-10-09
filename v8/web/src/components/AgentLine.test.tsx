import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { AgentLine } from "./AgentLine";

// Agent-text framing (design §15): name-first with the id after in mono, and the role word.
// s-aa76c83998: the reader-relative waiting tag is gone.

describe("AgentLine", () => {
  it("frames a message name first, id after, with the role word and the kind label", () => {
    render(<AgentLine by="engineer.s-1" kind="question" at="2026-09-08T10:00:00Z" />);
    expect(screen.getByTestId("agent-line")).toHaveTextContent("engineer"); // name (role prefix)
    expect(screen.getByTestId("agent-id")).toHaveTextContent("engineer.s-1"); // id after, in mono
    expect(screen.getByText("Question")).toBeInTheDocument(); // glossary label for the kind
  });

  it("carries no reader-relative tag", () => {
    render(<AgentLine by="architect.epic-1" kind="note" />);
    expect(screen.queryByTestId("reader-tag")).toBeNull();
  });
});
