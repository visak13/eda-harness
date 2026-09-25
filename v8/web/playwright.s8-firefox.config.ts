// S8 (s-17c13096e5): the Code tab spec against the live gated guard, in the installed automation Firefox
// (the guard cookie is SameSite=Strict; Firefox partitions cookies by top-level site).
//   npx playwright test -c playwright.s8-firefox.config.ts
import path from "node:path";
import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

export default defineConfig({
  ...base,
  testMatch: "code-tab.spec.ts",
  use: { ...base.use, browserName: "firefox", launchOptions: {
    executablePath: path.join(process.env.LOCALAPPDATA ?? "", "ms-playwright", "firefox-1538", "firefox", "firefox.exe"),
  } },
});
