"""What Heronry needs on a machine, how to tell it is there, and how to install it (t-08612be1b0).

ONE manifest (:data:`MANIFEST`) drives every surface that talks about prerequisites:

* ``heronry prereqs [install]`` — the one install step. ``install.ps1``/``install.sh`` call it after
  ``uv tool install``, the desktop MSI calls it on first run, the /ui/setup Install button runs it for one tool.
* ``heronry doctor`` — the prerequisites section (read-only rows).
* ``GET /v1/admin/prereqs`` — the setup wizard's "Your tools" checklist.
* the README's "What gets installed" table (:func:`markdown_table`; a test fails when the README drifts).

Detection goes through :func:`edp_contracts.toolpath.find_tool` (setting, else PATH) plus a ``--version`` probe
over a pipe; both are parameters (``which``/``probe``) so tests run on a fake PATH with fake version output.
Installs use the OS package manager (winget / brew / apt), npm for the npm-published harnesses, or the vendor's
official script; each is an argv run without a shell (a vendor script is piped through ``sh -c``). A tool with
no usable recipe on this machine is reported with its download page, never guessed at.

SQLite ships inside Python (``sqlite3``); Docker is not needed by anything at runtime (the repo's Dockerfile is
an optional way to host the board, not a prerequisite).
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import settings
from .toolpath import TOOL_KEYS, find_tool, tool_argv

# ------------------------------------------------------------------------------------------ the manifest

#: an OS key: sys.platform, with every Linux folded to "linux"
OSES = ("win32", "darwin", "linux")


@dataclass(frozen=True)
class Recipe:
    """One way to install a tool on one OS.

    manager: ``winget`` (arg = package id) · ``brew`` (arg = formula, or ``--cask <name>``) · ``apt`` (arg =
    space-separated packages) · ``npm`` (arg = package, installed ``-g``) · ``script`` (arg = the vendor's
    official install script URL, run as ``curl -fsSL <url> | sh``) · ``uv-pip`` (arg = a requirement installed
    into this Python) · ``model`` (the embedding model download, in process) · ``url`` (manual: arg is the page).
    """

    manager: str
    arg: str


@dataclass(frozen=True)
class Prereq:
    name: str
    purpose: str
    #: ``required`` · ``harness`` (at least one of the harness group; :data:`HARNESS_DEFAULT` is installed when
    #: none is present) · ``optional`` (installed only when asked; `feature` says what it unlocks) ·
    #: ``default`` (installed unless the user opts out, e.g. ``--no-embed``)
    need: str
    feature: str = ""
    #: ``cli`` (a command on PATH) · ``python`` (a module in this Python) · ``model`` (a cached model)
    kind: str = "cli"
    command: str = ""
    version_args: tuple[str, ...] = ("--version",)
    probe: bool = (
        True  # False: presence is enough (the CLI's --version is slow or interactive)
    )
    min_version: str = ""
    install: dict[str, tuple[Recipe, ...]] = field(default_factory=dict)
    needs: tuple[
        str, ...
    ] = ()  # other prerequisites the install recipes depend on (npm → node)
    docs: str = ""
    login: str = ""  # the sign-in command to run after an install (harnesses)

    @property
    def setting(self) -> str | None:
        return TOOL_KEYS.get(self.command or self.name)


def _same(r: Recipe) -> dict[str, tuple[Recipe, ...]]:
    return {o: (r,) for o in OSES}


HARNESS_DEFAULT = "claude"

MANIFEST: tuple[Prereq, ...] = (
    Prereq(
        "uv",
        "installs and updates Heronry (`heronry update`)",
        "required",
        command="uv",
        min_version="0.9",
        install={
            "win32": (Recipe("winget", "astral-sh.uv"),),
            "darwin": (Recipe("brew", "uv"),),
            "linux": (Recipe("script", "https://astral.sh/uv/install.sh"),),
        },
        docs="https://docs.astral.sh/uv/getting-started/installation/",
    ),
    Prereq(
        "git",
        "seats commit their work; on Windows it also brings Git Bash, the shell seats use",
        "required",
        command="git",
        min_version="2.30",
        install={
            "win32": (Recipe("winget", "Git.Git"),),
            "darwin": (Recipe("brew", "git"),),
            "linux": (Recipe("apt", "git"),),
        },
        docs="https://git-scm.com/downloads",
    ),
    Prereq(
        "node",
        "runs the npm-installed harnesses (codex, pi) and the codex seat's Monitor",
        "required",
        command="node",
        min_version="20",
        install={
            "win32": (Recipe("winget", "OpenJS.NodeJS.LTS"),),
            "darwin": (Recipe("brew", "node"),),
            "linux": (
                Recipe("apt", "nodejs npm"),
                Recipe("url", "https://nodejs.org/en/download"),
            ),
        },
        docs="https://nodejs.org/en/download",
    ),
    Prereq(
        "claude",
        "Claude Code, the default seat harness",
        "harness",
        feature="claude seats",
        command="claude",
        min_version="1.0",
        install={
            "win32": (Recipe("winget", "Anthropic.ClaudeCode"),),
            "darwin": (Recipe("brew", "--cask claude-code"),),
            "linux": (Recipe("script", "https://claude.ai/install.sh"),),
        },
        docs="https://code.claude.com/docs/en/setup",
        login="claude, then /login",
    ),
    Prereq(
        "codex",
        "OpenAI Codex CLI: codex seats; with it the adversary runs on codex instead of Fable",
        "harness",
        feature="codex seats and the codex adversary",
        command="codex",
        install=_same(Recipe("npm", "@openai/codex")),
        needs=("node",),
        docs="https://github.com/openai/codex#installation",
        login="codex login",
    ),
    Prereq(
        "pi",
        "Pi coding agent seats",
        "optional",
        feature="Pi seats",
        command="pi",
        probe=False,
        install=_same(Recipe("npm", "@earendil-works/pi-coding-agent")),
        needs=("node",),
        docs="https://www.npmjs.com/package/@earendil-works/pi-coding-agent",
        login="pi, then /login",
    ),
    Prereq(
        "tailscale",
        "reaches the board from teammates' machines over your tailnet",
        "optional",
        feature="remote access for teammates",
        command="tailscale",
        version_args=("version",),
        install={
            "win32": (Recipe("winget", "Tailscale.Tailscale"),),
            "darwin": (Recipe("brew", "--cask tailscale"),),
            "linux": (Recipe("script", "https://tailscale.com/install.sh"),),
        },
        docs="https://tailscale.com/download",
    ),
    Prereq(
        "embedder",
        "fastembed (ONNX) for semantic search; without it search is keyword-only",
        "default",
        feature="semantic search",
        kind="python",
        command="fastembed",
        min_version="0.3",
        install=_same(Recipe("uv-pip", "fastembed>=0.3")),
        needs=("uv",),
        docs="https://github.com/qdrant/fastembed",
    ),
    Prereq(
        "embedding model",
        "the local embedding model, downloaded once so the board does not fetch it on "
        "first search",
        "default",
        feature="semantic search",
        kind="model",
        install=_same(Recipe("model", "")),
        needs=("embedder",),
        docs="https://huggingface.co/nomic-ai/nomic-embed-text-v1.5",
    ),
)

#: shipped with Heronry itself: listed so nobody goes looking for them
BUNDLED: tuple[tuple[str, str], ...] = (
    ("python 3.12+", "uv installs the Python Heronry runs on; nothing to do"),
    (
        "sqlite",
        "the board's database engine ships inside Python (sqlite3); nothing to do",
    ),
)

#: asked about, not needed
NOT_NEEDED: tuple[tuple[str, str], ...] = (
    (
        "docker",
        "not needed: every service runs as a local process; the repo's Dockerfile is only an optional "
        "way to host the board",
    ),
)


def by_name(name: str) -> Prereq:
    for p in MANIFEST:
        if p.name == name:
            return p
    raise KeyError(
        f"unknown prerequisite {name!r} (one of {', '.join(p.name for p in MANIFEST)})"
    )


def this_os() -> str:
    return "linux" if sys.platform.startswith("linux") else sys.platform


def in_bundle() -> bool:
    """True inside Heronry Desktop (a Briefcase/PyInstaller bundle), where sys.executable is the app stub, not a
    Python (the same structural test as edp8.launcher.bundled). The bundle ships the embedder and updates through
    its installer, so it needs no uv and never pip-installs into itself (S8)."""
    if getattr(sys, "frozen", False):
        return True
    return not Path(sys.executable or "python").name.lower().startswith("python")


def need_of(p: Prereq) -> str:
    """`p.need` on this install: uv is optional inside Heronry Desktop (nothing in the app runs it)."""
    return "optional" if p.name == "uv" and in_bundle() else p.need


# ------------------------------------------------------------------------------------------ detection

Which = Callable[[Prereq], str | None]
Probe = Callable[[list[str]], str | None]


def _which(p: Prereq) -> str | None:
    return find_tool(p.command or p.name)


def _probe(argv: list[str]) -> str | None:
    """`argv` (the tool plus its version arguments) over a pipe, no shell: the first output
    line, or None when it does not start, fails or hangs."""
    try:
        r = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=15.0)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    lines = (r.stdout or r.stderr).strip().splitlines()
    return lines[0].strip() if lines else ""


def parse_version(text: str | None) -> tuple[int, ...] | None:
    """The first dotted number in `text` (``git version 2.47.1.windows.2`` → (2, 47, 1))."""
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    if not m:
        m1 = re.search(r"\bv?(\d+)\b", text or "")
        return (int(m1.group(1)),) if m1 else None
    return tuple(int(g) for g in m.groups() if g is not None)


def _at_least(have: tuple[int, ...], want: str) -> bool:
    w = parse_version(want) or ()
    n = max(len(have), len(w))
    return (have + (0,) * (n - len(have))) >= (w + (0,) * (n - len(w)))


def embed_model() -> str:
    return str(settings.get("EDP8_EMBED_MODEL"))


def embed_cache_dir() -> Path | None:
    """Where the embedding model is cached: EDP8_EMBED_CACHE; else fastembed's own FASTEMBED_CACHE_PATH; else an
    installed Heronry keeps it under its data dir (fastembed's default is a temp folder the OS may clear) and dev
    mode keeps fastembed's default (None)."""
    raw = settings.get("EDP8_EMBED_CACHE") or settings.environ_copy().get(
        "FASTEMBED_CACHE_PATH"
    )
    if raw:
        return Path(raw)
    if settings.dev_mode():
        return None
    return settings.data_dir() / "models"


def _model_cached(model: str, cache: Path | None) -> Path | None:
    import tempfile

    root = cache or Path(tempfile.gettempdir()) / "fastembed_cache"
    tail = model.split("/")[-1].lower()
    try:
        dirs = [d for d in root.iterdir() if d.is_dir() and tail in d.name.lower()]
    except OSError:
        return None
    for d in dirs:
        if next(d.rglob("*.onnx"), None) is not None:
            return d
    return None


@dataclass
class Status:
    name: str
    need: str
    feature: str
    purpose: str
    state: str  # ok | missing | outdated | off
    path: str | None = None
    version: str | None = None
    min_version: str = ""
    fix: str = ""  # what to do, in words (a command or a link)
    installable: bool = False  # a recipe can run on this machine
    login: str = ""
    docs: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect(
    p: Prereq,
    *,
    which: Which | None = None,
    probe: Probe | None = None,
    os_key: str | None = None,
    embed: bool = True,
) -> Status:
    """One prerequisite's state on this machine."""
    st = Status(
        p.name,
        need_of(p),
        p.feature or ("a command-line (uv tool) install of Heronry" if need_of(p) != p.need else ""),
        p.purpose,
        "missing",
        min_version=p.min_version,
        login=p.login,
        docs=p.docs,
    )
    if p.kind == "python":
        spec = importlib.util.find_spec(p.command)
        if spec is not None:
            st.path = str(spec.origin or "")
            try:
                st.version = importlib.metadata.version(p.command)
            except importlib.metadata.PackageNotFoundError:
                st.version = None
    elif p.kind == "model":
        found = _model_cached(embed_model(), embed_cache_dir())
        if found is not None:
            st.path, st.version = str(found), embed_model()
    else:
        st.path = (which or _which)(p)
        if st.path and p.probe:
            try:
                st.version = (probe or _probe)([*tool_argv(st.path), *p.version_args])
            except FileNotFoundError:  # a .js shim with no node
                st.version = None
    if st.path:
        have = parse_version(st.version) if st.version else None
        if p.min_version and p.probe and p.kind != "model":
            if have is None and p.kind == "cli":
                st.state, st.fix = (
                    "outdated",
                    f"{st.path} does not answer {' '.join(p.version_args)}",
                )
            elif have is not None and not _at_least(have, p.min_version):
                st.state, st.fix = (
                    "outdated",
                    f"version {st.version} is older than {p.min_version}",
                )
            else:
                st.state = "ok"
        else:
            st.state = "ok"
    elif st.need == "optional" or (st.need == "default" and not embed):
        st.state = "off"
    recipe = pick_recipe(p, os_key or this_os(), which=which)
    st.installable = recipe is not None and recipe.manager != "url"
    if st.state != "ok":
        st.fix = st.fix or describe_recipe(p, recipe)
    return st


def detect_all(
    *,
    which: Which | None = None,
    probe: Probe | None = None,
    os_key: str | None = None,
    embed: bool = True,
) -> list[Status]:
    return [
        detect(p, which=which, probe=probe, os_key=os_key, embed=embed)
        for p in MANIFEST
    ]


def harness_ok(rows: Sequence[Status]) -> bool:
    return any(r.state == "ok" for r in rows if r.need == "harness")


# ------------------------------------------------------------------------------------------ install plans


def _manager_available(manager: str, *, which: Which | None, os_key: str) -> bool:
    lookup = {
        "winget": "winget",
        "brew": "brew",
        "apt": "apt-get",
        "npm": "npm",
        "script": "curl",
    }
    if manager in ("uv-pip",):
        # never into a bundle: its Python is the app itself, and it ships the embedder
        return not in_bundle() and (which or _which)(by_name("uv")) is not None
    if manager in ("model", "url"):
        return True
    tool = lookup.get(manager)
    if tool is None:
        return False
    if (
        manager == "apt"
        and os_key == "linux"
        and _euid() != 0
        and _find(which, "sudo") is None
    ):
        return False
    if manager == "npm":
        # npm arrives with node: a planned node install makes npm recipes usable
        return True
    return _find(which, tool) is not None


def _find(which: Which | None, tool: str) -> str | None:
    return (which or _which)(Prereq(tool, "", "optional", command=tool))


def _euid() -> int:
    return os.geteuid() if hasattr(os, "geteuid") else 0


def pick_recipe(p: Prereq, os_key: str, *, which: Which | None = None) -> Recipe | None:
    """The first recipe for `os_key` whose package manager is on this machine; else the manual page, if any."""
    recipes = p.install.get(os_key, ())
    for r in recipes:
        if r.manager != "url" and _manager_available(
            r.manager, which=which, os_key=os_key
        ):
            return r
    manual = next((r for r in recipes if r.manager == "url"), None)
    return manual or (Recipe("url", p.docs) if p.docs else None)


def recipe_argv(
    r: Recipe, *, which: Which | None = None, os_key: str | None = None
) -> list[str] | None:
    """The command a recipe runs, without a shell; None for the in-process and manual recipes."""
    os_key = os_key or this_os()
    if r.manager == "winget":
        return [
            *tool_argv(_find(which, "winget") or "winget"),
            "install",
            "--id",
            r.arg,
            "--exact",
            "--source",
            "winget",
            "--accept-source-agreements",
            "--accept-package-agreements",
            "--disable-interactivity",
        ]
    if r.manager == "brew":
        return [_find(which, "brew") or "brew", "install", *r.arg.split()]
    if r.manager == "apt":
        pre = [] if _euid() == 0 else [_find(which, "sudo") or "sudo"]
        return [*pre, "apt-get", "install", "-y", *r.arg.split()]
    if r.manager == "npm":
        return [*tool_argv(_find(which, "npm") or "npm"), "install", "-g", r.arg]
    if r.manager == "script":
        return ["sh", "-c", f"curl -fsSL {r.arg} | sh"]
    if r.manager == "uv-pip":
        return [
            *tool_argv(_find(which, "uv") or "uv"),
            "pip",
            "install",
            "--python",
            sys.executable,
            r.arg,
        ]
    return None


def describe_recipe(p: Prereq, r: Recipe | None) -> str:
    if r is None:
        return f"install {p.name} and put it on PATH" + (
            f" (or set {p.setting})" if p.setting else ""
        )
    if r.manager == "url" and p.kind == "python" and in_bundle():
        return "it ships inside Heronry Desktop: reinstall Heronry Desktop"
    if r.manager == "url":
        return f"install from {r.arg}" + (
            f", or set {p.setting} to its path" if p.setting else ""
        )
    if r.manager == "model":
        return f"download {embed_model()} into the model cache"
    # the command as a person would type it (recipe_argv adds shims and absolute paths)
    return {
        "winget": f"winget install --id {r.arg} --exact",
        "brew": f"brew install {r.arg}",
        "apt": f"sudo apt-get install -y {r.arg}",
        "npm": f"npm install -g {r.arg}",
        "script": f"curl -fsSL {r.arg} | sh",
        "uv-pip": f'uv pip install --python "{sys.executable}" "{r.arg}"',
    }.get(r.manager, r.arg)


@dataclass
class Step:
    name: str
    recipe: Recipe
    argv: list[str] | None
    reason: str


def plan(
    rows: Sequence[Status],
    *,
    os_key: str | None = None,
    which: Which | None = None,
    embed: bool = True,
    only: Sequence[str] = (),
    optional: Sequence[str] = (),
) -> tuple[list[Step], list[Status]]:
    """What `install` would do: (steps, left) — steps for every missing required tool, the default harness when
    no harness is present, the embedder unless `embed` is False, plus any names in `only`/`optional`; `left` are
    the missing ones it cannot install here (manual) or will not (optional, not asked)."""
    os_key = os_key or this_os()
    state = {r.name: r for r in rows}
    wanted: list[str] = []
    for r in rows:
        if r.state == "ok":
            continue
        p = by_name(r.name)
        if only:
            if r.name in only:
                wanted.append(r.name)
            continue
        if (
            need_of(p) == "required"
            or (need_of(p) == "default" and embed)
            or r.name in optional
        ):
            wanted.append(r.name)
    if not only and not harness_ok(rows) and HARNESS_DEFAULT not in wanted:
        wanted.append(HARNESS_DEFAULT)
    # dependencies first (node before the npm harnesses, the embedder before its model)
    for name in list(wanted):
        r = pick_recipe(by_name(name), os_key, which=which)
        if r is None or r.manager == "url":
            continue  # installed by hand (or, in a bundle, by reinstalling it): its installer's deps are moot
        for dep in by_name(name).needs:
            if dep not in wanted and state.get(dep) and state[dep].state != "ok":
                wanted.insert(wanted.index(name), dep)
    order = {p.name: i for i, p in enumerate(MANIFEST)}
    wanted = sorted(dict.fromkeys(wanted), key=lambda n: order[n])
    steps: list[Step] = []
    left: list[Status] = []
    for name in wanted:
        p = by_name(name)
        r = pick_recipe(p, os_key, which=which)
        if r is None or r.manager == "url":
            left.append(state[name])
            continue
        reason = (
            "required"
            if need_of(p) == "required"
            else (
                "no seat harness is installed"
                if p.need == "harness" and name not in only
                else p.feature or p.need
            )
        )
        steps.append(Step(name, r, recipe_argv(r, which=which, os_key=os_key), reason))
    planned = {s.name for s in steps}
    harness_covered = harness_ok(rows) or any(
        by_name(n).need == "harness" for n in planned
    )
    for r in rows:
        if r.state == "ok" or r.state == "off" or r.name in planned or r in left:
            continue
        if (r.need == "harness" and harness_covered) or (
            r.need == "default" and not embed
        ):
            continue
        left.append(r)
    return steps, left


# ------------------------------------------------------------------------------------------ running it

Runner = Callable[[list[str]], int]


def _run(argv: list[str]) -> int:
    """Run an installer command with its output on this console (winget/brew/apt progress stays visible)."""
    try:
        return subprocess.run(
            argv, stdin=subprocess.DEVNULL if not sys.stdin.isatty() else None
        ).returncode
    except OSError as e:
        sys.stderr.write(f"heronry prereqs: cannot run {argv[0]}: {e}\n")
        return 127


def download_model(*, say: Callable[[str], None] = print) -> Path | None:
    """Fetch the embedding model into :func:`embed_cache_dir` (fastembed prints its own progress bar)."""
    model, cache = embed_model(), embed_cache_dir()
    say(
        f"downloading the embedding model {model} into {cache or 'fastembed default cache'} (about 0.1-0.6 GB) …"
    )
    from fastembed import TextEmbedding  # noqa: PLC0415 — only after the embedder step

    kw: dict[str, Any] = {"model_name": model}
    if cache is not None:
        cache.mkdir(parents=True, exist_ok=True)
        kw["cache_dir"] = str(cache)
    TextEmbedding(**kw)
    found = _model_cached(model, cache)
    say(
        f"embedding model ready: {found}"
        if found
        else "embedding model: download finished but no .onnx found"
    )
    return found


def refresh_path() -> None:
    """Windows: merge the user and machine PATH from the registry into this process, so a tool winget just
    installed is found without a new terminal. Entries already present keep their order."""
    if sys.platform != "win32":
        return
    import winreg  # noqa: PLC0415

    got: list[str] = []
    for hive, sub in (
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        ),
        (winreg.HKEY_CURRENT_USER, "Environment"),
    ):
        try:
            with winreg.OpenKey(hive, sub) as k:
                v, _ = winreg.QueryValueEx(k, "Path")
                got += [os.path.expandvars(x) for x in str(v).split(";") if x]
        except OSError:
            continue
    cur = [x for x in settings.environ_copy().get("PATH", "").split(os.pathsep) if x]
    seen = {x.lower() for x in cur}
    settings.set_env(
        "PATH", os.pathsep.join(cur + [x for x in got if x.lower() not in seen])
    )


def run_steps(
    steps: Sequence[Step],
    *,
    run: Runner | None = None,
    say: Callable[[str], None] = print,
    model: Callable[[], Path | None] | None = None,
) -> dict[str, int]:
    """Run each step in order; {name: exit code}. A step whose dependency failed is skipped (exit -1)."""
    out: dict[str, int] = {}
    for s in steps:
        dead = [d for d in by_name(s.name).needs if out.get(d, 0) != 0]
        if dead:
            say(f"skip {s.name}: {', '.join(dead)} did not install")
            out[s.name] = -1
            continue
        if s.recipe.manager == "model":
            try:
                ok = (model or download_model)() is not None
            except Exception as e:  # noqa: BLE001 — offline, disk full: say so, keep going
                say(f"{s.name}: {e}")
                ok = False
            out[s.name] = 0 if ok else 1
            continue
        if not s.argv:
            out[s.name] = 1
            continue
        say(f"installing {s.name}: {' '.join(s.argv)}")
        out[s.name] = (run or _run)(s.argv)
        if out[s.name] != 0:
            say(f"{s.name}: the installer exited {out[s.name]}")
        if s.name == "node":
            refresh_path()  # npm must be findable for the npm steps that follow
    return out


# ------------------------------------------------------------------------------------------ README table

README_BEGIN = "<!-- prereqs:begin (generated by `python -m edp_contracts.prereqs --readme`; edit prereqs.py) -->"
README_END = "<!-- prereqs:end -->"
_NEED_WORDS = {
    "required": "required",
    "harness": "at least one of claude / codex",
    "optional": "optional",
    "default": "installed by default",
}
_MANAGER_WORDS = {
    "winget": "winget",
    "brew": "brew",
    "apt": "apt",
    "npm": "npm -g",
    "script": "official script",
    "uv-pip": "into Heronry's Python",
    "model": "downloaded on install",
    "url": "download page",
}


def _how(p: Prereq) -> str:
    parts = []
    for o, label in (("win32", "Windows"), ("darwin", "macOS"), ("linux", "Linux")):
        rs = p.install.get(o, ())
        if rs:
            r = rs[0]
            parts.append(
                f"{label}: {_MANAGER_WORDS[r.manager]}"
                + (
                    f" `{r.arg}`"
                    if r.manager in ("winget", "brew", "apt", "npm")
                    else ""
                )
            )
    if len({x.split(":")[1] for x in parts}) == 1 and len(parts) == 3:
        return parts[0].split(": ", 1)[1]
    return "<br>".join(parts)


def markdown_table() -> str:
    lines = [
        "| What | Needed for | Required? | How the installer gets it |",
        "|---|---|---|---|",
    ]
    for p in MANIFEST:
        need = _NEED_WORDS[p.need] + (
            f" ({p.feature})" if p.need in ("optional", "default") and p.feature else ""
        )
        ver = f" ≥ {p.min_version}" if p.min_version else ""
        lines.append(f"| `{p.name}`{ver} | {p.purpose} | {need} | {_how(p)} |")
    for name, why in BUNDLED:
        lines.append(f"| {name} | {why.split(';')[0]} | bundled | nothing to do |")
    for name, why in NOT_NEEDED:
        lines.append(f"| {name} | {why} | no | — |")
    return "\n".join(lines)


def readme_block() -> str:
    return f"{README_BEGIN}\n{markdown_table()}\n{README_END}"


def sync_readme(path: Path) -> bool:
    """Rewrite the generated block in `path`; True when it changed."""
    text = path.read_text(encoding="utf-8")
    pat = re.compile(re.escape(README_BEGIN) + r".*?" + re.escape(README_END), re.S)
    if not pat.search(text):
        raise ValueError(f"{path} has no {README_BEGIN!r} … {README_END!r} block")
    new = pat.sub(lambda _m: readme_block(), text)
    if new != text:
        path.write_text(new, encoding="utf-8")
    return new != text


def _main(argv: list[str]) -> int:
    if argv[:1] == ["--markdown"]:
        sys.stdout.write(markdown_table() + "\n")
        return 0
    if argv[:1] == ["--readme"]:
        root = Path(__file__).resolve().parents[3]
        target = Path(argv[1]) if len(argv) > 1 else root / "README.md"
        changed = sync_readme(target)
        sys.stdout.write(f"{target}: {'updated' if changed else 'already current'}\n")
        return 0
    sys.stderr.write("usage: python -m edp_contracts.prereqs --markdown | --readme [README.md]\n")
    return 2


__all__ = [
    "BUNDLED",
    "HARNESS_DEFAULT",
    "MANIFEST",
    "NOT_NEEDED",
    "Prereq",
    "Recipe",
    "Status",
    "Step",
    "by_name",
    "detect",
    "detect_all",
    "download_model",
    "embed_cache_dir",
    "harness_ok",
    "markdown_table",
    "pick_recipe",
    "plan",
    "readme_block",
    "recipe_argv",
    "refresh_path",
    "run_steps",
    "sync_readme",
    "this_os",
]

_ = (
    shutil,
    sqlite3,
)  # sqlite3: imported so a Python built without it fails here, not at first board start

if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
