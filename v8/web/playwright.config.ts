import path from "node:path";
import { defineConfig } from "@playwright/test";

// SEAM (pinned chromium). Pool shells set PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 and cannot
// download browsers, so we point at an already-installed build. @playwright/test 1.62.0
// ships chromium build 1234, which is present in %LOCALAPPDATA%\ms-playwright. The exe
// dir is `chrome-win64` (not `chrome-win`). Override with EDP8_CHROMIUM if a newer build
// was installed. (LL §9.2 / design §4.4c.)
const CHROMIUM =
  process.env.EDP8_CHROMIUM ??
  path.join(process.env.LOCALAPPDATA ?? "", "ms-playwright", "chromium-1234", "chrome-win64", "chrome.exe");

export default defineConfig({
  testDir: "./e2e",
  workers: 1, // one board, one worker — the fixture spawns a single shared board
  fullyParallel: false,
  reporter: [["list"]],
  timeout: 30_000,
  globalSetup: "./e2e/globalSetup.ts",
  globalTeardown: "./e2e/globalTeardown.ts",
  use: {
    // baseURL is injected at runtime by globalSetup (the port is chosen there).
    baseURL: process.env.EDP8_E2E_BASE,
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
    launchOptions: { executablePath: CHROMIUM },
  },
});
