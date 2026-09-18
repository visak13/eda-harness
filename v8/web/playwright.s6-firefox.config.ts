// Focused S6 engine check using the already-installed automation Firefox; not native toast proof.
import path from "node:path";
import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

export default defineConfig({
  ...base,
  testMatch: "s6-usage.spec.ts",
  use: { ...base.use, browserName: "firefox", launchOptions: {
    executablePath: path.join(process.env.LOCALAPPDATA ?? "", "ms-playwright", "firefox-1538", "firefox", "firefox.exe"),
  } },
});
