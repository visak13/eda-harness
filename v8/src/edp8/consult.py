"""edp8.consult — the v8 bridge to the GPT consultant (Astra/Sol) via the OpenAI Codex CLI.

Replaces claude/src/edp_claude/tools/sol_bridge.py for v8. Keeps the landmines
that module documented (empty stdin else the CLI hangs forever; globals BEFORE
the `exec` subcommand; the prompt ALWAYS behind `--`; stdout+stderr merged
because the interesting error lands on stderr; `-o` for the final answer).

S0c (2026-09-05) adds the purpose PROFILES contract (Astra m-98a321d7d2 §5,
design addendum note-c6012f12c1 §B, architect m-3afdbf1a62):

  * Five profiles — design | concept | blender | verify | direct — each fixing
    the codex-exec invocation: sandbox mode, approval_policy=never, effort, the
    enabled/disabled set of MCP servers + features (+ best-effort skill toggles).
    `purpose` maps to a profile (adversary/second_opinion→design, creative→
    concept, visual→verify, build→blender); an explicit `profile=` overrides.
  * Asset boundary enforced in CODE: write_dir may never be inside/equal/parent
    of the UE project root (junctions resolved); a post-run mtime scan fails the
    call on any write into the protected UE tree.
  * Evidence integrity: images decoded (PIL) + hashed before the run; the verify
    profile parses a structured PASS/FAIL/UNVERIFIED verdict; a run with no final
    answer FAILS CLOSED (no last-log-line fallback); requested vs provider model
    recorded; timeout preserves thread_id and kills the child PROCESS TREE;
    image_gen is never auto-retried. Every run writes a manifest.

S0d (2026-09-05) turns the post-run boundary into an ATTRIBUTING WRITE-FENCE. Measured
this build: the read-only codex sandbox IS enforced on Windows (a write under a
read-only profile is refused at the OS layer — runs 8d98f6ae/4e638d11; the earlier
"nominal on Windows" claim was inferred, not measured, and the origin escape could not
be reproduced). The fence is therefore DEFENSE-IN-DEPTH, and it attributes before it
acts so a concurrent seat's file is never touched (the S10 false positive): (a)
git-snapshot the UE root before launch (`git status --porcelain`, gitignored build
output excluded); (b) after the run, a dirty path already dirty pre-run is a concurrent
seat's edit (left), a path THIS run's codex jsonl NAMES in a write/shell/apply_patch
event is the escape — new file deleted, modified tracked file `git checkout --`
restored (sha256 + action recorded) — and a path no log names is unattributed
(left); (c) an ATTRIBUTED escape fails the run closed (code=boundary) while a
concurrent-only run succeeds, and EITHER way Astra's answer is returned flagged
`recovered: true` with the escape report, never discarded. See fence_remediate /
codex_log_corpus + criteria c-fe4f824d82 / c-16ae18056e / c-1457650970.

CAPABILITY GATING IS ENFORCED (MCP allowlist, feature allowlist, sandbox root,
approval=never, post-run boundary scan). SKILL visibility is best-effort only:
codex 0.153.4 does not honour `-c skills.config` toggles (the skill list is not
pruned), so skill toggles are emitted to argv + manifest for the record and a
prompt-level line names the skills a profile MAY use — see guides/sol-pairing.md.

PAIN POINT (claude/docs/pain-points.jsonl, 2026-08-21): the old bridge glossed
every non-zero exit as "quota cap". This module never does that — a failure's
`message` is the actual last non-empty output line, and the `hint` says what to
check (login / model id / network), never a canned quota story.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

Purpose = Literal["adversary", "creative", "visual", "second_opinion", "build"]
ProfileName = Literal["design", "concept", "blender", "verify", "direct"]

#: Short system preambles selected by purpose (user directive, this task).
_PREAMBLES: dict[str, str] = {
    "adversary": (
        "attack this delivery: find bugs, gaps vs the stated requirement, risky "
        "assumptions; classify each finding obvious-bug vs scope-question; be "
        "concrete (file, line, repro)."
    ),
    "creative": (
        "you are the visual/creative authority: judge or specify look against "
        "the references; give measurable bars. When a writable workspace is "
        "given, deliver files (SVG/CSS/code) directly into it — never describe "
        "an asset you could produce."
    ),
    "visual": (
        "you are the visual/creative authority: judge or specify look against "
        "the references; give measurable bars. When a writable workspace is "
        "given, deliver files (SVG/CSS/code) directly into it — never describe "
        "an asset you could produce."
    ),
    "second_opinion": "give an independent read; disagree where warranted.",
    "build": (
        "you are a senior implementation agent working directly in the "
        "workspace, and you OWN THE OUTCOME, not just the checklist: the "
        "stated constraints are the floor — the quality bar is your own, and "
        "'technically satisfies the instructions' is a failure if the result "
        "is lifeless. Keep the code style of the files you touch and do not "
        "break existing behavior. End your reply with the list of every file "
        "you created or edited and one line on why."
    ),
}

# ------------------------------------------------------------------ profiles

#: purpose value → profile name. Legacy purposes stay valid (architect m-31d80fa690).
_PURPOSE_TO_PROFILE: dict[str, ProfileName] = {
    "adversary": "design",
    "second_opinion": "design",
    "creative": "concept",
    "visual": "verify",
    "build": "blender",
}

#: MCP containment is DISCOVER-AND-DISABLE, never a static denylist (a plugin can
#: inject a server a fixed list misses — e.g. `cua_repl`, the unified-computer-use
#: surface, absent from config.toml but live). Every server `codex mcp list --json`
#: reports at call time is disabled in every profile; discovery failure is fail-closed.
#: unreal-mcp stays a hard floor even if discovery returns nothing.
_MCP_FLOOR: tuple[str, ...] = ("unreal-mcp",)

#: A stdio server that has no `mcp_servers.<name>` table in config.toml (plugin-
#: injected, e.g. cua_repl) rejects a bare `-c mcp_servers.<name>.enabled=false`
#: with "invalid transport"; supplying this harmless stub `command` makes the merge
#: a valid (disabled) table. The server is disabled, so the stub is never launched.
#: A url/http server instead takes a bare `.enabled=false` — adding a command there
#: is rejected as "url is not supported for stdio". (proven on codex 0.153.4)
_MCP_STUB_COMMAND = "edp8-disabled"

#: Features we always emit (name order fixed) so the argv is deterministic and a
#: reviewer can assert the exact set. Proven via `codex features list -c features.<n>=…`.
_MANAGED_FEATURES: tuple[str, ...] = (
    "image_generation", "view_image", "browser_use", "computer_use", "js_repl",
)

#: Skills emitted to `-c skills.config` (best-effort; 0.153.4 does not prune). "off by
#: default"; a profile's `skills_on` flips its allowed few to enabled=true.
_MANAGED_SKILLS: tuple[str, ...] = (
    "photoreal-asset-factory", "terrain-geology-assets", "imagegen",
    "sites", "documents", "spreadsheets", "presentations", "template-creator",
    "pdf", "computer-use", "visualize", "neuron", "tree-growth-assets",
)


@dataclass(frozen=True)
class ProfileSpec:
    """The full, enforced codex-exec invocation contract for one profile."""
    sandbox: str                       # "read-only" | "workspace-write"
    effort: str                        # model_reasoning_effort
    features: dict[str, bool]          # feature name -> enabled (covers _MANAGED_FEATURES)
    skills_on: tuple[str, ...] = ()    # skills flipped enabled=true (subset of _MANAGED_SKILLS)
    brief: str = ""                    # extra prompt line (allowed skills / verdict format)

    @property
    def writes(self) -> bool:
        return self.sandbox == "workspace-write"


_VERDICT_BRIEF = (
    "Return your answer with a final structured VERDICT block, exactly:\n"
    "VERDICT\n"
    "status: PASS | FAIL | UNVERIFIED\n"
    "inspected: <evidence ids / sha256 you actually read>\n"
    "findings:\n- frame <n> region <x,y-w,h>: <what is wrong or right>\n"
    "measurements: <numbers with how they were obtained>\n"
    "corrections: <concrete changes, or none>\n"
    "assumptions: <unresolved assumptions, or none>\n"
    "Rule: if you could not successfully read a supplied image, status is "
    "UNVERIFIED — never PASS on a path you did not open."
)

_PROFILES: dict[str, ProfileSpec] = {
    "design": ProfileSpec(
        sandbox="read-only", effort="medium",
        features={"image_generation": False, "view_image": True,
                  "browser_use": True, "computer_use": False, "js_repl": False},
    ),
    "concept": ProfileSpec(
        sandbox="workspace-write", effort="high",
        features={"image_generation": True, "view_image": True,
                  "browser_use": False, "computer_use": False, "js_repl": False},
        skills_on=("imagegen", "photoreal-asset-factory", "terrain-geology-assets"),
        brief=("Allowed skills for this task: image generation (imagegen), "
               "photoreal-asset-factory, terrain-geology-assets. Every other "
               "skill/plugin is out of scope — do not use it."),
    ),
    "blender": ProfileSpec(
        sandbox="workspace-write", effort="high",
        features={"image_generation": False, "view_image": False,
                  "browser_use": False, "computer_use": False, "js_repl": False},
        skills_on=("photoreal-asset-factory", "terrain-geology-assets"),
        brief=("Allowed skills for this task: photoreal-asset-factory, "
               "terrain-geology-assets, and headless Blender via the shell. "
               "Every other skill/plugin is out of scope — do not use it."),
    ),
    "verify": ProfileSpec(
        sandbox="read-only", effort="high",
        features={"image_generation": False, "view_image": True,
                  "browser_use": False, "computer_use": False, "js_repl": False},
        brief=_VERDICT_BRIEF,
    ),
    "direct": ProfileSpec(
        sandbox="read-only", effort="medium",
        features={"image_generation": False, "view_image": False,
                  "browser_use": False, "computer_use": False, "js_repl": False},
        brief=("Inspect read-only and return a structured specification "
               "(dimensions, materials, references, targets). Do not write."),
    ),
}


def resolve_profile(purpose: str, profile: str | None) -> tuple[str | None, str | None]:
    """(profile_name, error). Explicit `profile=` wins; else map from purpose."""
    if profile:
        if profile not in _PROFILES:
            return None, f"unknown profile {profile!r}; one of {sorted(_PROFILES)}"
        return profile, None
    name = _PURPOSE_TO_PROFILE.get(purpose)
    if name is None:
        return None, (f"purpose {purpose!r} has no profile mapping; pass an explicit "
                      f"profile= ({sorted(_PROFILES)})")
    return name, None


def _profile_config_args(spec: ProfileSpec) -> list[str]:
    """The deterministic, PURE `-c` overrides a reviewer asserts: approval_policy
    plus the feature allowlist. The MCP-server disable set is DISCOVERED at call
    time (discover_mcp_servers → mcp_disable_args) and appended by consult(), so it
    is not part of this pure function — a static server list is exactly the hole
    c-9f87c3d102 flagged.

    NB skills: codex 0.153.4 `exec` REJECTS `-c skills.config=[…]` (exits 1 with
    `in skills.config.path`), while `codex mcp list` / `debug prompt-input` accept
    it and do not prune anyway. So skill toggles are NOT emitted to the exec argv —
    they live in the manifest (`skills`) as the recorded intent, and the profile
    brief names the allowed skills at the prompt level. Capability gating is via
    the MCP-server + feature allowlist, the sandbox, and the boundary scan."""
    args: list[str] = ["-c", "approval_policy=never"]
    for feat in _MANAGED_FEATURES:
        args += ["-c", f"features.{feat}={'true' if spec.features[feat] else 'false'}"]
    return args


def discover_mcp_servers(codex: str, timeout_s: int = 30) -> tuple[list[dict[str, str]], str | None]:
    """Enumerate every MCP server codex would load, via `codex mcp list --json`.
    Returns ([{name, transport}], None) or ([], error). FAIL-CLOSED: a non-zero
    exit or unparseable output is an error the caller must not launch through — the
    consult refuses to run rather than leave an unknown server live. A valid empty
    array is not an error (the unreal-mcp floor still applies). (criterion c-9f87c3d102)"""
    try:
        proc = subprocess.run(
            [codex, "mcp", "list", "--json"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", timeout=timeout_s, check=False)
    except (OSError, subprocess.SubprocessError) as e:
        return [], f"`codex mcp list --json` could not run: {e}"
    if proc.returncode != 0:
        tail = _last_nonempty_line((proc.stdout or "") + "\n" + (proc.stderr or ""))
        return [], f"`codex mcp list --json` exited {proc.returncode}: {tail}"
    try:
        data = json.loads(proc.stdout or "")
    except ValueError as e:
        return [], f"`codex mcp list --json` output was not JSON: {e}"
    if not isinstance(data, list):
        return [], "`codex mcp list --json` did not return a JSON array"
    servers: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            return [], "`codex mcp list --json` array held a non-object entry"
        name = item.get("name")
        if not isinstance(name, str) or not name:
            return [], "`codex mcp list --json` entry has no name"
        t = item.get("transport")
        transport = str(t.get("type") or "") if isinstance(t, dict) else ""
        servers.append({"name": name, "transport": transport})
    return servers, None


def mcp_disable_args(servers: list[dict[str, str]]) -> list[str]:
    """`-c` overrides that disable EVERY discovered server, plus the unreal-mcp
    floor if discovery missed it. A stdio server takes a stub `command` + a
    `.enabled=false` (a bare disable on a plugin-injected stdio server with no
    config.toml table fails codex bootstrap with "invalid transport"); a url/http
    server takes a bare `.enabled=false` (a command on a url server is rejected as
    "url is not supported for stdio"). Order-stable per input. PURE."""
    args: list[str] = []
    seen: set[str] = set()
    for s in servers:
        name = s["name"]
        seen.add(name)
        if s.get("transport") == "stdio":
            args += ["-c", f'mcp_servers.{name}.command="{_MCP_STUB_COMMAND}"',
                     "-c", f"mcp_servers.{name}.enabled=false"]
        else:
            args += ["-c", f"mcp_servers.{name}.enabled=false"]
    for floor in _MCP_FLOOR:
        if floor not in seen:
            args += ["-c", f"mcp_servers.{floor}.enabled=false"]
    return args


def mcp_disabled_names(servers: list[dict[str, str]]) -> list[str]:
    """The set of server names disabled: every discovered name plus the floor.
    In normal operation (unreal-mcp discovered) this equals the discovered set."""
    return sorted({s["name"] for s in servers} | set(_MCP_FLOOR))


def profile_skill_intent(spec: ProfileSpec) -> dict[str, bool]:
    """The recorded (manifest) skill allowlist for a profile: every managed skill
    off by default, the profile's few flipped on. Not enforceable via -c on
    0.153.4 — recorded intent + prompt-level scoping only. PURE."""
    return {name: (name in spec.skills_on) for name in _MANAGED_SKILLS}


_BIN_ENV = "EDP8_CODEX_BIN"
_MODEL_ENV = "EDP8_SOL_MODEL"
_LOG_DIR_ENV = "EDP8_SOL_LOG_DIR"
_UE_ROOT_ENV = "EDP8_UE_PROJECT_ROOT"
_DEFAULT_BIN = "codex"
_DEFAULT_MODEL = "gpt-6-astra"  # matches claude/.bridge.json's "sol" delegate (2026-09-05: Astra)
_DEFAULT_UE_ROOT = r"C:\Projects\SpaceTravel"
#: only this subtree of the UE project may be a write_dir (criterion c-198d217e38)
_UE_ALLOWLIST_SUBPATH = ("Content", "Concepts")


def _log_dir() -> Path:
    override = os.environ.get(_LOG_DIR_ENV, "").strip()
    if override:
        return Path(override)
    home = os.environ.get("EDP8_HOME") or str(Path(__file__).resolve().parents[2])
    return Path(home) / ".sol"


def _resolve_bin() -> str:
    """EDP8_CODEX_BIN → PATH `codex` → the ChatGPT app's codex.exe under ~/.codex
    (plugins/.plugin-appserver first, then the first codex.exe found)."""
    import shutil

    override = os.environ.get(_BIN_ENV, "").strip()
    if override:
        return override
    found = shutil.which("codex") or shutil.which("codex.cmd")
    if found:
        # npm hands back a .cmd shim; run the REAL exe behind it so the prompt
        # never passes through cmd.exe quoting.
        if Path(found).suffix.lower() != ".exe":
            pkg_root = Path(found).resolve().parent / "node_modules" / "@openai"
            for exe in sorted(pkg_root.rglob("codex.exe")) if pkg_root.is_dir() else []:
                if exe.parent.name == "bin":
                    return str(exe)
        return found
    root = Path(os.environ.get("EDP8_CODEX_HOME") or (Path.home() / ".codex"))
    preferred = root / "plugins" / ".plugin-appserver" / "codex.exe"
    if preferred.is_file():
        return str(preferred)
    if root.is_dir():
        for exe in sorted(root.rglob("codex.exe")):
            return str(exe)
    return _DEFAULT_BIN


def _build_argv(codex: str, *, prompt: str, workdir: str, last_message_file: str,
                model: str, effort: str, sandbox: str = "read-only",
                config_args: list[str] | None = None,
                images: list[str] | None = None,
                resume_thread: str | None = None) -> list[str]:
    """Fresh turn:  `codex exec <globals> [-i img...] -- <prompt>`
    Resume turn: `codex exec <globals> resume [-i img]* -- <thread_id> <prompt>`

    Globals (incl. the profile `-c` overrides) precede the subcommand; the prompt
    is the LAST positional behind `--` so a leading '-' is never parsed as a flag.
    On a FRESH turn `-i` is variadic and must be terminated by `--`; on RESUME `-i`
    is per-flag and sits AFTER the `resume` subcommand. PURE — no IO."""
    imgs = [i for i in (images or []) if i]
    argv = [codex, "exec", "--skip-git-repo-check",
            "-C", workdir, "-s", sandbox, "--json", "--color", "never",
            "-o", last_message_file]
    if model:
        argv += ["-m", model]
    if effort:
        argv += ["-c", f"model_reasoning_effort={effort}"]
    argv += list(config_args or [])
    if resume_thread:
        argv.append("resume")
        for img in imgs:
            argv += ["-i", img]
        argv += ["--", resume_thread, prompt]
    else:
        if imgs:
            argv.append("-i")
            argv += imgs
        argv += ["--", prompt]
    return argv


def parse_thread_id(jsonl_text: str) -> str | None:
    """Pull the Codex thread id out of the `--json` event stream — the
    `{"type":"thread.started","thread_id":"…"}` event (first line normally).
    Defensive: never raises on lines that are not JSON or not that event."""
    for line in jsonl_text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict) and ev.get("type") == "thread.started":
            tid = ev.get("thread_id") or ev.get("session_id")
            if isinstance(tid, str) and tid:
                return tid
    return None


def parse_provider_model(jsonl_text: str) -> str | None:
    """The model the provider actually reports running, from the `--json` stream —
    distinct from the requested model. First non-empty `model` field wins."""
    for line in jsonl_text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        for key in ("model", "model_slug"):
            v = ev.get(key)
            if isinstance(v, str) and v:
                return v
        # some builds nest it under a session/turn object
        for holder in ("session", "turn", "thread", "data"):
            sub = ev.get(holder)
            if isinstance(sub, dict):
                v = sub.get("model") or sub.get("model_slug")
                if isinstance(v, str) and v:
                    return v
    return None


def _last_nonempty_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line:
            return line
    return "codex produced no output"


def _write_log(log_path: Path, raw: str) -> None:
    try:
        log_path.write_text(raw, encoding="utf-8")
    except OSError:
        pass


# ------------------------------------------------------------- asset boundary

def _realpath(p: str | Path) -> Path:
    """Resolve junctions/symlinks. os.path.realpath follows Windows junctions;
    Path.resolve() does too but may add a \\\\?\\ prefix — normalise via realpath."""
    return Path(os.path.realpath(str(p)))


def _under(child: Path, parent: Path) -> bool:
    """child == parent or child is inside parent (case-insensitive on Windows via
    PureWindowsPath comparison)."""
    try:
        return child == parent or child.is_relative_to(parent)
    except (ValueError, OSError):
        return False


def ue_project_root() -> Path:
    return Path(os.environ.get(_UE_ROOT_ENV) or _DEFAULT_UE_ROOT)


def check_write_dir_boundary(write_dir: str) -> str | None:
    """Return an error string if `write_dir` is inside / equal to / a parent
    (ancestor) of the UE project root — the only allowlisted exception being the
    Content/Concepts asset subtree. Junctions/symlinks are resolved first. None
    means the directory is safe to write into. (criterion c-198d217e38)"""
    wd = _realpath(write_dir)
    ue = _realpath(ue_project_root()) if ue_project_root().exists() else Path(
        os.path.normpath(str(ue_project_root())))
    allow = ue.joinpath(*_UE_ALLOWLIST_SUBPATH)
    if _under(wd, allow):
        return None  # explicitly allowlisted asset subtree
    if _under(wd, ue) or _under(ue, wd):
        return (f"write_dir {wd} is inside/equal/parent of the UE project root {ue}; "
                f"assets must land outside the UE tree — only {allow} is allowlisted "
                f"(set {_UE_ROOT_ENV} to change the protected root)")
    return None


def _snapshot_mtimes(roots: list[Path]) -> dict[str, int]:
    """{normcased-realpath: mtime_ns} for every file under each root. Best-effort;
    unreadable entries are skipped."""
    snap: dict[str, int] = {}
    for r in roots:
        if not r.exists():
            continue
        for f in r.rglob("*"):
            try:
                if f.is_file():
                    snap[os.path.normcase(str(_realpath(f)))] = f.stat().st_mtime_ns
            except OSError:
                continue
    return snap


def _writes_outside(write_dir: str | None, before: dict[str, int],
                    roots: list[Path]) -> list[str]:
    """Files under `roots` created/modified since `before` that escaped the
    permitted zones — i.e. writes into the PROTECTED UE tree (the root minus the
    allowlisted Content/Concepts subtree) and outside write_dir. The allowlist is
    excluded so the ordinary asset-drop location (and other agents' concurrent
    writes there) does not false-positive. (criterion c-198d217e38)"""
    wd = _realpath(write_dir) if write_dir else None
    allow = _realpath(ue_project_root().joinpath(*_UE_ALLOWLIST_SUBPATH))
    after = _snapshot_mtimes(roots)
    escaped: list[str] = []
    for path, mt in after.items():
        if before.get(path) == mt:
            continue
        p = Path(path)
        if wd is not None and _under(p, wd):
            continue
        if _under(p, allow):
            continue  # allowlisted Content/Concepts subtree is permitted
        escaped.append(path)
    return sorted(escaped)


# ---------------------------------------------------------- write-fence (S0d)
#
# The read-only codex sandbox IS ENFORCED on this Windows build (S0d MEASURED, run
# 20260905T171023Z-4e638d11: Astra's write was OS-refused "read-only filesystem
# permissions"; the origin escape 20260905T163527Z-707bc6ef could NOT be reproduced)
# — see guides/sol-pairing.md, the statement of record. This fence is therefore
# DEFENSE-IN-DEPTH: the real boundary for a future codex whose sandbox regresses, or
# a workspace-write profile that escapes its write_dir. S0c failed closed on an escape
# but discarded the answer and left the rogue file for a human to delete. S0d
# remediates: new untracked files are deleted, modified tracked
# files are restored with `git checkout --`, every action is recorded with sha256,
# and the run STILL fails closed (code=boundary) while returning the recovered answer.
# (criteria c-fe4f824d82, c-16ae18056e; architect handoff m-962582ae04)


def _sha256_file(p: Path) -> str | None:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return None


def _git(root: Path, *args: str, timeout_s: int = 30) -> subprocess.CompletedProcess[str] | None:
    """Run `git -C <root> <args>` with empty stdin. None on a launch failure
    (git missing / OS error) so callers can fall back cleanly."""
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", timeout=timeout_s, check=False)
    except (OSError, subprocess.SubprocessError):
        return None


def _is_git_repo(root: Path) -> bool:
    if not root.exists():
        return False
    p = _git(root, "rev-parse", "--is-inside-work-tree")
    return bool(p) and p.returncode == 0 and p.stdout.strip() == "true"


def git_status_map(root: Path) -> dict[str, str] | None:
    """{normcased-realpath: 2-char porcelain status} for every dirty path in the
    work tree, or None if `root` is not a git repo / git could not run.

    Uses `git status --porcelain -z -uall`: **gitignored build outputs
    (Binaries/, Intermediate/, Saved/, DerivedDataCache/, .vs/) are excluded by
    porcelain** (they never appear), and `-uall` lists each untracked FILE rather
    than collapsing a new directory to `dir/`, so the fence can delete files, not
    trees. `??` = untracked; any other code = a tracked change. (c-1457650970)"""
    if not _is_git_repo(root):
        return None
    p = _git(root, "status", "--porcelain", "-z", "-uall")
    if not p or p.returncode != 0:
        return None
    out: dict[str, str] = {}
    toks = p.stdout.split("\0")
    i = 0
    while i < len(toks):
        entry = toks[i]
        if not entry:
            i += 1
            continue
        xy, rel = entry[:2], entry[3:]
        if rel:
            abs_path = os.path.normcase(os.path.realpath(str(root / rel)))
            out[abs_path] = xy
        # a rename/copy entry (R./C.) is followed by its source path token — skip it
        if xy and xy[0] in ("R", "C"):
            i += 1
        i += 1
    return out


#: jsonl item types whose payload names files this run's codex actually wrote/ran.
_LOG_WRITE_HINTS = ("command", "patch", "file", "write", "shell", "exec")


def codex_log_corpus(run_log: str) -> str:
    """The concatenated text of every write/apply_patch/shell event in a run's
    codex `--json` stream — the primary ATTRIBUTION signal (c-fe4f824d82). We take
    each `command_execution.command` string plus the raw payload of any apply_patch/
    file/write item, so a path this run's codex named is discoverable; we DELIBERATELY
    exclude `aggregated_output` (a shell's stdout could echo a concurrent seat's
    filename and mis-attribute it). Lowercased for case-insensitive matching. PURE."""
    parts: list[str] = []
    for line in run_log.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        item = ev.get("item") if isinstance(ev.get("item"), dict) else ev
        cmd = item.get("command")
        if isinstance(cmd, str):
            parts.append(cmd)
        itype = str(item.get("type") or "")
        if any(h in itype for h in _LOG_WRITE_HINTS) and itype != "command_execution":
            # a patch/file/write item — its whole payload carries the path(s)
            try:
                parts.append(json.dumps(item, ensure_ascii=False))
            except (TypeError, ValueError):
                pass
    return "\n".join(parts).lower()


def _log_attributes(path: str, corpus: str) -> bool:
    """True if this run's codex log names `path` (by basename) in a write/shell/patch
    event. Basename match: commands reference a file by name in whatever slash form
    and cwd-relativity the shell used. (c-fe4f824d82)"""
    base = os.path.basename(path)
    return bool(base) and base.lower() in corpus


def fence_remediate(write_dir: str | None, pre_status: dict[str, str] | None,
                    before_mtimes: dict[str, int], ue_root: Path,
                    run_log: str = "") -> dict[str, Any]:
    """Attribute and revert writes into the protected UE tree after a run.

    ATTRIBUTION (c-fe4f824d82): auto-delete/restore is allowed ONLY for a path THIS
    run's codex jsonl names in a write/apply_patch/shell event (`run_log`). Every
    other dirty path — a pre-dirty file another seat was already editing
    (c-1457650970), or one nobody's log claims — is reported and LEFT UNTOUCHED. So a
    concurrent seat's own file is never deleted, which was the S10 false positive.

    GIT TREE (pre_status not None). For each dirty path outside write_dir /
    Content-Concepts (gitignored build output never appears in porcelain, so is never
    an escape): pre-dirty ⇒ `pre_dirty_concurrent`; else log-attributed ⇒ `??`
    deleted / tracked `git checkout --` restored; else ⇒ `unattributed_concurrent`.

    NON-GIT TREE (pre_status is None) ⇒ FALLBACK: the mtime scan is the only signal,
    still gated by log attribution → a log-named NEW file is deleted; a log-named
    pre-existing file cannot be restored (no git) so is left; anything unattributed
    is left.

    Each entry: {path, action, attribution(log|pre_dirty|none), tracked, pre_dirty,
    sha256|pre_sha256/post_sha256, ok, detail?}. Returns {git, escapes, note}."""
    root = _realpath(ue_root) if ue_root.exists() else Path(os.path.normpath(str(ue_root)))
    wd = _realpath(write_dir) if write_dir else None
    allow = _realpath(root.joinpath(*_UE_ALLOWLIST_SUBPATH))
    corpus = codex_log_corpus(run_log)
    report: list[dict[str, Any]] = []

    def _in_allowed_zone(p: Path) -> bool:
        return (wd is not None and _under(p, wd)) or _under(p, allow)

    if pre_status is not None:
        post = git_status_map(root) or {}
        for path, xy in sorted(post.items()):
            p = Path(path)
            if _in_allowed_zone(p):
                continue
            tracked = xy != "??"
            rogue_sha = _sha256_file(p)
            if path in pre_status:
                report.append({"path": path, "action": "pre_dirty_concurrent",
                               "attribution": "pre_dirty", "tracked": tracked,
                               "pre_dirty": True, "status": xy, "sha256": rogue_sha,
                               "ok": True})
            elif not _log_attributes(path, corpus):
                report.append({"path": path, "action": "unattributed_concurrent",
                               "attribution": "none", "tracked": tracked,
                               "pre_dirty": False, "status": xy, "sha256": rogue_sha,
                               "ok": True})
            elif not tracked:
                try:
                    if p.exists():
                        p.unlink()
                    report.append({"path": path, "action": "deleted_new",
                                   "attribution": "log", "tracked": False,
                                   "pre_dirty": False, "sha256": rogue_sha,
                                   "ok": not p.exists()})
                except OSError as e:
                    report.append({"path": path, "action": "delete_failed",
                                   "attribution": "log", "tracked": False,
                                   "pre_dirty": False, "sha256": rogue_sha,
                                   "ok": False, "detail": str(e)})
            else:
                r = _git(root, "checkout", "--", str(p))
                ok = bool(r) and r.returncode == 0
                report.append({"path": path, "action": "restored_tracked",
                               "attribution": "log", "tracked": True,
                               "pre_dirty": False, "pre_sha256": rogue_sha,
                               "post_sha256": _sha256_file(p), "ok": ok,
                               "detail": ("" if ok else _last_nonempty_line(
                                   ((r.stdout if r else "") or "") + "\n"
                                   + ((r.stderr if r else "") or "")
                                   or "git checkout could not run"))})
        return {"git": True, "escapes": report, "note": ""}

    # non-git fallback: mtime scan, still gated by log attribution
    escaped = _writes_outside(write_dir, before_mtimes, [root])
    for path in escaped:
        p = Path(path)
        rogue_sha = _sha256_file(p)
        pre_existing = before_mtimes.get(path) is not None
        if not _log_attributes(path, corpus):
            report.append({"path": path, "action": "unattributed_concurrent",
                           "attribution": "none", "tracked": None,
                           "pre_dirty": pre_existing, "sha256": rogue_sha, "ok": True,
                           "detail": "not named in this run's codex log; left untouched"})
        elif pre_existing:
            report.append({"path": path, "action": "left_modified_no_git",
                           "attribution": "log", "tracked": None, "pre_dirty": True,
                           "sha256": rogue_sha, "ok": False,
                           "detail": ("UE root is not a git repo; a modified pre-existing "
                                      "file cannot be restored (delete-new-only fallback)")})
        else:
            try:
                if p.exists():
                    p.unlink()
                report.append({"path": path, "action": "deleted_new", "attribution": "log",
                               "tracked": None, "pre_dirty": False, "sha256": rogue_sha,
                               "ok": not p.exists()})
            except OSError as e:
                report.append({"path": path, "action": "delete_failed", "attribution": "log",
                               "tracked": None, "pre_dirty": False, "sha256": rogue_sha,
                               "ok": False, "detail": str(e)})
    note = ("UE root is not a git repo — fallback: log-attributed new files deleted, "
            "modified/unattributed files left (mtime signal only)")
    return {"git": False, "escapes": report, "note": note}


def _real_escapes(fence: dict[str, Any]) -> list[dict[str, Any]]:
    """Escapes ATTRIBUTED to this run (its codex log named them) and acted on — the
    only ones that fail a run closed. pre_dirty / unattributed concurrent paths
    (another seat) never count. (c-fe4f824d82, c-1457650970)"""
    return [e for e in fence["escapes"]
            if e["action"] in ("deleted_new", "restored_tracked", "delete_failed",
                               "left_modified_no_git")]


# ---------------------------------------------------------------- evidence

def image_evidence(images: list[str]) -> tuple[list[dict[str, Any]], str | None]:
    """Decode every image with PIL and record dimensions + sha256. Returns
    (records, error): a non-None error (undecodable image) means the caller must
    FAIL before codex runs. (criterion c-7001dd4631)"""
    if not images:
        return [], None
    try:
        from PIL import Image  # noqa: PLC0415
    except ImportError:
        return [], ("Pillow (PIL) is required to validate images= but is not "
                    "installed; `uv add pillow`")
    records: list[dict[str, Any]] = []
    for img in images:
        p = Path(img)
        try:
            data = p.read_bytes()
        except OSError as e:
            return [], f"image {img!r} could not be read: {e}"
        try:
            with Image.open(p) as im:
                im.verify()  # raises on a corrupt/undecodable file
            with Image.open(p) as im2:
                w, h = im2.size
                fmt = im2.format
        except Exception as e:  # PIL raises a grab-bag; treat any as undecodable
            return [], f"image {img!r} is not a decodable image ({e.__class__.__name__}: {e})"
        records.append({"path": str(p), "sha256": hashlib.sha256(data).hexdigest(),
                        "width": w, "height": h, "format": fmt, "bytes": len(data)})
    return records, None


_VERDICT_STATUSES = ("PASS", "FAIL", "UNVERIFIED")


def parse_verdict(answer: str, *, images_decoded: int) -> dict[str, Any]:
    """Parse the structured VERDICT block from a verify answer. Absent block, or
    a PASS/FAIL claimed with zero successfully-decoded images, ⇒ UNVERIFIED (a
    path with no successful image read is never a PASS). (criterion c-7001dd4631)"""
    import re

    def _section(name: str) -> str:
        m = re.search(rf"^\s*{name}\s*:\s*(.*?)(?=^\s*\w[\w ]*:\s|\Z)",
                      answer, re.I | re.M | re.S)
        return (m.group(1).strip() if m else "")

    status_m = re.search(r"^\s*status\s*:\s*(PASS|FAIL|UNVERIFIED)\b",
                         answer, re.I | re.M)
    has_block = bool(re.search(r"^\s*VERDICT\s*$", answer, re.I | re.M)) or bool(status_m)
    if not status_m:
        return {"status": "UNVERIFIED", "parsed": False,
                "reason": "no structured VERDICT block / status line in the answer",
                "inspected": "", "findings": "", "measurements": "",
                "corrections": "", "assumptions": ""}
    status = status_m.group(1).upper()
    if status in ("PASS", "FAIL") and images_decoded == 0:
        status = "UNVERIFIED"
    return {"status": status, "parsed": has_block,
            "inspected": _section("inspected"),
            "findings": _section("findings"),
            "measurements": _section("measurements"),
            "corrections": _section("corrections"),
            "assumptions": _section("assumptions")}


# ------------------------------------------------------------- codex runner

def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the codex process AND its children — a plain proc.kill() on Windows
    leaves the spawned helper tree (node_repl, blender, image_gen) alive."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=30, check=False)
        except Exception:
            pass
    else:
        try:
            os.killpg(os.getpgid(proc.pid), 9)  # type: ignore[attr-defined]
        except Exception:
            pass
    try:
        proc.kill()
    except Exception:
        pass


def _run_codex(argv: list[str], timeout_s: int) -> tuple[str, int | None, bool]:
    """Run codex, merging stderr into stdout (the real error lands on stderr),
    empty stdin (else the CLI hangs forever). Returns (raw, exit_code, timed_out);
    a timeout kills the whole child process tree and returns whatever was captured."""
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", **kwargs)
    try:
        raw, _ = proc.communicate(timeout=timeout_s)
        return raw or "", proc.returncode, False
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        try:
            raw, _ = proc.communicate(timeout=30)
        except Exception:
            raw = ""
        return raw or "", None, True


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ------------------------------------------------------------------ consult

def consult(purpose: Purpose, question: str, context: str = "",
            files: list[str] | None = None, timeout_s: int = 600,
            write_dir: str | None = None, images: list[str] | None = None,
            thread_id: str | None = None, model: str | None = None,
            profile: str | None = None) -> dict[str, Any]:
    """Ask the consultant one question under a purpose PROFILE and return the
    standard envelope. Never retries, never glosses a failure as a quota cap.

    `profile` (design|concept|blender|verify|direct) fixes the codex-exec
    invocation — sandbox, approval_policy=never, effort, and the enabled/disabled
    MCP-server + feature set. Omit it and the profile is derived from `purpose`
    (adversary/second_opinion→design, creative→concept, visual→verify,
    build→blender). Only concept/blender may write; passing write_dir to a
    read-only profile is an error (use profile=concept|blender).

    `write_dir` (concept/blender only) roots a workspace-write sandbox. It may
    never be inside/equal/parent of the UE project root (junctions resolved);
    after the run the bridge scans the protected UE tree and fails on any escape.

    `images` are decoded (PIL) and hashed BEFORE the run — an undecodable image
    fails the call. `thread_id` resumes a prior session. A run that produces no
    final answer FAILS CLOSED. Every run writes a manifest beside the log."""
    if purpose not in _PREAMBLES:
        return {"ok": False,
                "error": {"code": "exit", "message": f"unknown purpose {purpose!r}"},
                "hint": f"purpose must be one of {sorted(_PREAMBLES)}"}
    profile_name, perr = resolve_profile(purpose, profile)
    if perr:
        return {"ok": False, "error": {"code": "exit", "message": perr},
                "hint": "pass a valid profile= or a purpose with a mapping"}
    spec = _PROFILES[profile_name]

    if spec.writes and not write_dir:
        return {"ok": False,
                "error": {"code": "exit",
                          "message": f"profile {profile_name!r} writes assets and needs a write_dir"},
                "hint": "pass write_dir=<a directory OUTSIDE the UE project>"}
    if write_dir and not spec.writes:
        return {"ok": False,
                "error": {"code": "exit",
                          "message": f"profile {profile_name!r} is read-only; write_dir is not allowed"},
                "hint": "use profile=concept or profile=blender to deliver files"}
    if write_dir and not Path(write_dir).is_dir():
        return {"ok": False,
                "error": {"code": "exit", "message": f"write_dir {write_dir!r} is not a directory"},
                "hint": "create it first, or pass the directory that holds the files to edit"}
    if write_dir:
        boundary_err = check_write_dir_boundary(write_dir)
        if boundary_err:
            return {"ok": False,
                    "error": {"code": "boundary", "message": boundary_err},
                    "hint": "deliver assets outside the UE project tree"}

    images = [i for i in (images or []) if i]
    for img in images:
        if not Path(img).is_file():
            return {"ok": False,
                    "error": {"code": "exit", "message": f"image {img!r} does not exist"},
                    "hint": "attach existing files (png/jpg); attaching is the only way an image reaches Sol"}
    img_records, img_err = image_evidence(images)
    if img_err:
        return {"ok": False, "error": {"code": "image", "message": img_err},
                "hint": "attach a decodable png/jpg; the bridge validates images before the run"}
    thread_id = (thread_id or "").strip() or None

    parts = [_PREAMBLES[purpose], "", (question or "").strip()]
    if context.strip():
        parts += ["", "Context:", context.strip()]
    if files:
        parts += ["", "Relevant files (read them from the working tree):"]
        parts += [f"- {f}" for f in files]
    if write_dir:
        parts += ["", f"You have WRITE access to {write_dir} (and only there): deliver files "
                      f"into it or edit in place as asked."]
    if spec.brief:
        parts += ["", spec.brief]
    prompt = "\n".join(parts)

    codex = _resolve_bin()
    requested_model = (model or "").strip() or os.environ.get(_MODEL_ENV, "").strip() or _DEFAULT_MODEL

    run_id = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:8]}"
    log_dir = _log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{run_id}.jsonl"
    manifest_path = log_dir / f"{run_id}.manifest.json"
    last_msg = log_dir / f".last-message-{run_id}.txt"

    # Discover-and-disable the MCP surface at call time (fail-closed). A static
    # denylist misses plugin-injected servers (cua_repl) — c-9f87c3d102.
    discovered, disc_err = discover_mcp_servers(codex)
    if disc_err:
        try:
            manifest_path.write_text(json.dumps(
                {"run_id": run_id, "started_at": _now(), "profile": profile_name,
                 "status": "mcp_discovery_failed", "error": disc_err}, indent=2),
                encoding="utf-8")
        except OSError:
            pass
        return {"ok": False,
                "error": {"code": "mcp_discovery", "message": disc_err},
                "value": {"run_id": run_id, "manifest": str(manifest_path)},
                "hint": "`codex mcp list --json` must succeed so every server can be "
                        "disabled; the consult is fail-closed (no launch with an "
                        "unknown MCP surface). Check `codex login` and the CLI version"}
    discovered_names = sorted(s["name"] for s in discovered)
    disabled_names = mcp_disabled_names(discovered)
    config_args = _profile_config_args(spec) + mcp_disable_args(discovered)
    argv = _build_argv(codex, prompt=prompt, workdir=write_dir or os.getcwd(),
                       last_message_file=str(last_msg), model=requested_model,
                       effort=spec.effort, sandbox=spec.sandbox,
                       config_args=config_args, images=images, resume_thread=thread_id)

    manifest: dict[str, Any] = {
        "run_id": run_id, "started_at": _now(), "profile": profile_name,
        "purpose": purpose, "requested_model": requested_model, "provider_model": None,
        "sandbox": spec.sandbox, "effort": spec.effort, "approval_policy": "never",
        "write_dir": write_dir, "resumed_thread_id": thread_id,
        "mcp_discovered": discovered_names,
        "mcp_disabled": disabled_names,
        "mcp_servers_disabled": disabled_names,  # back-compat alias for the disabled set
        "features": dict(spec.features),
        "skills": profile_skill_intent(spec),
        "skills_note": ("recorded intent only — codex 0.153.4 `exec` rejects "
                        "`-c skills.config` and does not prune the skill list; "
                        "capability gating is via the MCP/feature allowlist, sandbox "
                        "and boundary scan, plus the prompt-level allowed-skills line"),
        "images": img_records, "config_args": config_args,
        "image_gen_retried": False,  # image_gen is NEVER auto-retried
    }

    def _save_manifest() -> None:
        try:
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        except OSError:
            pass

    # Snapshot the protected UE tree immediately before launch so the post-run
    # fence can ATTRIBUTE each dirty path: git status is the primary signal (a path
    # already dirty here is a concurrent seat's edit, never ours), the mtime scan a
    # secondary signal for a non-git tree. Cheap when the root does not exist.
    boundary_before = _snapshot_mtimes([ue_project_root()])
    pre_status = git_status_map(ue_project_root())
    start = time.monotonic()
    try:
        raw, exit_code, timed_out = _run_codex(argv, timeout_s)
    except (OSError, ValueError) as e:
        manifest["error"] = f"launch failed: {e}"
        _save_manifest()
        return {"ok": False,
                "error": {"code": "unavailable", "message": f"could not launch {codex!r}: {e}"},
                "hint": f"check {_BIN_ENV} and that `codex` is on PATH (`codex login` may be required)"}

    elapsed = time.monotonic() - start
    _write_log(log_path, raw)
    # provider-reported model, recorded separately from the requested one; codex
    # 0.153.4 exec `--json` carries none, so "unavailable" — never fabricated.
    provider_model = parse_provider_model(raw) or "unavailable"
    manifest["provider_model"] = provider_model
    manifest["elapsed_s"] = round(elapsed, 3)
    out_thread = parse_thread_id(raw) or thread_id
    manifest["thread_id"] = out_thread

    answer = ""
    if last_msg.is_file():
        try:
            answer = last_msg.read_text(encoding="utf-8").strip()
        finally:
            try:
                last_msg.unlink()
            except OSError:
                pass

    # Post-run write-fence: attribute every dirty path in the protected UE tree.
    # Concurrent seats' edits (pre-dirty) and gitignored build outputs are reported
    # but never touched; only THIS run's escapes (clean→dirty) are reverted, and even
    # then the answer is RECOVERED, never discarded. A concurrent-only run succeeds.
    fence = fence_remediate(write_dir, pre_status, boundary_before, ue_project_root(),
                            run_log=raw)
    real = _real_escapes(fence)
    concurrent = [e for e in fence["escapes"]
                  if e["action"] in ("pre_dirty_concurrent", "unattributed_concurrent")]
    manifest["fence"] = fence
    manifest["writes_outside_write_dir"] = [e["path"] for e in real]      # attributed escapes only
    manifest["concurrent_writes"] = [e["path"] for e in concurrent]

    if timed_out:
        manifest["status"] = "timeout"
        _save_manifest()
        val: dict[str, Any] = {"thread_id": out_thread, "run_id": run_id,
                               "manifest": str(manifest_path)}
        if fence["escapes"]:
            val["escaped"] = [e["path"] for e in real]
            val["escapes"] = fence["escapes"]
            val["fence"] = fence
        return {"ok": False,
                "error": {"code": "timeout",
                          "message": f"codex exceeded {timeout_s}s and its process tree was killed "
                                     f"(last output: {_last_nonempty_line(raw)})"},
                "value": val,
                "hint": "resume with thread_id when ready; do not retry immediately"}

    if real:
        manifest["status"] = "boundary_violation"
        _save_manifest()
        n_restored = sum(1 for e in real if e["action"] == "restored_tracked")
        n_deleted = sum(1 for e in real if e["action"] == "deleted_new")
        escaped_paths = [e["path"] for e in real]
        val = {"run_id": run_id, "manifest": str(manifest_path), "log": str(log_path),
               "escaped": escaped_paths, "escapes": fence["escapes"], "fence": fence,
               "concurrent": [e["path"] for e in concurrent], "thread_id": out_thread}
        # The answer is preserved for reference even though the run fails closed;
        # `recovered` is only true when there actually was a final answer to keep.
        if answer:
            val.update({"answer": answer, "recovered": True,
                        "model": requested_model, "provider_model": provider_model,
                        "profile": profile_name, "elapsed_s": round(elapsed, 3)})
        return {"ok": False,
                "error": {"code": "boundary",
                          "message": (f"codex wrote {len(real)} file(s) into the protected UE tree "
                                      f"outside write_dir; the write-fence restored {n_restored} "
                                      f"tracked and removed {n_deleted} new file(s): {escaped_paths[:5]}"
                                      + (f" ({len(concurrent)} concurrent seat write(s) left "
                                         f"untouched)" if concurrent else "")
                                      + ("" if fence["git"] else
                                         " (UE root not a git repo — delete-new-only fallback)"))},
                "value": val,
                "hint": ("run fails closed (code=boundary) but the answer is RECOVERED under "
                         "value.recovered=true; the escaped writes were reverted — see "
                         "value.escapes for each path, sha256 and action")
                if answer else
                "the run is rejected; the escaped writes were reverted — see value.escapes"}

    if exit_code != 0:
        manifest["status"] = f"exit_{exit_code}"
        _save_manifest()
        return {"ok": False,
                "error": {"code": "exit",
                          "message": f"codex exited {exit_code}: {_last_nonempty_line(raw)}"},
                "value": {"run_id": run_id, "manifest": str(manifest_path), "thread_id": out_thread},
                "hint": "check `codex login` status, EDP8_SOL_MODEL, and network — "
                        "a non-zero exit is not automatically a quota cap"}

    # Fail closed: no final answer is NOT rescued by the last log line.
    if not answer:
        manifest["status"] = "no_final_answer"
        _save_manifest()
        return {"ok": False,
                "error": {"code": "no_answer",
                          "message": "codex exited 0 but produced no final answer (-o file empty); "
                                     "failing closed rather than guessing from the log tail"},
                "value": {"run_id": run_id, "manifest": str(manifest_path), "thread_id": out_thread},
                "hint": "inspect the run log; a missing final answer is treated as a failed call"}

    value: dict[str, Any] = {
        "answer": answer, "model": requested_model, "provider_model": provider_model,
        "profile": profile_name, "elapsed_s": round(elapsed, 3), "run_id": run_id,
        "log": str(log_path), "manifest": str(manifest_path), "thread_id": out_thread,
        "images_attached": len(images),
    }
    if profile_name == "verify":
        verdict = parse_verdict(answer, images_decoded=len(img_records))
        manifest["verdict"] = verdict
        value["verdict"] = verdict
    # No escape attributable to THIS run. Any dirty paths were concurrent seats'
    # in-progress edits (or gitignored build output) — the run is NOT rejected for
    # them (the S10 false-positive fix), but they are surfaced with recovered=true
    # so the caller sees them and decides. (criterion c-1457650970)
    if concurrent:
        value["recovered"] = True
        value["concurrent"] = [e["path"] for e in concurrent]
        value["escapes"] = fence["escapes"]
        value["fence"] = fence
    manifest["status"] = "ok_concurrent_writes" if concurrent else "ok"
    _save_manifest()
    hint = ("pass thread_id back on the next consult to STEER this same session"
            if out_thread else "")
    if concurrent:
        hint = (f"OK — {len(concurrent)} concurrent seat write(s) in the UE tree were "
                "left untouched (attributed pre-dirty, not this run); see value.concurrent. "
                + hint)
    return {"ok": True, "value": value, "hint": hint}
