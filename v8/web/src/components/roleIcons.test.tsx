import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { render } from "@testing-library/react";
import { BOARD_ROLES } from "../api/types";
import { label as glossLabel } from "../copy/glossary";
import { Avatar } from "./Avatar";
import { AGENT_AVATARS } from "./agentAvatars";
import { ICON_PATHS, ROLE_ICONS, roleLabel, seatRole } from "./iconPaths";

// t-20f0718990 (owner m-3136ceca05 "doctor seat shows ? icon"): every role the board knows renders with an
// icon, never the board's unknown "?" template. Agent roles draw their illustrated avatar and have a stroke
// glyph; the two human-only roles (owner, expert) are people and keep their picture avatar.

const HUMAN_ROLES = new Set(["owner", "expert"]);

/** The board's Role enum members, read from edp8/schemas.py so a new board role fails here first. */
function boardRoleEnum(): string[] {
  const src = readFileSync("../src/edp8/schemas.py", "utf8");
  const body = src.split(/class Role\(StrEnum\):/)[1]!.split(/\nclass /)[0]!;
  return [...body.matchAll(/^ {4}(\w+) = "(\w+)"/gm)].map((m) => m[2]!);
}

describe("every board role has an icon", () => {
  it("BOARD_ROLES is the board's Role enum", () => {
    expect([...BOARD_ROLES].sort()).toEqual(boardRoleEnum().sort());
  });

  it.each(BOARD_ROLES.filter((r) => !HUMAN_ROLES.has(r)))("%s seat renders its role avatar and glyph", (role) => {
    const { container } = render(<Avatar id={`${role}.t-1`} size={24} />);
    const el = container.querySelector("[data-testid=avatar]")!;
    expect(el.getAttribute("data-role-icon")).toBe(role);
    expect(el.querySelector("svg")).not.toBeNull();
    expect(seatRole(role)).toBe(role);
    expect(AGENT_AVATARS[role as keyof typeof AGENT_AVATARS]).toBeTruthy();
    expect(ICON_PATHS[ROLE_ICONS[role as keyof typeof ROLE_ICONS]]).toBeTruthy();
  });

  it.each([...HUMAN_ROLES])("%s is a person: the picture avatar, not a role glyph", (role) => {
    const { container } = render(<Avatar id={role} size={24} />);
    const el = container.querySelector("[data-testid=avatar]")!;
    expect(el.tagName).toBe("IMG");
    expect(el.getAttribute("data-role-icon")).toBeNull();
  });

  it.each(BOARD_ROLES)("%s has a label", (role) => {
    expect(glossLabel("role", role).length).toBeGreaterThan(0);
  });

  it("the doctor seat is called Help", () => {
    expect(roleLabel("doctor")).toBe("Help");
    expect(glossLabel("role", "doctor")).toBe("Help");
    expect(roleLabel("engineer")).toBe("engineer");
  });
});
