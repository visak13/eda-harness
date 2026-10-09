// e0cec S6 c-b049e44561: the Pains view (Library > Pains) lists the board's one pain store, filters by status and links
// a fixed pain to its commit and a ticketed one to its ticket. One-off evidence spec: run it alone, never the full suite.
import fs from "node:fs";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { BASE, EPIC, expect, test } from "./fixtures";

test.use({ boardFile: "pains-view", boardEnv: { EDP8_REPO: path.resolve("..", "..") }, viewport: { width: 1440, height: 900 } });
const out = path.resolve("e2e/evidence/s6-pains");
const H = { "content-type": "application/json", "X-Participant": "owner", "X-Admin": process.env.EDP8_ADMIN_TOKEN ?? "t" };
async function call(route: string, body: unknown) {
  const r = await fetch(BASE() + route, { method: "POST", headers: H, body: JSON.stringify(body) });
  const j = await r.json();
  if (!j.ok) throw new Error(route + " " + JSON.stringify(j));
  return j.value;
}
const pain = (area: string, symptom: string) => call("/v1/pains", { severity: "medium", area, symptom, expected: "it works", evidence: "seen in e2e" });

test("Pains view: default open list, status filter, commit and ticket links", async ({ page }) => {
  fs.mkdirSync(out, { recursive: true });
  await pain("tools", "doc_read drops proposed docs");
  const fixed = await pain("board", "a dead checker strands the criterion");
  const ticketed = await pain("tools", "artifact_upload refused");
  const dup = await pain("tools", "artifact_upload refused, again");
  // sweep #5: only a commit some remote-tracking ref holds links to GitHub; an unpushed sha is plain text
  const pushed = execFileSync("git", ["rev-list", "-1", "--remotes"], { encoding: "utf8" }).trim();
  await call(`/v1/pains/${fixed.id}/resolve`, { status: "fixed", commit: pushed });
  await call(`/v1/pains/${ticketed.id}/resolve`, { status: "ticket", ticket_id: EPIC() });
  await call(`/v1/pains/${dup.id}/resolve`, { status: "duplicate", dup_of: ticketed.id });

  await page.goto(`${BASE()}/ui/library/pains`);
  await expect(page.getByTestId("pains-view")).toBeVisible();
  await expect(page.getByTestId("pain-row")).toHaveCount(1);
  await page.screenshot({ path: path.join(out, "pains-open.png") });

  await page.getByTestId("pains-status").selectOption("all");
  await expect(page.getByTestId("pain-row")).toHaveCount(4);
  await expect(page.getByRole("link", { name: `commit ${pushed}` })).toBeVisible();
  await expect(page.getByRole("link", { name: EPIC() }).first()).toHaveAttribute("href", new RegExp(`/ticket/${EPIC()}$`));
  await expect(page.getByTestId("pain-row").filter({ hasText: `of ${ticketed.id}` })).toHaveCount(1);
  await page.screenshot({ path: path.join(out, "pains-all.png") });
});
