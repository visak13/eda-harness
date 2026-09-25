import { it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Icon } from "./Icon";
import { ICON_PATHS, PROVIDER_ICONS, ROLE_ICONS, STATUS_ICONS, modelProvider, seatRole, type IconName } from "./iconPaths";
import { Avatar, ProviderIcon } from "./Avatar";
import { StatusChip } from "./StatusChip";
it("all 53 approved glyphs use named currentColor paths, no generic fallback", () => {
  expect(Object.keys(ICON_PATHS)).toHaveLength(54); // +code (epic-91fcd3b370 S3)
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
it("S-UI: one glyph per seat role and per provider, resolved from seat ids and model ids", () => {
  expect(Object.values(ROLE_ICONS)).toEqual(["role-architect", "role-engineer", "role-qa", "role-adversary", "role-sme"]);
  expect(Object.values(PROVIDER_ICONS)).toEqual(["provider-claude", "provider-gpt"]);
  const names = [...Object.values(ROLE_ICONS), ...Object.values(PROVIDER_ICONS)];
  const { container } = render(<>{names.map((n) => <Icon key={n} name={n} />)}</>);
  for (const n of names) expect(container.querySelector(`svg[data-icon="${n}"] path`)?.getAttribute("d")).toBe(ICON_PATHS[n]);
  expect(seatRole("engineer.s-32ddc49d96")).toBe("engineer");
  expect(seatRole("architect.epic-6a8a6020fd")).toBe("architect");
  expect(seatRole("qa")).toBe("qa");
  expect(seatRole("owner")).toBeNull();
  expect(seatRole("constructor")).toBeNull();
  expect(modelProvider("gpt-6-astra")).toBe("gpt");
  expect(modelProvider("codex/gpt-6-sol")).toBe("gpt");
  expect(modelProvider("claude-opus-5-5")).toBe("claude");
  expect(modelProvider("")).toBeNull();
});
it("S-UI / m-ff00fad1ec: an agent seat's avatar is its illustrated role character (no fetch); a person keeps the picture", () => {
  const { container } = render(<><Avatar id="engineer.s-1" /><Avatar id="adversary.epic-2" size={28} /><ProviderIcon model="gpt-6-astra" /><ProviderIcon model="claude-fable-5-1" /><ProviderIcon model="mystery" /></>);
  const eng = container.querySelector('[data-avatar-for="engineer.s-1"] svg');
  expect(eng).not.toBeNull();
  expect(eng).toHaveAttribute("viewBox", "0 0 36 36"); // the people avatars' canvas
  expect(eng?.innerHTML).toContain('d="M4 36c1-9 7-13 14-13s13 4 14 13"'); // the same torso as avatars.py
  expect(eng?.innerHTML).toContain("#EABF3B"); // the engineer's hard hat
  expect(container.querySelector('[data-avatar-for="adversary.epic-2"] svg')?.getAttribute("width")).toBe("28");
  expect(container.querySelector('[data-avatar-for="adversary.epic-2"]')).toHaveAttribute("data-role-icon", "adversary");
  expect(container.querySelector("img")).toBeNull();
  expect([...container.querySelectorAll("[data-provider-icon]")].map((e) => e.getAttribute("data-provider-icon"))).toEqual(["gpt", "claude"]);
});
