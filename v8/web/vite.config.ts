import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// SEAM (serve-under-prefix): the built bundle is mounted by FastAPI at `/app`
// (src/edp8/webapp/serve.py::mount_spa). `base` MUST equal the mount prefix so the
// emitted asset URLs (`/app/assets/*`) resolve against StaticFiles, and so a deep
// link like `/app/x/y` (served index.html by the SPA catch-all) still finds them.
// When the /ui cutover happens (later story) this base moves to `/ui/`.
const BASE = process.env.EDP8_WEB_BASE ?? "/app/";

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
});
