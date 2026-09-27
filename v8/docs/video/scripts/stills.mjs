// Renders stills from the Main composition with one bundle.
//   node scripts/stills.mjs               → out/stills/readme-{1,2,3}.png + out/poster.png
//   node scripts/stills.mjs --storyboard  → out/storyboard/<id>.png per chapter, plus <id>-open.png (the illustration beat)
import path from "node:path";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import { bundle } from "@remotion/bundler";
import { renderStill, selectComposition } from "@remotion/renderer";
import { readFileSync } from "node:fs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const FPS = 30;
// chapter lengths and the local frame that shows the most of each (src/chapters.json, shared with Main)
const TABLE = JSON.parse(readFileSync(path.join(root, "src/chapters.json"), "utf8"));
const start = (i) => TABLE.slice(0, i).reduce((a, c) => a + c.frames, 0);
const at = (id) => { const i = TABLE.findIndex((c) => c.id === id); return start(i) + TABLE[i].key; };

const storyboard = process.argv.includes("--storyboard");
const shots = storyboard
  ? TABLE.flatMap((c, i) => [
      // the opening beat (the chapter illustration, where there is one) and the key frame
      ...(c.art ? [{ file: `out/storyboard/${c.id}-open.png`, frame: start(i) + 30 }] : []),
      { file: `out/storyboard/${c.id}.png`, frame: at(c.id) },
    ])
  : [
      { file: "out/poster.png", frame: at("ch7") },
      { file: "out/stills/readme-1-pool.png", frame: at("ch1") },
      { file: "out/stills/readme-2-context.png", frame: at("ch4") },
      { file: "out/stills/readme-3-board.png", frame: at("ch6") },
    ];

// numbers the captions state come from the code (src/code-facts.json); refresh before bundling
execFileSync(process.execPath, [path.join(root, "scripts/code-facts.mjs")], { stdio: "inherit" });

const serveUrl = await bundle({ entryPoint: path.join(root, "src/index.ts") });
const composition = await selectComposition({ serveUrl, id: "Main" });
for (const s of shots) {
  const out = path.join(root, s.file);
  mkdirSync(path.dirname(out), { recursive: true });
  await renderStill({ composition, serveUrl, output: out, frame: s.frame });
  console.log(`${s.file}  frame ${s.frame} (${(s.frame / FPS).toFixed(1)} s)`);
}
