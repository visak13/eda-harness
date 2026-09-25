import fs from "node:fs";
import path from "node:path";
import { expect, test, BASE } from "./fixtures";
import { REPO_DIR } from "./board";

// epic-91fcd3b370 S3 (c-15095a23a0): with the code service stopped, /ui/code says so and names the
// start command — never a blank frame. This file's board points EDP_CODE_PORT at port 9 (discard),
// which has no listener on this host, so the board's real /healthz probe fails exactly as it does
// for a stopped service (a separate file: boardEnv is a per-file worker option).
test.use({ boardFile: "code-tab-down", boardEnv: { EDP_CODE_PORT: "9" } });

const SHOTS = path.join(REPO_DIR, "web", "e2e", "evidence", "code-tab");
const as = "as=owner";

test.describe("code service down", () => {
  test("says the service is not running, names the start command, and shows no frame", async ({ page }) => {
    fs.mkdirSync(SHOTS, { recursive: true });
    await page.goto(`/ui/code?${as}`, { waitUntil: "load" });
    const down = page.getByTestId("code-down");
    await expect(down).toBeVisible({ timeout: 15_000 });
    await expect(down).toContainText("Code service is not running");
    await expect(page.getByTestId("code-start-command")).toHaveText(".\\edp.ps1 start code");
    await expect(page.getByTestId("code-frame")).toHaveCount(0);
    await expect(page.getByTestId("code-faq")).toHaveAttribute("href", "/ui/code/faq");
    const res = await page.request.get(`${BASE()}/v1/code`, { headers: { "X-Participant": "owner" } });
    expect((await res.json()).value).toMatchObject({ port: 9, running: false });
    await page.screenshot({ path: path.join(SHOTS, "code-tab-down.png") });
  });
});
