// S9 guard G2: a mangled EDP8_WEB_BASE fails the build instead of blanking the shared SPA.
import { describe, expect, it } from "vitest";
import { resolveBase } from "../../viteBase";

describe("resolveBase", () => {
  it("defaults to /ui/ and accepts URL paths", () => {
    expect(resolveBase(undefined)).toBe("/ui/");
    expect(resolveBase("/app/")).toBe("/app/");
    expect(resolveBase("/")).toBe("/");
    expect(resolveBase("/a/b.c-d_e/")).toBe("/a/b.c-d_e/");
  });

  it.each(["C:/Program Files/Git/ui/", ["C:", "Program Files", "Git", "ui"].join(String.fromCharCode(92)), "ui/", "/ui", "", "/ui//", "https://x/ui/"])(
    "refuses %j and says to build from PowerShell",
    (bad) => {
      expect(() => resolveBase(bad)).toThrow(/is not a URL path.*build from PowerShell/);
    },
  );
});
