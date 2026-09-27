# The Heronry product video

A 78-second [Remotion](https://www.remotion.dev) composition in seven chapters: the pool, the broker,
reactive wakes, context engineering, the self-improving memory loop, one epic walking the board, and
the close. Every frame is drawn in code in the Heronry palette; nothing is a screenshot.

> **Licence note.** Remotion is free for individuals and companies of 3 or fewer people; larger
> companies need a Remotion company licence. See [CREDITS.md](CREDITS.md) for the music (CC0), fonts and art.

## Render
Needs Node 20+ and `ffmpeg` on PATH (for the webp/gif loop). Remotion downloads its own headless Chrome
on the first render.

```sh
npm ci
npm run render:all     # out/heronry-demo.mp4, out/hero.webp, out/hero.gif, out/poster.png, out/stills/
npm run studio         # edit live in Remotion Studio
npm run storyboard     # one still per chapter in out/storyboard/
```

Renders go to `out/` (git-ignored). Large renders are attached to the GitHub Release, not committed.

## Play it live
`player/` is a small page that plays the same `Main` composition through `@remotion/player`
(no video file needed). The project site plays the rendered MP4 in an HTML5 player instead.

```sh
npm run player:build   # static page in player/dist/
```

## Layout
- `src/Main.tsx` — the chapter list and lengths; `src/chapters/Ch*.tsx` — one file per chapter, each
  headed by the code it depicts; `src/Hero.tsx` — the README loop; `src/components/kit.tsx` — shared parts.
- `scripts/render-all.mjs`, `scripts/stills.mjs` — the render commands.
- `scripts/code-facts.mjs` — reads the numbers the captions state from the code (the context() budget
  from `v8/src/edp8/bundles.py` and the settings registry) into `src/code-facts.json`; both render
  commands run it first and fail if the code moved.
