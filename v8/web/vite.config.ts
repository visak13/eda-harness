/// <reference types="vitest/config" />
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

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

export default defineConfig({
  base: BASE,
  plugins: [react()],
  server: {
    proxy: {
      "/v1": { target, changeOrigin: true },
      "/ui/poll": { target, changeOrigin: true },
      "/healthz": { target, changeOrigin: true },
    },
  },
  build: {
    // → v8/src/edp8/webapp/dist (gitignored, hatch force-included into the wheel)
    outDir: "../src/edp8/webapp/dist",
    emptyOutDir: true,
  },
  // Vitest (unit) runs only src/*.test.* under jsdom. The Playwright e2e/visual specs are a
  // SEPARATE runner (`npm run e2e`, win32-only) and MUST be excluded here so `npm test` (and
  // the Linux CI job) never tries to collect them (design §4.4, S17 CI criterion).
  test: {
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
