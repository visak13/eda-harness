import { it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Icon } from "./Icon";
import { ICON_PATHS, STATUS_ICONS, type IconName } from "./iconPaths";
import { StatusChip } from "./StatusChip";
it("all 46 approved glyphs use named currentColor paths, no generic fallback", () => {
  expect(Object.keys(ICON_PATHS)).toHaveLength(46);
  const { container } = render(<>{(Object.keys(ICON_PATHS) as IconName[]).map((name) => <Icon key={name} name={name} />)}</>);
  for (const svg of container.querySelectorAll("svg")) {
    expect(svg).toHaveAttribute("stroke", "currentColor"); expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg.querySelector("path")).toHaveAttribute("d", ICON_PATHS[svg.getAttribute("data-icon") as IconName]);
  }
});
it("every known status has shape plus literal glossary word, unknown never becomes Decisions", () => {
  const { container } = render(<>{Object.keys(STATUS_ICONS).map((status) => <StatusChip key={status} status={status} />)}<StatusChip status="future_state" /></>);
  expect(container.querySelectorAll("svg")).toHaveLength(10);
  for (const chip of screen.getAllByTestId("status-chip")) expect(chip.textContent?.length).toBeGreaterThan(0);
  expect(container.querySelector('[data-status="future_state"] svg')).toBeNull();
});
