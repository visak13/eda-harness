// Builds the live player page (player/main.tsx) into player/dist/: one esbuild bundle, the fonts
// beside it, and the public/ assets (art, brand, music) the compositions load through staticFile().
//   node scripts/player-build.mjs
import path from "node:path";
import { cpSync, mkdirSync, rmSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dist = path.join(root, "player/dist");
rmSync(dist, { recursive: true, force: true });
mkdirSync(dist, { recursive: true });

await build({
  entryPoints: { player: path.join(root, "player/main.tsx") },
  outdir: dist,
  bundle: true,
  format: "esm",
  minify: true,
  jsx: "automatic",
  target: "es2022",
  define: { "process.env.NODE_ENV": '"production"' },
  loader: { ".woff2": "file", ".woff": "file", ".png": "file" },
  assetNames: "assets/[name]-[hash]",
  logLevel: "warning",
});
cpSync(path.join(root, "player/index.html"), path.join(dist, "index.html"));
cpSync(path.join(root, "public"), dist, { recursive: true });
console.log(`player/dist ready — serve it statically (e.g. npx serve player/dist)`);
