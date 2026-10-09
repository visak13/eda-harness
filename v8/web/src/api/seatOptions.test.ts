import { describe, it, expect } from "vitest";
import {
  choiceFromTags, epicChoiceTags, optionToken, parseOptionToken, roleOptionsFromTags, storyPicksFromTags,
  withChoiceTags, withStoryPick,
} from "./endpoints";

// S7: the SPA's mirror of edp8/seat_choice option-list and story-pick tags.

describe("seat option tags", () => {
  it("splits the effort at the last @, so a [1m] id survives", () => {
    expect(parseOptionToken("claude-sonnet-5-5[1m]@high")).toEqual({ model: "claude-sonnet-5-5[1m]", effort: "high" });
    expect(parseOptionToken("gpt-6-sol")).toEqual({ model: "gpt-6-sol", effort: "" });
    expect(optionToken({ model: "gpt-6-sol", effort: "medium" })).toBe("gpt-6-sol@medium");
    expect(optionToken({ model: "gpt-6-sol", effort: "" })).toBe("gpt-6-sol");
  });

  it("roundtrips a role's ordered list through its tag", () => {
    const tags = epicChoiceTags({
      roleModels: { engineer: "a" }, roleEfforts: { engineer: "low" },
      roleOptions: { engineer: [{ model: "a", effort: "high" }, { model: "b", effort: "medium" }] },
    });
    expect(tags).toEqual(["model:engineer=a@high|b@medium"]);
    expect(roleOptionsFromTags(tags)).toEqual({ engineer: [{ model: "a", effort: "high" }, { model: "b", effort: "medium" }] });
  });

  it("a role without a list keeps the legacy pair", () => {
    expect(epicChoiceTags({ roleModels: { qa: "x" }, roleEfforts: { qa: "medium" } }))
      .toEqual(["model:qa=x", "seat-effort:qa=medium"]);
  });

  it("choiceFromTags reads the first option, and its own effort wins", () => {
    const catalog = { roles: { engineer: ["a", "b"] }, defaults: { engineer: "a" } };
    expect(choiceFromTags(["model:engineer=b@high|a@low", "seat-effort:engineer=low"], catalog))
      .toEqual({ roleModels: { engineer: "b" }, roleEfforts: { engineer: "high" } });
  });

  it("a story pick is set, replaced and cleared without touching other tags; the epic rewrite keeps it", () => {
    const set = withStoryPick(["area:ui"], "engineer", { model: "b", effort: "medium" });
    expect(set).toEqual(["area:ui", "seat:engineer=b@medium"]);
    expect(storyPicksFromTags(set)).toEqual({ engineer: { model: "b", effort: "medium" } });
    expect(withStoryPick(set, "engineer", { model: "a", effort: "low" })).toEqual(["area:ui", "seat:engineer=a@low"]);
    expect(withStoryPick(set, "engineer", null)).toEqual(["area:ui"]);
    expect(withChoiceTags(set, { roleModels: {}, roleEfforts: {} })).toEqual(set);
  });
});
