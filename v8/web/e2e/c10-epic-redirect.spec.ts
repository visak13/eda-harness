import { expect, test, BASE } from "./fixtures";
import { seedEpic, type G3aFixture } from "./g3a.seed";

test.use({ boardFile: "c10-epic-redirect" }); // one fresh board per spec file (fixtures.ts)

// C10 (s-e1cec79882, design-10b21760d9 §13): the VS Code chat's "open on board" link built
// /ui/ticket/<epic id> and landed on the story view (owner screenshot art-c42c656c54). The ticket
// page now REPLACES itself with /ui/epic/<id>, keeping the query and the #m- anchor; a story stays.

let fx: G3aFixture;
let note: string;

test.beforeAll(async () => {
  fx = await seedEpic();
  const r = await fetch(`${BASE()}/v1/messages`, {
    method: "POST",
    headers: { "content-type": "application/json", "X-Participant": "owner" },
    body: JSON.stringify({ ticket_id: fx.epic, kind: "note", text: "C10 anchor target" }),
  });
  note = ((await r.json()) as { value: { id: string } }).value.id;
});

test("/ui/ticket/<epic id>?as=owner#m-… lands on /ui/epic/<id> with query and anchor, by replace", async ({ page }) => {
  await page.goto(`${BASE()}/ui/library/tickets?as=owner`, { waitUntil: "load" });
  await page.goto(`${BASE()}/ui/ticket/${fx.epic}?as=owner#${note}`, { waitUntil: "load" });

  await page.waitForURL(`**/ui/epic/${fx.epic}**`);
  await expect(page.getByText("One epic: its goal, its work, and what needs a decision.")).toBeVisible(); // the epic page's lede
  const url = new URL(page.url());
  expect(url.pathname).toBe(`/ui/epic/${fx.epic}`);
  expect(url.search).toBe("?as=owner");
  expect(url.hash).toBe(`#${note}`);
  await expect(page.getByText("C10 anchor target").first()).toBeVisible();

  // replace, not push: Back skips the /ui/ticket/ entry and returns to the page before it
  await page.goBack({ waitUntil: "load" });
  expect(new URL(page.url()).pathname).toBe("/ui/library/tickets");
  await page.screenshot({ path: "e2e/evidence/c10-epic-redirect.png" }).catch(() => {});
});

test("/ui/ticket/<story id> stays on the ticket view", async ({ page }) => {
  await page.goto(`${BASE()}/ui/ticket/${fx.story}?as=owner`, { waitUntil: "load" });
  await expect(page.getByTestId("status-chip").filter({ visible: true }).first()).toBeVisible();
  expect(new URL(page.url()).pathname).toBe(`/ui/ticket/${fx.story}`);
});
