import fs from "node:fs";
import path from "node:path";
import { expect, test, BASE } from "./fixtures";
import { REPO_DIR } from "./board";
import { e2eDist, sharedDist } from "./distDir";

test.use({ boardFile: "private-dist" }); // one fresh board per spec file (fixtures.ts)

// t-b2f8859d30 (owner art-678346d6e2): the spec board serves the PRIVATE e2e build (globalSetup → EDP8_WEB_OUT,
// board → EDP8_WEB_DIST), and the run never touches the shared src/edp8/webapp/dist the fleet board serves.

test("the e2e board serves the private dist, and the shared dist is untouched by the run", async ({ page }) => {
  const privateIndex = path.join(e2eDist(REPO_DIR), "index.html");
  const html = fs.readFileSync(privateIndex, "utf8");
  const bundle = /\/ui\/assets\/index-[\w-]+\.js/.exec(html)?.[0];
  expect(bundle, "the private build names its entry bundle").toBeTruthy();

  const served = await (await fetch(`${BASE()}/ui/epics`)).text();
  expect(served).toContain(bundle!); // the board's index.html is the private build's
  expect((await fetch(`${BASE()}${bundle}`)).status).toBe(200);

  const shared = path.join(sharedDist(REPO_DIR), "index.html");
  const now = fs.existsSync(shared) ? String(fs.statSync(shared).mtimeMs) : "absent";
  expect(now, "shared dist mtime before (globalSetup) vs after the build and board start").toBe(process.env.EDP8_E2E_SHARED_MTIME);

  // and the page it serves runs (the private bundle mounts the shell)
  await page.goto(`${BASE()}/ui/epics?as=owner`);
  await expect(page.getByTestId("page-framing")).toBeVisible();
});
