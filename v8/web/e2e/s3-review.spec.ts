import { test, expect, BASE } from "./fixtures";
import AxeBuilder from "@axe-core/playwright";
import { THEMES } from "../src/theme/themes";
test.use({ boardFile: "s3-review" });
test("source deep link, local feedback, optional tab context and exact-version approval", async ({ page, request, context }) => {
  async function post(path: string, data: unknown, actor = "arch", method = "POST") {
    const res = await request.fetch(`${BASE()}${path}`, { method, headers: { "X-Participant": actor }, data });
    expect(res.ok(), await res.text()).toBe(true);
    return (await res.json()).value;
  }
  const epic = await post("/v1/tickets", { kind: "epic", work_type: "feature", title: "Review workflow" }, "owner");
  const doc = await post("/v1/docs", { doc_type: "design", title: "Conversation-first workflow", scope: epic.id, body_md: "# Keep the work together\n\nReview the exact document you can see.\n\n## Feedback stays local\n\nDiscuss the work without leaving the source conversation." });
  await post(`/v1/docs/${doc.id}`, { body_md: "# Keep the work together\n\nReview the exact version.\n\n## Feedback stays local\n\nAttachments stay with the draft." }, "arch", "PATCH");
  await post("/v1/criteria", { ticket_id: epic.id, text: "Review works", check: "command" });
  await post(`/v1/tickets/${epic.id}`, { design_ref: doc.id }, "arch", "PATCH");
  const gate = await post(`/v1/gates/${epic.id}/design_signoff/open`, { note: "Review requested" });
  await page.goto(`/ui/epic/${epic.id}?as=owner&request=${gate.id}`);
  const dialog = page.getByRole("dialog", { name: "Design", exact: true });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("heading", { name: "Conversation-first workflow", exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "Request changes", exact: true }).click();
  await dialog.getByRole("textbox", { name: "Message" }).fill("Please clarify how stale versions behave.");
  await expect(dialog.getByRole("button", { name: "Approve design" })).toBeDisabled();
  let release!: () => void;
  const hold = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/v1/artifacts/upload", async (route) => { await hold; await route.continue(); });
  await dialog.locator('input[type="file"]').setInputFiles("e2e/evidence/s3-new-epic-320.png");
  await expect(dialog.getByText(/Uploading 1 attachment/)).toBeVisible();
  await expect(dialog.getByTestId("composer-expand")).toBeDisabled();
  await dialog.getByRole("link", { name: /Back to source/ }).click();
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Versions", { exact: true }).locator("summary").click();
  await dialog.getByTestId("version-entry").first().click();
  await expect(dialog.getByTestId("version-now")).toContainText("v2");
  await page.keyboard.press("Escape"); await expect(dialog).toBeVisible();
  release();
  await expect(dialog.getByText(/Uploading 1 attachment/)).toHaveCount(0);
  // R1 stages an upload as a chip, not a raw art- token in the draft text (Composer §attachments).
  await expect(dialog.getByTestId("attachment-chip")).toHaveCount(1);
  await expect(dialog.getByRole("textbox", { name: "Message" })).toHaveValue("Please clarify how stale versions behave.");
  await expect(dialog.getByText("Wait for the pending upload or send before closing. Your draft is kept.")).toHaveCount(0);
  await dialog.getByLabel("Versions", { exact: true }).locator("summary").click();
  // @ts-expect-error shared axe adapter has dual playwright-core types
  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
  await page.screenshot({ path: "e2e/evidence/s3-review.png" });
  for (const theme of THEMES) {
    await page.evaluate((id) => { document.documentElement.dataset.theme = id; localStorage.setItem("edp8.theme", id); }, theme.id);
    for (const [width, height] of [[1440, 900], [320, 568], [844, 390]]) {
      await page.setViewportSize({ width, height });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await dialog.getByRole("button", { name: "Send", exact: true }).click({ trial: true });
      // @ts-expect-error shared axe adapter has dual playwright-core types
      const audit = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
      expect(audit.violations.filter((v) => v.impact === "serious" || v.impact === "critical"), `${theme.id}/${width}`).toEqual([]);
    }
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  const sent = page.waitForResponse((res) => res.url().endsWith("/v1/gates/decide"));
  await dialog.getByRole("button", { name: "Send", exact: true }).click();
  expect((await (await sent).json()).value.decision).toBe("request_changes");
  await expect(dialog.getByText(/Design remains unapproved/)).toBeVisible();
  const epicRecord = await request.get(`${BASE()}/v1/tickets/${epic.id}`, { headers: { "X-Participant": "owner" } });
  expect((await epicRecord.json()).value.status).toBe("designed");
  const tabPromise = context.waitForEvent("page");
  await dialog.getByRole("link", { name: "Open in tab" }).click();
  const tab = await tabPromise;
  await expect(tab).toHaveURL(new RegExp(`source=${epic.id}.*request=${gate.id}`));
  await expect(tab.getByRole("button", { name: "Approve design" })).toBeVisible();
  await tab.getByRole("button", { name: "Approve design" }).click();
  await expect(tab.getByText("Design approved at v2.")).toBeVisible();
  await tab.close();
});
