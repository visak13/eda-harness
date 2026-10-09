import { describe, it, expect } from "vitest";
import { roleLabel } from "./iconPaths";
import { roleLabel as designRoleLabel } from "../pages/design/model";

// S12-ui (owner m-839aa76c90): "Qa" and "Sme" read wrong; an acronym role keeps its capitals and every other role
// shows in title case, through this one helper (the Design pages fall back to it for a role with no label).
describe("roleLabel", () => {
  it("keeps acronyms in capitals and title-cases the rest", () => {
    expect(roleLabel("qa")).toBe("QA");
    expect(roleLabel("sme")).toBe("SME");
    expect(roleLabel("doctor")).toBe("Help");
    expect(roleLabel("architect")).toBe("Architect");
    expect(roleLabel("engineer")).toBe("Engineer");
    expect(roleLabel("release_manager")).toBe("Release Manager");
  });

  it("is what the Design pages show for a role without its own label", () => {
    expect(designRoleLabel({ id: "qa" } as never)).toBe("QA");
    expect(designRoleLabel({ id: "qa", label: "Quality" } as never)).toBe("Quality");
  });
});
