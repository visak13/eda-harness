# INSTALL-PATHS.md — rtk + graphify, grounded install research (s30 / a1, STAGE A)

**Status:** research only. **NOTHING WAS INSTALLED.** No installer, package add,
`curl | sh`, winget/cargo/pip/uv install, or download-and-execute was run. Every
command in this file is for the USER's hands.

**Date:** 2026-07-11 · **Host:** Windows 11, AMD64 · **Grounding:** the projects'
own published instructions (GitHub README, GitHub Releases API, PyPI metadata),
quoted — not inferred from memory.

---

## 0. Host facts (re-confirmed, not re-derived)

Confirmed by direct probe this session; all match the planner's brief:

| Fact | Probe result |
|---|---|
| `rtk` on PATH | NOT FOUND |
| `cargo` / `rustc` | NOT FOUND (no Rust toolchain) |
| `graphify` on PATH | NOT FOUND |
| `uv` | present — `C:\Users\aksou\AppData\Local\Microsoft\WinGet\Links\uv.exe`, v0.9.11 |
| `git` | present |
| `edp-pool/.claude-pool/settings.json` | EXISTS: `{"tui":"fullscreen","theme":"dark","effortLevel":"medium"}` — **no `hooks` block** |

### THE ONE FACT THAT DRIVES BOTH TOOLS

`C:\Users\aksou\.local\bin`

- **exists** (currently holds only `python3.13.exe`),
- is **`uv`'s tool bin directory** (`uv tool dir --bin` → exactly this path),
- is the directory **rtk's README recommends** for `rtk.exe` on Windows,
- and is **NOT on the persistent User PATH** (verified against the User PATH
  registry value; it lists WindowsApps, nvm, VS Code, WinGet\Links, gcloud,
  Ollama, Adoptium, jdtls, .dotnet\tools — and no `.local\bin`).

So **one PATH addition serves both tools.** Do it once, in §3, not twice.

### PATH propagation into pool shells (load-bearing)

`pty_launcher.build_env` starts from **`os.environ.copy()`** (edp-pool/src/edp_pool/pty_launcher.py:425). A pool-spawned shell therefore inherits the **pool server process's** PATH — not a freshly-read User PATH. Consequence:

> Adding `.local\bin` to the User PATH does **not** reach running shells. The
> **pool server (and the foreground Claude Code session) must be restarted from a
> shell that already has the new PATH.** Per d2 restarts are user-driven; this
> folds into the coordinated bounce the step already needs for `EDP_RTK=1`.

---

## 1. rtk

**What it is:** a CLI proxy that "filters and compresses command outputs before
they reach your LLM context" — wraps a command, compresses its output, claims
60–90% token reduction. Rust binary. Repo: `github.com/rtk-ai/rtk`.

### 1.1 Prebuilt Windows binary — EXISTS. This is the path. (No Rust needed.)

Read from the **GitHub Releases API**, not from memory:

- **Release tag:** `v0.43.0` (latest, published 2026-06-28, not a prerelease)
- **Asset filename:** `rtk-x86_64-pc-windows-msvc.zip` — matches this host (AMD64)
- **Download URL:**
  `https://github.com/rtk-ai/rtk/releases/download/v0.43.0/rtk-x86_64-pc-windows-msvc.zip`
- **Checksum — the project DOES publish one.** `checksums.txt` is a release asset
  (`https://github.com/rtk-ai/rtk/releases/download/v0.43.0/checksums.txt`). The
  SHA-256 for the Windows zip, quoted from it verbatim:

  ```
  7c5e4a2ef816a4d4ed947ddd74ca3df851fc39ea87d49a3ca2bf3abc515a016b  rtk-x86_64-pc-windows-msvc.zip
  ```

The README's Windows instruction, verbatim in substance: extract the zip and place
`rtk.exe` in your PATH (**it names `C:\Users\<you>\.local\bin` as the example**),
and "Run RTK from **Command Prompt**, **PowerShell**, or **Windows Terminal** — do
not double-click the `.exe`." Verify with `rtk --version`.

**No elevated shell is required.** Everything lands under the user profile.

### 1.2 Toolchain fallback — NOT NEEDED, priced only to close the question

The other install routes the README offers are `brew install rtk` (macOS/Linux),
`curl … install.sh | sh` (Linux/macOS — **not Windows**), and
`cargo install --git https://github.com/rtk-ai/rtk`. The cargo route is the only
Windows-viable alternative and it is **strictly worse here**: `cargo` and `rustc`
are both absent, so it would first require installing a full Rust toolchain
(rustup + MSVC build tools — a multi-GB, longer, higher-blast-radius change) to
build a binary the project **already ships prebuilt for this exact target**.

**Recommendation: use the prebuilt binary. Do not install Rust.**

### 1.3 Where the binary must land

`C:\Users\aksou\.local\bin\rtk.exe`, with that directory added to the **User**
PATH (§3). This single location is resolvable by:

- **foreground** Claude Code shells (they inherit the user environment), and
- **pool-spawned** shells (they inherit the pool server's environment, which
  carries the User PATH once the pool is restarted — see §0).

It is also where `uv tool install` will put `graphify.exe`, so the same PATH entry
covers §2. Do **not** drop `rtk.exe` into `WinGet\Links` (already on PATH but
WinGet-managed — an unmanaged binary there is a foreign object in a package
manager's directory).

### 1.4 How the existing hook invokes it — read from the file, not assumed

`claude/.claude/hooks/rtk-pretooluse.py` (already exists, already registered in
`claude/.claude/settings.json` under `PreToolUse`, matcher `Bash`):

- It **shells out to `rtk --version`** as an availability probe: `_rtk_available()`
  does `shutil.which("rtk")`, then `subprocess.run(["rtk", "--version"], timeout=3)`
  and requires `returncode == 0`.
- On a hit it rewrites the Bash command to **`rtk <original command>`** — literally
  prefixing the string — and returns a PreToolUse `allow` decision carrying
  `updatedInput.command`.
- **On a missing binary it PASSES THROUGH, cleanly.** `rewrite()` returns `None`
  when `EDP_RTK != "1"`, when the command is empty, when the command already
  starts with `rtk ` (idempotence), or when `_rtk_available()` is False — and
  `main()` then just `return 0` with no output, so the Bash command runs exactly
  as it does today. `main()` wraps everything in a bare `except Exception: return 0`.
  The module docstring states the contract: **"FAIL-SAFE is mandatory: this hook
  must NEVER block or error out a Bash call; any exception is swallowed into
  pass-through."**
- **Gate is BOTH-of:** `EDP_RTK == "1"` **AND** `rtk --version` exits 0. Today the
  binary is absent, so it no-ops — which is exactly why rtk has been inert.
- **Errors kept verbatim — confirmed as a documented claim, NOT as measured
  behaviour.** The hook's docstring says: "rtk keeps stderr/errors verbatim by
  design, so when the compressed view is insufficient an agent can re-run the raw
  command." That sentence is *our own* docstring restating rtk's design intent. It
  is a claim to be **measured** once the binary is on PATH, not a fact this action
  can certify.

**Second, independent blocker (do not lose this):** pool shells pin
`CLAUDE_CONFIG_DIR` to `edp-pool/.claude-pool` (pty_launcher.py:443-444), and that
config **has no `hooks` block**. So even with `rtk.exe` on PATH and `EDP_RTK=1`,
pool shells still would not fire the hook. Wiring that is a *later* action, and it
carries a live tripwire:

> ⚠ **`edp-pool/.claude-pool/settings.json` EXISTS and holds the user's
> `effortLevel: "medium"` (d106).** APPEND a `hooks` block by read-modify-write.
> **NEVER create it fresh; NEVER overwrite it.** Losing `effortLevel` silently
> destroys a production setting the user personally chose. (Per d67 — the earlier
> record claiming this file was "ABSENT ENTIRELY" was FALSE.)

FYI for that later action: `edp-pool/.pool-logs/spawn_defaults.json` already
contains `{"rtk": true}`, and per pty_launcher.py:452-464 the file **wins over the
ambient env** — so `EDP_RTK=1` is already effectively requested at spawn.

### 1.5 EXACT COMMANDS FOR THE USER — rtk

Run in **PowerShell**. No elevation required. (Steps 1–4 install; the PATH step is
in §3 and is shared with graphify.)

```powershell
# 1. Download the prebuilt Windows binary (v0.43.0) + the project's checksums file
$dl = "$env:USERPROFILE\Downloads"
Invoke-WebRequest -Uri "https://github.com/rtk-ai/rtk/releases/download/v0.43.0/rtk-x86_64-pc-windows-msvc.zip" -OutFile "$dl\rtk-x86_64-pc-windows-msvc.zip"

# 2. VERIFY THE CHECKSUM before you extract anything.
#    This must print: True
(Get-FileHash "$dl\rtk-x86_64-pc-windows-msvc.zip" -Algorithm SHA256).Hash -eq "7C5E4A2EF816A4D4ED947DDD74CA3DF851FC39EA87D49A3CA2BF3ABC515A016B"

# 3. Extract and place rtk.exe in the shared bin dir (it already exists)
Expand-Archive -Path "$dl\rtk-x86_64-pc-windows-msvc.zip" -DestinationPath "$dl\rtk-extract" -Force
Copy-Item "$dl\rtk-extract\rtk.exe" "$env:USERPROFILE\.local\bin\rtk.exe" -Force

# 4. Verify the binary runs (full path — PATH is not wired until §3)
& "$env:USERPROFILE\.local\bin\rtk.exe" --version
```

> If step 2 prints `False`, **STOP** — do not extract or run the file. Re-download,
> and if it fails again, report it: a checksum mismatch is a finding, not a nuisance.
>
> If step 3 fails with "path not found", list the zip's contents
> (`Expand-Archive` then `Get-ChildItem "$dl\rtk-extract" -Recurse`) — the binary may
> sit one directory deeper. Copy the `rtk.exe` you find.

---

## 2. graphify

**What it is — and the first correction to the record:** graphify is **a Claude
Code *skill*, not merely a CLI**. Its README's headline is "**A Claude Code
skill.** Type `/graphify` in Claude Code." The `/graphify …` forms in its docs are
**skill invocations typed into an assistant**, not shell commands. There is *also*
a real CLI (`graphify query|path|explain|install|hook`) that runs against
`graph.json` from a terminal — and **that CLI is the binding this harness can
actually reach.** Repo: `github.com/safishamsi/graphify`.

**Second correction to the record: the GitHub repo is STALE relative to PyPI.**
The public repo's `pyproject.toml` is at version **0.1.15** (branch `v1`) / 0.1.14
(`main`), while the PyPI package `graphifyy` is at **0.9.12**. An install gets
**0.9.12**, whose instructions differ materially from the GitHub README (0.9.12
adds `--project` installs, `uv tool install`, ~40 tree-sitter grammars, an MCP
server with a documented tool list). **Everything below is grounded in the 0.9.12
PyPI metadata + its packaged README** — i.e. what the user would actually get —
not in the stale repo README.

- **PyPI package name:** `graphifyy` (**double-y**). The README flags this
  explicitly: "The PyPI package is `graphifyy` (double-y)… The CLI command is still
  `graphify`." Also: "Other `graphify*` packages on PyPI are not affiliated." —
  **installing `graphify` (single-y) would be installing a stranger's package.**
- **Requires:** Python ≥3.10 (satisfied). `uv` present.
- **CLI entry point** (from `pyproject.toml`): `graphify = "graphify.__main__:main"`.

### 2.1 Install on Windows with uv — exact, quoted

The README's Step 1/Step 2, verbatim:

```bash
uv tool install graphifyy      # Recommended (isolated env)
graphify install               # register the skill with your AI assistant
```

And, quoted, the resolution note that predicts *exactly* this host's situation:

> "**`graphify: command not found`?** `uv tool install` / `pipx install` put the
> `graphify` command in their tool bin dir (`~/.local/bin`). If your shell can't
> find it right after install… that dir isn't on your `PATH` yet: run
> `uv tool update-shell` … then open a new terminal."

That is the same `C:\Users\aksou\.local\bin` from §0 — **already true here**, so
expect it and handle it in §3 rather than be surprised by it.

Two more quoted notes that matter:

> "**Avoid `pip install` on Mac/Windows** if possible. The skill resolves Python at
> runtime from `graphify-out/.graphify_python`; if that points to a different
> environment than where `pip` installed the package, you'll get
> `ModuleNotFoundError`. `uv tool install` and `pipx install` isolate the package
> in their own env and avoid this entirely."

> "**PowerShell note:** Use `graphify .` not `/graphify .` — the leading slash is a
> path separator in PowerShell."

**Extras are opt-in and the MCP server is one of them:** `mcp` is an optional
extra (`uv tool install "graphifyy[mcp]"`). Installing plain `graphifyy` does
**not** get you the MCP server. (`leiden` community detection is gated to
Python < 3.13 — on a 3.13+ interpreter graphify uses its LLM-free labelling
fallback instead. Not a blocker; just don't expect Leiden.)

**No elevated shell is required.**

### 2.2 Building the graph — command, and the target that is actually correct here

- **Entry command (CLI, PowerShell):** `graphify .` — or, better here, a **scoped
  path**: `graphify <folder>`.
- **Output artifact location:** a **`graphify-out/`** directory in the current
  working directory, containing (quoted from the README's tree):
  `graph.json` ("the full graph — query it anytime without re-reading your files"),
  `GRAPH_REPORT.md`, `graph.html`, `cache/` (SHA256 cache — re-runs only process
  changed files), and optionally `obsidian/` / `wiki/`.
  `graph.json` is the artifact the query binding reads.
- **Useful variants:** `--update` (re-extract only changed files), `--no-viz`
  (skip HTML), `--mode deep`, `--cluster-only`.

**⚠ DO NOT run `graphify .` at the workspace root.** Measured this session, the
repo root is dominated by *runtime state*, not source:

| Path | .md files | note |
|---|---|---|
| `claude/.backup` | 4,256 | backup churn |
| `claude/.plans` | 2,228 | plan/worklog state |
| `claude/.recipes` | 692 | recipe state |
| `claude/docs` | 108 | **real docs** |

…plus 333 files under `.inbox_cursors` and 191 under `.backup` on the code side. A
naive full-tree run would build a graph mostly *of the framework's own worklogs*,
which is noise, and would bury the ~200 files that are actually the system.

**Recommended target (scoped, honest):**
`claude/src`, `claude/tests`, `edp-pool/src`, `edp-broker/src` (+ `claude/docs` if
docs are wanted in the graph).

### 2.3 Query binding — the options, and which one this harness can actually reach

| Binding | What it is | Reachable from this harness? |
|---|---|---|
| **CLI against `graph.json`** — `graphify query "<q>"`, `graphify path A B`, `graphify explain "X"` | Terminal commands; the README shows `graphify query "…" --graph graphify-out/graph.json` | **YES — this is the one.** Any worker/reviewer already has the Bash tool. Zero new wiring, works in foreground *and* pool shells the moment the PATH is live. |
| **MCP server** — `python -m graphify.serve graphify-out/graph.json` (stdio; `--transport http --port 8080` also available). Exposes `query_graph`, `get_node`, `get_neighbors`, `shortest_path`, `list_prs`, `get_pr_impact`, `triage_prs` | Structured tool access | **Yes, but costs wiring**: needs the `[mcp]` extra, plus an entry in `claude/.mcp.json` (which already carries `edp-claude` / `design-templates` / `unrealMCP`, so the pattern is proven). Strictly more work than the CLI for the same graph. |
| **Skill / always-on hook** — `graphify claude install` writes a `PreToolUse` hook + CLAUDE.md guidance that "fires automatically before search-style tool calls (and… before reading source files one by one via the Read/Glob tools) and nudges your assistant toward the graph path" | The "query instead of grep/Read" enforcement | **Yes — and this is the piece that hits our known gap.** It is the **same PreToolUse mechanism rtk uses**, so it lands in the same settings files and inherits the **same pool-config-dir problem** and the **same d67 tripwire** (§1.4). A `--project` install (`graphify install --project`) writes `.claude/skills/graphify/SKILL.md` under the repo, which is the right shape for a checked-in harness. |

**Recommendation:** take the **CLI binding first** (`graphify query`) — it is
reachable today, needs no config surgery, and is sufficient to prove or refute the
value. Treat the hook/skill binding as the *second* step, and when wiring it,
honor the §1.4 tripwire: **append** to `edp-pool/.claude-pool/settings.json`,
never overwrite it.

### 2.4 HONEST EXPECTED PAYOFF — stated BEFORE we measure it

Recorded up front, deliberately, so the later measurement **cannot be quietly
reinterpreted to flatter the tool**:

**Measured corpus size (this session, `.venv` excluded):** the real indexable code
corpus — `claude/src` (62 .py, matching the brief exactly) + `claude/tests` (113) +
`edp-pool/src`/`tests` (71) + `edp-broker/src` (6) — is **≈205 Python files**
(~250 counting all real code file types). The 2,395 / 947 figures previously
floating around are **`.venv`-inflated and are not real source** (the tree holds
9,626 `.py` files *with* `.venv`, vs 850 real code files without it).

**Therefore:**

1. **This corpus is ~205 files — well under the ≥500-file threshold DESIGN-v6's own
   analysis names as graphify's payoff point.** By the design's own reckoning, the
   token benefit here is **marginal**. I expect graphify to *function correctly*
   and to be *useful for structure/navigation*, and I do **not** expect the
   headline **71.5×** fewer-tokens-per-query figure to reproduce on this repo. That
   71.5× is graphify's own benchmark on a *mixed* corpus (repos + papers + images);
   its own README concedes "**Token reduction scales with corpus size**" and that a
   small corpus "fits in a context window anyway, so graph value there is
   **structural clarity, not compression**."
2. **The downside is genuinely low, which is the real reason to try it.** graphify's
   own benchmark table lists **"Graph build — LLM credits: 0"**, and the README
   states code is "parsed locally with tree-sitter (no LLM, nothing leaves your
   machine); only the semantic pass over docs/media calls a backend, and only if you
   configure one." So building the graph over **code** costs ~zero model tokens. A
   cheap-to-build, possibly-modest-payoff tool is a reasonable bet — but that is an
   argument for *trying* it, not for *claiming* savings.
3. **Where a real win is plausible, if one exists:** replacing repeated multi-file
   `Read`/`Glob`/`grep` sweeps ("what calls `record_action_status`?", "what connects
   the planner FSM to the broker?") with one scoped `graphify query`. That is a
   *per-query* substitution, so the payoff is proportional to how often agents
   actually grep — which is an empirical question about our worklogs, and **it is
   the thing the later measurement must measure.** The honest framing is
   *fewer tokens per navigation query*, **not** *71.5× cheaper agents*.

**Pre-registered bar:** if the measured token delta on a real worker's navigation
pattern is not clearly positive, the correct outcome is to **say so** — a measured
"functions, but the payoff on a 205-file corpus is inside the noise" is an
acceptable, valuable result under d77. It is not a failure to be argued away.

### 2.5 EXACT COMMANDS FOR THE USER — graphify

Run in **PowerShell**. No elevation required. Do §3 (PATH) either before this or
right after step 1 — `graphify` will not resolve until `.local\bin` is on PATH.

```powershell
# 1. Install the CLI (isolated env). NOTE THE DOUBLE-Y: graphifyy.
#    The [mcp] extra is included so the MCP binding stays available without a reinstall.
uv tool install "graphifyy[mcp]"

# 2. Put uv's tool bin dir on PATH (this is the same dir rtk.exe lives in).
#    uv does it for you here:
uv tool update-shell

# 3. Open a NEW PowerShell window, then verify the CLI resolves:
graphify --version

# 4. Build the graph — SCOPED to the real source tree, not the repo root
#    (the root is dominated by .backup/.plans/.recipes runtime state).
cd C:\Projects\Learning\eda-base3
graphify .\claude\src --no-viz

# 5. Confirm the artifact landed, then try one real query:
Get-ChildItem .\graphify-out\
graphify query "what connects the plan FSM to the broker?"
```

> **Do not run `graphify .` at `C:\Projects\Learning\eda-base3`.** See §2.2 — it
> would index ~7,000 markdown files of backups and worklogs.
>
> If step 3 still says `graphify` is not recognized, the PATH change has not
> reached this shell — confirm `C:\Users\aksou\.local\bin` is in
> `$env:PATH`, and if not, apply §3 manually and open a new window.
>
> **Do not `pip install graphify`** (single-y). That is a different, unaffiliated
> package.

---

## 3. EXACT COMMANDS FOR THE USER — the shared PATH step (do this ONCE, for both tools)

`C:\Users\aksou\.local\bin` is where **`rtk.exe`** goes (§1.3) *and* where
**`uv tool install` puts `graphify.exe`** (§2.1). It exists but is not on the
persistent User PATH. One addition covers both.

Run in **PowerShell**. **No elevation required** — this writes the *User* PATH, not
the Machine PATH.

```powershell
# 1. Add ~\.local\bin to the PERSISTENT User PATH (idempotent — safe to re-run).
#    Reads the existing value and appends; it does NOT clobber your PATH.
$bin  = "$env:USERPROFILE\.local\bin"
$user = [Environment]::GetEnvironmentVariable('Path','User')
if (($user -split ';') -notcontains $bin) {
    [Environment]::SetEnvironmentVariable('Path', "$user;$bin", 'User')
    "ADDED: $bin"
} else {
    "ALREADY PRESENT: $bin"
}

# 2. Make it live in THIS shell too (the persistent change only reaches new processes)
$env:PATH = "$env:PATH;$env:USERPROFILE\.local\bin"

# 3. Verify BOTH tools resolve (run after installing them per §1.5 and §2.5)
rtk --version
graphify --version
```

> ⚠ **This is the step that has a way to go wrong.** Do **not** use
> `setx PATH "%PATH%;..."` — `setx` truncates at 1024 characters and expands the
> *combined* Machine+User PATH into the *User* PATH, which corrupts it. The
> read-append-write above is the safe form.

### 3.1 THEN: restart the stack (this is what makes the pool see the tools)

A PATH change does **not** reach already-running processes. Pool shells inherit the
**pool server's** environment (§0). So, per the user-driven restart discipline (d2)
and one coordinated bounce per phase (d19/d58):

1. Quiesce and restart the **broker + pool** — **started from a NEW shell** that
   has the updated PATH (a pool server restarted from a stale shell will still not
   see `rtk.exe`, and rtk will silently keep no-op'ing — this is the exact failure
   mode that would look like "we installed it and nothing happened").
2. Restart the **foreground Claude Code session** for the same reason.
3. Only then is `rtk --version` resolvable *inside a spawned worker*, which is the
   condition `rtk-pretooluse.py` actually gates on (§1.4).

---

## 4. Findings that the next actions must not lose

1. **Neither tool is blocked on this host.** rtk ships a prebuilt
   `x86_64-pc-windows-msvc` binary with a published SHA-256, so the missing Rust
   toolchain is **irrelevant** — do not install Rust. graphify installs cleanly via
   the already-present `uv`. **There is no cannot-work-on-this-host finding for
   either tool.**
2. **One PATH entry (`~\.local\bin`) serves both.** It exists, it is uv's tool bin
   dir and rtk's recommended location, and it is not on PATH. Fix once.
3. **PATH must reach the POOL SERVER, not just the user.** `build_env` copies
   `os.environ`, so the pool must be restarted from a shell carrying the new PATH.
   Miss this and rtk stays inert while *looking* installed.
4. **rtk needs a SECOND fix beyond the binary:** a `hooks` block in
   `edp-pool/.claude-pool/settings.json`. That file **EXISTS** and holds the user's
   `effortLevel: "medium"`. **APPEND (read-modify-write). NEVER overwrite.** The
   acceptance for that action must assert `effortLevel == "medium"` survives.
5. **The graphify GitHub README is stale (0.1.x) vs the PyPI package (0.9.12).**
   Ground in PyPI. The package is **`graphifyy`** — double-y; the single-y name is
   an unaffiliated package.
6. **graphify's own Claude-Code binding is a PreToolUse hook** — the *same*
   mechanism as rtk, hitting the *same* pool-config gap and the *same* tripwire (4).
   Wire the **CLI binding first**; it is reachable with zero config surgery.
7. **Scope the graph build.** `graphify .` at the repo root indexes ~7,000 markdown
   files of `.backup`/`.plans`/`.recipes` runtime state. Target the real source.
8. **The expected payoff for graphify is MARGINAL, and that is on the record
   before measurement** (§2.4): ~205 real source files vs the ≥500-file threshold
   the design itself names; build cost ≈0 LLM tokens; expect structural clarity,
   **not** the headline 71.5×.
9. **"rtk keeps errors verbatim" is a documented claim, not a measured fact.** Our
   own hook docstring asserts it. It is exactly the kind of sentence this recipe has
   repeatedly caught outrunning its evidence — **measure it** once rtk is live.
