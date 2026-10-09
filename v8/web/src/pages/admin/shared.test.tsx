import { describe, expect, it } from "vitest";
import { BoardApiError } from "../../api/client";
import { ADMIN_ONLY, adminRefused, errorText } from "./shared";

// architect m-2da889e64a: the board's admin refusal names request headers; every admin panel shows one plain line instead.
describe("admin refusal text", () => {
  const refused = new BoardApiError(403, "", "admin routes need an admin human's X-Participant and X-Token");

  it("maps the 403 to the plain line, in the one place every panel reads", () => {
    expect(adminRefused(refused)).toBe(true);
    expect(errorText(refused)).toBe(ADMIN_ONLY);
    expect(errorText(refused)).not.toMatch(/X-Token|X-Participant/);
  });
  it("leaves every other board answer as the board said it", () => {
    const bad = new BoardApiError(400, "", "handle must be a slug");
    expect(adminRefused(bad)).toBe(false);
    expect(errorText(bad)).toBe("handle must be a slug");
  });
});
