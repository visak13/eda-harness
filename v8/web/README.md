# edp8 web (Folio SPA) — S1 walking skeleton

Vite + React 19 + TypeScript front-end for the edp8 board. S1 is a **spike**: the thinnest real
end-to-end thread through the five risky seams, on the production interfaces the later stories keep
(`src/auth/identity.ts`, `src/live/feed.ts`, `src/edp8/webapp/serve.py`). No Folio components yet.

> Design: `design-dc3a77cbc1` §4.1 (HLD), §4.4 (testing), §9 (risks). Craft bars: `strategyll-37c460a141`.

## Commands (run from `v8/`, never `cd` into `web/`)

| purpose | command |
|---|---|
| install (lockfile-exact) | `npm --prefix web ci` |
| install + update lock | `npm --prefix web install` |
| dev server (proxying a running board on :9400) | `npm --prefix web run dev` |
| production build → `../src/edp8/webapp/dist` | `npm --prefix web run build` |
| Playwright e2e | `npm --prefix web run e2e` |
| single e2e spec | `npm --prefix web run e2e -- e2e/spike.spec.ts` |

Backend serve + wheel + serve tests (from `v8/`):

```
npm --prefix web ci && npm --prefix web run build && uv run pytest -q tests/test_webapp_serve.py
uv build --wheel && python -m zipfile -l dist/edp8-*.whl | grep webapp/dist   # ships index.html
```

## Seam findings

### 1. Serve a Vite bundle from FastAPI under a prefix (`webapp/serve.py::mount_spa`)
- Vite `base` **must equal the mount prefix** so emitted asset URLs resolve. S1 mounts at `/app`, so
  `vite.config.ts` sets `base: "/app/"` (override via `EDP8_WEB_BASE`). The `/ui` cutover (later story)
  moves this to `/ui/`. A relative `base: "./"` breaks on deep SPA routes (catch-all serves `index.html`
  from a nested path) — use an absolute prefix.
- `build.outDir` is `../src/edp8/webapp/dist` so `npm run build` writes straight where `serve.py` and the
  wheel force-include expect it. `emptyOutDir: true` is required because outDir is outside the web root.
- `mount_spa` registers `{prefix}/assets` as `StaticFiles` (immutable cache) **before** the SPA catch-all,
  and is mounted in `service.create_app` **after** `ui_router` so `/ui/poll` and every `/v1` route win.
- **Not-built page: HTTP 503**, not 200 (architect ruling m-f0a5330767 — a missing build is
  service-unavailable; health checks / Slack deep links must not read it as success). `create_app()`
  still boots with no bundle. The criterion c-35447ca142 shorthand "200" was reworded to 503.

### 2. Identity `?as=`/`token` → headers (`src/auth/identity.ts`)
- Read `as`/`token` from the URL **once** at module load → `sessionStorage` (tab-scoped, not local).
  `token` is stripped from the address bar with `history.replaceState`, so it never lands in history,
  bookmarks, or a shared deep link. Default `as=owner` (parity `ui.py:235`).
- `EventSource` cannot set headers — this is *why* identity travels as `X-Participant`/`X-Token` and the
  feed is read with `fetch`, not `EventSource`.

### 3. SSE `/v1/feed` reaching the browser (`src/live/feed.ts`)
- `fetch` + `response.body.pipeThrough(new TextDecoderStream()).getReader()`; buffer and split frames on
  the blank line (`\n\n`); take `data:` lines. The board emits `: ready` / `: ping` comment frames (no
  `data:` line) which are skipped. Track the last `seq` and **reconnect from it** on any drop.
- Dev proxy (`vite.config.ts`): `/v1`, `/ui/poll`, `/healthz` → `http://127.0.0.1:9400`
  (`EDP8_BOARD_URL` overrides). No CORS — same-origin in prod, proxied in dev. SSE streams through the
  Vite proxy without buffering.

### 4. Playwright against a spawned board (`e2e/`)
- **Chromium pin**: `EDP8_CHROMIUM`, default
  `%LOCALAPPDATA%\ms-playwright\chromium-1234\chrome-win64\chrome.exe`. This machine has builds
  **1223 / 1228 / 1234** installed; `@playwright/test` is pinned to **1.62.0** because it bundles build
  1234 and pool shells set `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1` (cannot download). Exe dir is
  `chrome-win64`, not `chrome-win`. Bump the pin only after `npx playwright install chromium` on the pool.
- `e2e/globalSetup.ts` builds the SPA if `dist` is missing, then `startBoard()` (`e2e/board.ts`) picks a
  free port, spawns the board with temp `EDP8_DB`/`EDP8_HOME`, `EDP8_EMBEDDER=none`, `EDP8_ADMIN_TOKEN=t`,
  waits `/healthz`, and seeds `owner` + `arch` + one epic via `/v1`. `globalTeardown.ts` kills it.
- Board spawn command defaults to **`uv run edp8-board`** (design idiom); set `EDP8_BOARD_CMD` to the venv
  console script `edp8-board` to skip a cold `uv` sync (see Gotchas).

### 5. Wheel / Docker packaging of a gitignored `dist/`
- `src/edp8/webapp/dist/` is **gitignored** (regenerated) yet **force-included** into the wheel:
  `pyproject.toml [tool.hatch.build.targets.wheel.force-include] "src/edp8/webapp/dist" = "edp8/webapp/dist"`.
  Proven: `uv build --wheel` → the wheel contains `edp8/webapp/dist/index.html`, while
  `git status --short src/edp8/webapp/dist` is empty.
- `Dockerfile`: a `node:24-alpine` stage runs `npm --prefix web ci && npm --prefix web run build`
  (writing `/app/src/edp8/webapp/dist`), copied into the `python:3.12-slim` stage before `pip install .`.
  `engines.node` is `>=24` (LL §13), agreeing with the Docker node version. A `.dockerignore` keeps the
  context small (excludes `.venv`, `.data`, `node_modules`, `dist`, `.git`).
- Proven: `docker build -t edp8-spike:s1 .` succeeds, and
  `docker run --rm -p 9410:9400 -e EDP8_HOST=0.0.0.0 edp8-spike:s1` serves `GET /app/x?as=owner` (200,
  `Cache-Control: no-store`, referencing `/app/assets/*`).
- **force-include vs non-VCS builds.** Outside git (the Docker stage copies `dist` but excludes `.git`),
  hatch's file selection includes *everything* under the package, so `dist` was added twice — once by
  `packages` and once by `force-include` — failing with `A second file is being added ... at the same
  path`. Fixed by `[tool.hatch.build.targets.wheel] exclude = ["src/edp8/webapp/dist"]`, making
  force-include the sole source in both VCS (local) and non-VCS (Docker) builds.
- **Container bind host.** The board CMD defaults to `EDP8_HOST=127.0.0.1`, unreachable through a
  published port; run containers with `-e EDP8_HOST=0.0.0.0` (docker-compose should set it).

## Gotchas hit
- **`uv run` cold-sync stall.** The first `uv run <x>` in a fresh shell can hang for minutes on a sync.
  Tests here run through the venv interpreter directly (`.venv/Scripts/python -m pytest`), and the e2e
  fixture accepts `EDP8_BOARD_CMD` to spawn the venv `edp8-board` console script instead of `uv run`.
- **Node 25 EBADENGINE warnings.** `vitest@5.0.0` and `jsdom@30.0.1` declare `node ^22.12 || ^24 || >=26`;
  this machine runs node **v25.1.0** (between the ranges) → install warns but succeeds. S1 exercises no
  vitest, so it's non-blocking; the unit-test stories (S4+) should note it or the owner installs node 24/26.
- **`@types/react-dom` version.** Not pinned in LL §13; the invented `19.2.8` doesn't exist. Pinned to the
  real latest: `@types/react 19.2.18`, `@types/react-dom 19.2.7`, `@types/node 26.5.0`.
- **Shared source tree.** `dist/` is untracked — a sibling seat's `git clean` can wipe it; rebuild with
  `npm --prefix web run build` before `uv build`/e2e. Commit only your own paths, never `git add -A`.
