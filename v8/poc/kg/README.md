# S13 — knowledge-graph proof of concept

A small SQLite graph over epic-44a0576511, built to answer with data whether an
epic can be held as a current, small graph that returns the most relevant facts
to a seat every time. Findings: board report **report-70411801d5**.

Code is a few hundred lines of stdlib Python (+ PIL for pictures). No new
dependency. Data (db, packs, pictures) lives under `v8/.data/kg-poc/`.

## Layout
- `db.py` — schema: `node`, `edge`, `source`, `ingest_state`, `module_head`, FTS5 mirror.
- `board.py` — read-only board REST client (`X-Participant`, stdlib urllib).
- `ingest.py` — incremental ingest (board REST + `git log`). Rules-only decision extraction, 0 model calls.
- `walk.py` — `walk(start)` retrieval: FTS5 seed, mandatory constraint set, scored 2-hop remainder, 8 KB / 40-node cut, receipt.
- `gold.py` — 12 gold questions, seed comparison (FTS5 vs TF-IDF), walk recall, answer packs.
- `freshness.py` — freshness replay on a db COPY.
- `render.py` — real-graph PNGs (module slice, epic top level).

## Cold re-run (qa)
Run from `v8/` with the fleet board (:9400) up:
```
PY=.venv/Scripts/python.exe
$PY poc/kg/ingest.py            # build kg.db; prints node/edge counts by type
$PY poc/kg/ingest.py            # second run: a no-op (0 node/edge/source/head writes) -> c-06d5f4a76d
$PY poc/kg/walk.py "src/edp8/slack_bridge.py"   # module walk + stale flags -> c-4b3c96e28c
$PY poc/kg/walk.py "s-5c93e5e31e"               # ticket walk (<=40 nodes, <=8KB)
$PY poc/kg/gold.py             # seed comparison + walk recall 12/12       -> c-be9347848d
$PY poc/kg/freshness.py        # freshness replay: PASS                    -> c-30fd782289
$PY poc/kg/render.py module "src/edp8/slack_bridge.py" .data/kg-poc/pics/kg-module-slack.png
$PY poc/kg/render.py epic .data/kg-poc/pics/kg-epic-toplevel.png          # -> c-61fa86d6cf
$PY poc/kg/gold.py packq .data/kg-poc/gold-pack-perq.md  # the cold answering pack -> c-98dee60cae
```
The gold answering seat gets ONLY `.data/kg-poc/gold-pack-perq.md` and never the
marking key (note-0151676530). Cold answers + grade: `.data/kg-poc/gold-results.md`.

`KG_DB` env overrides the db path; `EDP8_BOARD_URL` / `EDP8_PARTICIPANT` the board.
