import path from "node:path";
import { defineConfig } from "@playwright/test";

// The site's product-guide screenshots (s-bcc0c06de7, owner m-67c4136530). Same private board and private SPA build
// as the e2e suite (e2e/globalSetup.ts, e2e/fixtures.ts): a throwaway board on a free port with a temp DB, seeded
// with a made-up team project (guide/demo.seed.ts). Nothing here reads the fleet board or anyone's real data.
//   npx playwright test -c playwright.guide.config.ts      -> docs/site/docs/assets/guide/*.png
const CHROMIUM =
  process.env.EDP8_CHROMIUM ??
  path.join(process.env.LOCALAPPDATA ?? "", "ms-playwright", "chromium-1234", "chrome-win64", "chrome.exe");

export default defineConfig({
  testDir: "./guide",
  workers: 1,
  fullyParallel: false,
  reporter: [["list"]],
  timeout: 120_000,
  globalSetup: "./e2e/globalSetup.ts",
  globalTeardown: "./e2e/globalTeardown.ts",
  use: {
    baseURL: process.env.EDP8_E2E_BASE,
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
    launchOptions: { executablePath: CHROMIUM },
  },
});
