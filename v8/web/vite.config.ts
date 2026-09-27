/// <reference types="vitest/config" />
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { execSync } from "node:child_process";

// SEAM (serve-under-prefix): the built bundle is mounted by FastAPI (serve.py::mount_spa).
// `base` MUST equal the mount prefix so the emitted asset URLs resolve against StaticFiles,
// and so a deep link like `/ui/x/y` (served index.html by the SPA catch-all) still finds them.
// Post-cutover (S12) the SPA owns `/ui` under EDP8_UI=folio (the default), so `base` is `/ui/`.
// `main.tsx` derives the react-router basename from import.meta.env.BASE_URL, so this one knob
// moves both. Build with EDP8_WEB_BASE=/app/ only for the legacy-mode SPA mount at /app.
const BASE = process.env.EDP8_WEB_BASE ?? "/ui/";

// Dev proxy: `vite dev` serves the SPA at BASE and forwards the board's real
// endpoints to the running board on :9400 (no CORS — same-origin in prod).
const target = process.env.EDP8_BOARD_URL ?? "http://127.0.0.1:9400";

// t-b2f8859d30: the build stamps where it came from, so the SPA can tell when it runs ahead of the board
// (src/live/boardVersion.ts). rev = HEAD; dirty = uncommitted changes under v8/ at build time; at = build time.
function git(args: string): string {
  try {
    return execSync(`git ${args}`, { cwd: "..", stdio: ["ignore", "pipe", "ignore"] }).toString().trim();
  } catch {
    return "";
  }
}
const BUILD = { rev: git("rev-parse --short=7 HEAD") || "unknown", dirty: git("status --porcelain -- .") !== "", at: new Date().toISOString() };

// t-b2f8859d30: only the deploy (edp.ps1 update, CI) writes the shared dist the fleet board serves. A seat or e2e
// build sets EDP8_WEB_OUT to a private dir (web/e2e/distDir.ts) and points its own board at it (EDP8_WEB_DIST).
const OUT = process.env.EDP8_WEB_OUT || "../src/edp8/webapp/dist";

export default defineConfig({
  base: BASE,
  plugins: [react()],
  define: { __EDP_BUILD__: JSON.stringify(BUILD) },
  server: {
    proxy: {
      "/v1": { target, changeOrigin: true },
      "/ui/poll": { target, changeOrigin: true },
      "/healthz": { target, changeOrigin: true },
    },
  },
  build: {
    // → v8/src/edp8/webapp/dist (gitignored, hatch force-included into the wheel), or EDP8_WEB_OUT
    outDir: OUT,
    emptyOutDir: true,
  },
  // Vitest (unit) runs only src/*.test.* under jsdom. The Playwright e2e/visual specs are a
  // SEPARATE runner (`npm run e2e`, win32-only) and MUST be excluded here so `npm test` (and
  // the Linux CI job) never tries to collect them (design §4.4, S17 CI criterion).
  test: {
    // S22 host hygiene: a seat's shell is a PTY, so a bare `vitest` / `npm test` started WATCH mode and never
    // exited — one outlived its closed seat for 2 h at 85% of a core. Run once; `vitest --watch` still watches.
    watch: false,
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    exclude: ["e2e/**", "node_modules/**", "dist/**"],
    coverage: {
      provider: "v8",
      thresholds: { lines: 80, branches: 80 },
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.{test,spec}.{ts,tsx}", "src/test/**", "src/main.tsx"],
    },
  },
});
