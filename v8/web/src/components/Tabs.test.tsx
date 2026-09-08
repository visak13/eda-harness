import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Tabs, type Tab } from "./Tabs";

const TABS: Tab[] = [
  { key: "overview", label: "Overview" },
  { key: "work", label: "Work", count: 3 },
  { key: "docs", label: "Docs", count: 0 },
];

describe("Tabs", () => {
  it("renders a tablist with a tab per entry and shows counts when numeric", () => {
    render(<Tabs tabs={TABS} active="overview" onChange={() => {}} />);
    expect(screen.getByRole("tablist", { name: "Sections" })).toBeInTheDocument();
    expect(screen.getAllByRole("tab")).toHaveLength(3);
    // count is rendered for entries with a numeric count (including 0), not for undefined
    expect(screen.getByRole("tab", { name: /Work/ })).toHaveTextContent("3");
    expect(screen.getByRole("tab", { name: /Docs/ })).toHaveTextContent("0");
    // Overview has no count span
    expect(screen.getByRole("tab", { name: "Overview" }).textContent).toBe("Overview");
  });

  it("marks the active tab aria-selected and roving-tabindex", () => {
    render(<Tabs tabs={TABS} active="work" onChange={() => {}} />);
    const work = screen.getByRole("tab", { name: /Work/ });
    const overview = screen.getByRole("tab", { name: "Overview" });
    expect(work).toHaveAttribute("aria-selected", "true");
    expect(work).toHaveAttribute("tabindex", "0");
    expect(overview).toHaveAttribute("aria-selected", "false");
    expect(overview).toHaveAttribute("tabindex", "-1");
  });

  it("clicking a tab calls onChange with its key", () => {
    const onChange = vi.fn();
    render(<Tabs tabs={TABS} active="overview" onChange={onChange} />);
    fireEvent.click(screen.getByRole("tab", { name: /Work/ }));
    expect(onChange).toHaveBeenCalledWith("work");
  });

  it("ArrowRight moves to the next tab", () => {
    const onChange = vi.fn();
    render(<Tabs tabs={TABS} active="overview" onChange={onChange} />);
    fireEvent.keyDown(screen.getByRole("tab", { name: "Overview" }), { key: "ArrowRight" });
    expect(onChange).toHaveBeenCalledWith("work");
  });

  it("ArrowRight from the last tab wraps to the first", () => {
    const onChange = vi.fn();
    render(<Tabs tabs={TABS} active="docs" onChange={onChange} />);
    fireEvent.keyDown(screen.getByRole("tab", { name: /Docs/ }), { key: "ArrowRight" });
    expect(onChange).toHaveBeenCalledWith("overview");
  });

  it("ArrowLeft moves to the previous tab and wraps at the start", () => {
    const onChange = vi.fn();
    render(<Tabs tabs={TABS} active="overview" onChange={onChange} />);
    // from the first tab, ArrowLeft wraps to the last
    fireEvent.keyDown(screen.getByRole("tab", { name: "Overview" }), { key: "ArrowLeft" });
    expect(onChange).toHaveBeenCalledWith("docs");
  });

  it("ignores keys other than the horizontal arrows", () => {
    const onChange = vi.fn();
    render(<Tabs tabs={TABS} active="overview" onChange={onChange} />);
    const overview = screen.getByRole("tab", { name: "Overview" });
    fireEvent.keyDown(overview, { key: "ArrowDown" });
    fireEvent.keyDown(overview, { key: "Home" });
    fireEvent.keyDown(overview, { key: "Enter" });
    expect(onChange).not.toHaveBeenCalled();
  });
});
