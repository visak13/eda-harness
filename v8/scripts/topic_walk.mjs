// S-SME-SURFACE (s-698224fca8) Library screenshots for scripts/topic_walk.py. Private board only.
//
//   node scripts/topic_walk.mjs before <board-base-url> <out-dir>
//   node scripts/topic_walk.mjs after  <board-base-url> <out-dir> <topic-id> <expert-link>
//
// `before`: the Library as it was (Knowledge, no topics). `after`: the owner's Topics list and Open topic
// dialog, the topic page (docs, thread, experts, seat, tags with who set them), an owner tag edit, and the
// same page seen through the expert's one-time link (topic routes only).
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(here, "..", "web", "package.json"));
const { chromium } = require("playwright");

const [mode, base, out, topic, expertLink] = process.argv.slice(2);
const as = `as=owner&token=${encodeURIComponent(process.env.WALK_OWNER_TOKEN ?? "")}`; // the private board is in token mode
if (!["before", "after"].includes(mode) || !base || !out || (mode === "after" && (!topic || !expertLink))) {
  console.error("usage: node scripts/topic_walk.mjs before|after <base-url> <out-dir> [<topic-id> <expert-link>]");
  process.exit(2);
}
const browser = await chromium.launch();
try {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  const shot = async (name) => {
    await page.waitForTimeout(700);
    await page.screenshot({ path: path.join(out, `${name}.png`) });
    console.log(`shot ${name}.png`);
  };
  if (mode === "before") {
    await page.goto(`${base}/ui/library/knowledge?${as}`);
    await page.getByTestId("knowledge").waitFor();
    await shot("before-01-library-knowledge");
  } else {
    await page.goto(`${base}/ui/library/topics?${as}`);
    await page.getByTestId("topics").waitFor();
    await shot("after-01-library-topics");
    await page.getByTestId("topic-open-button").click();
    await page.getByTestId("topic-open-dialog").waitFor();
    await shot("after-02-open-topic-dialog");
    await page.keyboard.press("Escape");
    await page.goto(`${base}/ui/library/topics/${topic}?${as}`);
    await page.getByTestId("topic-page").waitFor();
    await page.getByTestId("topic-thread").waitFor();
    console.log(`tags: ${(await page.getByTestId("topic-tags").innerText()).replace(/\s+/g, " ")}`);
    await shot("after-03-topic-page-owner");
    // the owner edits the tag list the sme set
    await page.getByTestId("topic-tags-edit").click();
    const input = page.getByTestId("topic-tags-input");
    await input.fill(`${await input.inputValue()}, owner-picked`);
    await page.getByTestId("topic-tags-save").click();
    await page.getByTestId("topic-tags-by").filter({ hasText: "owner" }).waitFor();
    console.log(`tags after owner edit: ${(await page.getByTestId("topic-tags").innerText()).replace(/\s+/g, " ")}`);
    await shot("after-04-owner-edited-tags");
    // the expert's view: a fresh context, only the one-time link
    const ectx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
    const epage = await ectx.newPage();
    await epage.goto(`${base}${expertLink}`);
    await epage.getByTestId("topic-page").waitFor();
    await epage.getByTestId("topic-thread").waitFor();
    await epage.waitForTimeout(700);
    await epage.screenshot({ path: path.join(out, "after-05-expert-view.png") });
    console.log("shot after-05-expert-view.png");
    await ectx.close();
  }
} finally {
  await browser.close();
}
