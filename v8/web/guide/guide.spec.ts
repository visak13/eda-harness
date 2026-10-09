// The site's product-guide screenshots (s-bcc0c06de7, owner m-67c4136530): the Tidewater demo project (demo.seed.ts)
// on this run's private board, photographed screen by screen into docs/site/docs/assets/guide/ (GUIDE_OUT overrides).
//   npx playwright test -c playwright.guide.config.ts
import fs from "node:fs";
import path from "node:path";
import type { Page } from "@playwright/test";
import { REPO_DIR } from "../e2e/board";
import { BASE, expect, test } from "../e2e/fixtures";
import { makeArt } from "./art";
import { seedDemo, type Demo } from "./demo.seed";

const OUT = process.env.GUIDE_OUT ?? path.join(REPO_DIR, "..", "docs", "site", "docs", "assets", "guide");

test.use({ boardFile: "guide" });
test.describe.configure({ mode: "default" });

let demo: Demo;

async function shot(page: Page, name: string, opts: { fullPage?: boolean } = {}): Promise<void> {
  fs.mkdirSync(OUT, { recursive: true });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(1200); // the board polls live, so the network is never idle
  await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: opts.fullPage ?? false });
}

const url = (p: string, who = "maya") => `${BASE()}/ui/${p}${p.includes("?") ? "&" : "?"}as=${who}`;

test.beforeAll(async () => {
  demo = await seedDemo(await makeArt());
});

/** The thread with the composer folded away, scrolled so `text`'s message is in view. */
async function thread(page: Page, ticket: string, who = "maya"): Promise<void> {
  await page.goto(url(`ticket/${ticket}`, who));
  await expect(page.getByTestId("thread")).toBeVisible();
  const fold = page.getByTestId("composer-collapse");
  if (await fold.isVisible().catch(() => false)) await fold.click();
}
const message = (page: Page, text: string) => page.getByTestId("thread-message").filter({ hasText: text }).first();

async function elementShot(page: Page, loc: ReturnType<Page["locator"]>, name: string): Promise<void> {
  fs.mkdirSync(OUT, { recursive: true });
  await loc.scrollIntoViewIfNeeded();
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(800);
  await loc.screenshot({ path: path.join(OUT, `${name}.png`) });
}

test("epics and the epic page", async ({ page }) => {
  await page.goto(url("epics"));
  await expect(page.getByText("Make Tidewater work offline")).toBeVisible();
  await shot(page, "epics");
  await page.goto(url(`ticket/${demo.epic}`));
  await expect(page.getByTestId("thread")).toBeVisible();
  await shot(page, "epic-page");
});

test("a conversation: an ask, an answer that quotes it, a status", async ({ page }) => {
  await thread(page, demo.epic);
  await elementShot(page, message(page, "Go with (b)"), "reply-with-quote");
  await elementShot(page, page.locator(`[id="${demo.question}"]`), "question-from-architect");
});

test("three quotes in one message: another seat, the design and the code", async ({ page }) => {
  await thread(page, demo.stories.tombstones);
  await elementShot(page, page.locator(`[id="${demo.quoted}"]`), "quotes-three-sources");
});

test("select any passage to quote it", async ({ page }) => {
  await thread(page, demo.stories.merge);
  const msg = message(page, "S2's merge is in");
  await msg.scrollIntoViewIfNeeded();
  await page.evaluate((needle) => {
    const root = [...document.querySelectorAll("[data-testid=thread-message]")].find((n) => n.textContent?.includes(needle))!;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const at = (n as Text).data.indexOf(needle);
      if (at >= 0) {
        const r = document.createRange();
        r.setStart(n, at);
        r.setEnd(n, at + needle.length);
        const sel = window.getSelection()!;
        sel.removeAllRanges();
        sel.addRange(r);
        break;
      }
    }
    document.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
  }, "a same-paragraph clash comes back as a conflict");
  const pop = page.getByTestId("quote-popover");
  await expect(pop).toBeVisible();
  await pop.getByTestId("quote-note").click();
  await page.keyboard.type("Does this hold for a deleted paragraph too?");
  await shot(page, "quote-select");
});

test("attachments: a guest's phone screenshot and a seat's recording", async ({ page }) => {
  await thread(page, demo.epic);
  const img = message(page, "Checked on my phone in Tokyo");
  await expect(img.locator("img").first()).toBeVisible();
  await elementShot(page, img, "attachment-image");
  await thread(page, demo.stories.tombstones);
  const vid = message(page, "Fixed: the merge now checks");
  const video = vid.locator("video").first();
  await expect(video).toBeVisible();
  // play to the end state (the recording has no seek index), then pause on it
  await video.evaluate(async (v: HTMLVideoElement) => {
    v.muted = true;
    await v.play();
    await new Promise((r) => setTimeout(r, 3400));
    v.pause();
  });
  await elementShot(page, vid, "attachment-video");
});

test("the Work drawer", async ({ page }) => {
  await page.goto(url(`ticket/${demo.epic}`));
  await page.getByTestId("work-work").click();
  await expect(page.getByTestId("drawer-panel")).toBeVisible();
  await shot(page, "work-drawer");
  const tree = page.getByTestId("work-tree");
  await tree.scrollIntoViewIfNeeded();
  await shot(page, "work-stories");
});

test("the design opens beside the conversation", async ({ page }) => {
  await page.goto(url(`ticket/${demo.epic}?doc=${demo.design}`));
  await expect(page.getByTestId("doc-body")).toContainText("Conflict rule");
  await shot(page, "design-drawer");
});

test("the composer: who it goes to, what kind, @mentions", async ({ page }) => {
  await page.goto(url(`ticket/${demo.epic}`));
  await page.getByTestId("composer-text").click();
  // "@a" narrows to people and seats (the unfiltered list also carries the test harness's own sign-ins)
  await page.keyboard.type("@a");
  await expect(page.getByTestId("mentions-menu")).toBeVisible();
  await shot(page, "composer-mention");
});

test("the composer: $ links a story, doc or file", async ({ page }) => {
  await page.goto(url(`ticket/${demo.epic}`));
  await page.getByTestId("composer-text").click();
  await page.keyboard.type("The fix is in $me");
  await expect(page.getByTestId("refs-menu")).toBeVisible();
  await expect(page.getByTestId("refs-menu").getByRole("option").first()).toBeVisible();
  await shot(page, "composer-refs");
});

test("find anything", async ({ page }) => {
  await page.goto(url(`ticket/${demo.epic}`));
  await page.getByTestId("find-open").click();
  await page.getByTestId("find-input").fill("tombstone");
  await expect(page.getByTestId("find-row").first()).toBeVisible();
  await shot(page, "find");
});

test("seats", async ({ page }) => {
  await page.goto(url("seats"));
  await page.waitForTimeout(500);
  await shot(page, "seats");
});

test("a guest teammate sees only the epics they are added to", async ({ page }) => {
  await page.goto(url(`ticket/${demo.epic}`, "kenji"));
  await expect(page.getByTestId("thread")).toBeVisible();
  await shot(page, "guest-view");
});

test.describe("on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true });
  test("the conversation on a phone", async ({ page }) => {
    await thread(page, demo.epic);
    await page.getByRole("heading", { name: "Conversation" }).evaluate((h) => h.scrollIntoView({ block: "start" }));
    await shot(page, "phone-thread");
  });
});
