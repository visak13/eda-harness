// One command for every render (npm run render:all):
//   out/heronry-demo.mp4   Main, 1920x1080, h264 + aac
//   out/hero.webp, out/hero.gif   the Hero loop (1200x630, 7 s), from out/hero.mp4 via ffmpeg
//   out/poster.png, out/stills/readme-*.png   (scripts/stills.mjs)
// One bundle, one render at a time (concurrency 1): the host this was built on is short of RAM.
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { bundle } from "@remotion/bundler";
import { renderMedia, selectComposition } from "@remotion/renderer";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = (f) => path.join(root, "out", f);
const concurrency = Number(process.env.RENDER_CONCURRENCY ?? 1);

const serveUrl = await bundle({ entryPoint: path.join(root, "src/index.ts") });

for (const [id, file] of [["Main", "heronry-demo.mp4"], ["Hero", "hero.mp4"]]) {
  const composition = await selectComposition({ serveUrl, id });
  let last = -1;
  await renderMedia({
    composition, serveUrl, codec: "h264", outputLocation: out(file), concurrency, crf: 18,
    onProgress: ({ progress }) => {
      const pct = Math.floor(progress * 10) * 10;
      if (pct !== last) { last = pct; console.log(`${file} ${pct}%`); }
    },
  });
}

// The hero loop for the README: animated webp (small, sharp) and a gif fallback (palette pass).
const ff = (args) => execFileSync("ffmpeg", ["-v", "error", "-y", ...args], { stdio: "inherit" });
ff(["-i", out("hero.mp4"), "-vf", "fps=20,scale=900:-1:flags=lanczos", "-loop", "0", "-quality", "80",
  "-compression_level", "6", out("hero.webp")]);
ff(["-i", out("hero.mp4"), "-vf",
  "fps=15,scale=720:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96[p];[b][p]paletteuse=dither=bayer:bayer_scale=4",
  "-loop", "0", out("hero.gif")]);

execFileSync(process.execPath, [path.join(root, "scripts/stills.mjs")], { stdio: "inherit" });
console.log("done: out/heronry-demo.mp4, out/hero.webp, out/hero.gif, out/poster.png, out/stills/");
