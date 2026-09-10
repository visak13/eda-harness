# edp8 web (Folio SPA)

Vite + React 19 + TypeScript front-end for the edp8 board — the Folio destinations (Decisions, Epics,
Epic, Seats, Library, Ticket, Doc), themes, identity adapter and SSE live feed. Built on the five
production seams the S1 spike proved (`src/auth/identity.ts`, `src/live/feed.ts`,
`src/edp8/webapp/serve.py`). After the G4 cutover the SPA is the default UI at `/ui` (see **Cutover**).

> Design: `design-dc3a77cbc1` §4.1 (HLD), §4.2 (IA/geometry), §4.4 (testing), §9 (risks). Craft bars: `strategyll-37c460a141`.

## Commands (run from `v8/`, never `cd` into `web/`)

| purpose | command |
|---|---|
| install (lockfile-exact) | `npm --prefix web ci` |
| install + update lock | `npm --prefix web install` |
| dev server (proxying a running board on :9400) | `npm --prefix web run dev` |
| production build → `../src/edp8/webapp/dist` | `npm --prefix web run build` |
| one-shot install+build (wraps the above) | `scripts/build-web.ps1 [-Ci]` · `scripts/build-web.sh [--ci]` |
| unit tests (Vitest + RTL, jsdom) | `npm --prefix web test -- --run` |
| unit coverage (v8, ≥80% lines) | `npm --prefix web test -- --run --coverage` |
| Playwright e2e (win32) | `npm --prefix web run e2e` |
| single e2e spec | `npm --prefix web run e2e -- e2e/spike.spec.ts` |

## Cutover — which renderer owns `/ui` (`EDP8_UI`, S12, design §4.1)

`create_app` reads **`EDP8_UI`** at board boot:

| `EDP8_UI` | `/ui` | `/ui-legacy` | SPA mounted? | `/ui/poll` |
|---|---|---|---|---|
| **`folio`** (default) | Folio SPA | legacy server-rendered UI (rollback) | yes, at `/ui` | poll (unchanged) |
| `legacy` | legacy server-rendered UI | — | **no** (one-flag rollback) | poll (unchanged) |

`/ui/poll` and every `/v1` route answer identically under both. The legacy renderer is **retained**,
not deleted (its retirement is a follow-up epic — see the retire-legacy plan note on story
`s-edb266895d`). Slack deep-link shapes `/ui/ticket/{id}?as=x` and `/ui/me?as=x` keep their shape and
open the SPA under `folio`.

**Rollback the SPA in one flag** (a seat never restarts the shared board — ask the launcher/owner):
`EDP8_UI=legacy` then `scripts/start-board.ps1 -Restart`. There is **no second bundle** — a `/ui`-built
SPA cannot also serve at `/app` (its `BASE_URL` is compiled in), so legacy mode simply turns the SPA
off and hands `/ui` back to the legacy renderer. The `/ui` bundle is built at **`EDP8_WEB_BASE=/ui/`**
(the default; was `/app/` during the pre-cutover build phase); `npm --prefix web run build`.

**Freshness guard.** The wheel build (`uv build --wheel`) runs `hatch_build.py`: if
`src/edp8/webapp/dist/index.html` is missing or older than any file under `web/src` (or
`web/index.html`, `vite.config.ts`, `package.json`) it runs `npm --prefix web run build` when npm is on
PATH and otherwise FAILS with the command to run; `EDP8_WEB_AUTOBUILD=0` makes it check-only. The e2e
`globalSetup` applies the same rule before a run. The :9400 fleet board serves dist from disk, so after a
`web/src` change rebuild (`$env:EDP8_WEB_BASE='/ui/'; npm run build` from PowerShell — Git Bash rewrites
`/ui/`) and hard-refresh; a wheel/docker image always carries a bundle at least as new as its sources.

Backend serve + wheel + serve tests (from `v8/`):

```
npm --prefix web ci && npm --prefix web run build && uv run pytest -q tests/test_webapp_serve.py
uv build --wheel && python -m zipfile -l dist/edp8-*.whl | grep webapp/dist   # ships index.html
```

## Seam findings

### 1. Serve a Vite bundle from FastAPI under a prefix (`webapp/serve.py::mount_spa`)
- Vite `base` **must equal the mount prefix** so emitted asset URLs resolve. Post-cutover (S12) the
  SPA owns `/ui` under `EDP8_UI=folio`, so `vite.config.ts` sets `base: "/ui/"` (override via
  `EDP8_WEB_BASE`; build with `/app/` only for the legacy-mode SPA at `/app`). `main.tsx` derives the
  react-router basename from `import.meta.env.BASE_URL`, so this one knob moves both. A relative
  `base: "./"` breaks on deep SPA routes (catch-all serves `index.html` from a nested path) — use an
  absolute prefix.
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
  Because `uv build` (no flag) builds the sdist first and the wheel *from* that sdist, and hatch's
  sdist honours `.gitignore`, the sdist must also carry `dist`
  (`[tool.hatch.build.targets.sdist] artifacts = ["src/edp8/webapp/dist/**"]`) — otherwise the
  wheel-from-sdist stage fails with `Forced include not found`. Proven: `uv build` (no flag) → the
  wheel contains `edp8/webapp/dist/index.html` + hashed `assets/*`, while
  `git status --short src/edp8/webapp/dist` is empty.
- `Dockerfile`: a `node:24-alpine` stage runs `npm --prefix web ci && npm --prefix web run build`
  (writing `/app/src/edp8/webapp/dist`), copied into the `python:3.12-slim` stage before `pip install .`.
  `engines.node` is `>=24` (LL §13), agreeing with the Docker node version. A `.dockerignore` keeps the
  context small (excludes `.venv`, `.data`, `node_modules`, `dist`, `.git`).
- Proven: `docker build -t edp8-spike:s1 .` succeeds, and
  `docker run --rm -p 9410:9400 -e EDP8_HOST=0.0.0.0 edp8-spike:s1` serves the Folio SPA at
  `GET /ui/x?as=owner` (200, `Cache-Control: no-store`, referencing `/ui/assets/*`) under the
  `EDP8_UI=folio` default.
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
