import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { clampEffort, effortCap, SeatPickRow } from "./SeatPicks";

// S12 (t-186b964fb1): caps and glyphs come from the catalog entry's metadata, never the model id.
const META = {
  "gpt-looking-but-claude": { harness: "claude", provider: "anthropic", effort_cap: "medium" },
  "claude-looking-but-pi": { harness: "pi", provider: "openrouter", effort_cap: null },
  "low-only": { harness: "pi", provider: "groq", effort_cap: "low" },
};

describe("SeatPicks effort caps from the catalog (S12)", () => {
  it("reads the cap from metadata, whatever the id says", () => {
    expect(effortCap("gpt-looking-but-claude", META)).toBe("medium");
    expect(effortCap("claude-looking-but-pi", META)).toBeNull();
    expect(clampEffort("gpt-looking-but-claude", "high", META)).toBe("medium");
    expect(clampEffort("claude-looking-but-pi", "high", META)).toBe("high");
    expect(clampEffort("low-only", "medium", META)).toBe("low");
    expect(clampEffort("claude-opus-5-5", "high", undefined)).toBe("high"); // undescribed = uncapped
  });

  it("disables efforts above the cap, names the harness and shows its glyph", () => {
    render(<>
      <SeatPickRow role="engineer" testIdPrefix="t" options={Object.keys(META)} meta={META} model="gpt-looking-but-claude" effort="high" onModel={() => {}} onEffort={() => {}} />
      <SeatPickRow role="qa" testIdPrefix="t" options={Object.keys(META)} meta={META} model="low-only" effort="medium" onModel={() => {}} onEffort={() => {}} />
      <SeatPickRow role="sme" testIdPrefix="t" options={Object.keys(META)} meta={META} model="claude-looking-but-pi" effort="high" onModel={() => {}} onEffort={() => {}} />
    </>);
    const eng = screen.getByTestId("t-effort-engineer") as HTMLSelectElement;
    expect(eng.value).toBe("medium");
    expect([...eng.options].filter((o) => o.disabled).map((o) => o.value)).toEqual(["high"]);
    expect(screen.getByTestId("t-cap-engineer")).toHaveTextContent("Claude: medium max");
    expect(screen.getByTestId("t-row-engineer").querySelector("[data-provider-icon='claude']")).not.toBeNull();
    expect(screen.getByTestId("t-cap-qa")).toHaveTextContent("Pi: low max");
    expect([...(screen.getByTestId("t-effort-qa") as HTMLSelectElement).options].filter((o) => o.disabled).map((o) => o.value)).toEqual(["medium", "high"]);
    expect(screen.getByTestId("t-cap-sme")).toHaveTextContent("");
    expect(screen.getByTestId("t-row-sme").querySelector("[data-provider-icon]")).toBeNull();
  });
});
