// Renders stills from the Main composition with one bundle.
//   node scripts/stills.mjs               → out/stills/readme-{1,2,3}.png + out/poster.png
//   node scripts/stills.mjs --storyboard  → out/storyboard/ch{1..7}.png (one frame per chapter)
import path from "node:path";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { bundle } from "@remotion/bundler";
import { renderStill, selectComposition } from "@remotion/renderer";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const FPS = 30;
// chapter lengths in frames, as in src/Main.tsx CHAPTERS
const LENGTHS = [360, 330, 345, 375, 360, 405, 210];
const start = (i) => LENGTHS.slice(0, i).reduce((a, b) => a + b, 0);
// the local frame inside each chapter that shows the most of it
const KEY = [300, 290, 250, 330, 300, 330, 150];

const storyboard = process.argv.includes("--storyboard");
const shots = storyboard
  ? KEY.map((f, i) => ({ file: `out/storyboard/ch${i + 1}.png`, frame: start(i) + f }))
  : [
      { file: "out/poster.png", frame: start(6) + KEY[6] },
      { file: "out/stills/readme-1-pool.png", frame: start(0) + KEY[0] },
      { file: "out/stills/readme-2-context.png", frame: start(3) + KEY[3] },
      { file: "out/stills/readme-3-board.png", frame: start(5) + KEY[5] },
    ];

const serveUrl = await bundle({ entryPoint: path.join(root, "src/index.ts") });
const composition = await selectComposition({ serveUrl, id: "Main" });
for (const s of shots) {
  const out = path.join(root, s.file);
  mkdirSync(path.dirname(out), { recursive: true });
  await renderStill({ composition, serveUrl, output: out, frame: s.frame });
  console.log(`${s.file}  frame ${s.frame} (${(s.frame / FPS).toFixed(1)} s)`);
}
