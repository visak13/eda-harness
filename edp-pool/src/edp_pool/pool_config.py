"""The pool's Claude settings.json: a tracked template, seeded into the pool config dir.

The pool config dir (`claude_pool_config_dir()`: dev <repo>/edp-pool/.claude-pool, installed
<data>/claude-pool) is gitignored whole, because seats write transcripts, memory and sign-in into it.
So its settings.json never ships. The template beside this module is the shipped copy: the hooks,
`outputStyle: edp-terse`, skill overrides. It carries no `effortLevel`: each seat's effort rides its launch argv
(`--effort`, pty_launcher.build_argv), resolved from the spawn and clamped to the catalog cap. It is seeded into the config dir at pool start and at
`heronry init`, only when the file is missing, so an owner's edits are never overwritten. After an upgrade
changes the template, upgrade_settings merges it once into an existing file (retired pins dropped, new keys and
hooks added, the owner's values kept). It carries no `model` (the catalog passes --model) and no host paths.
"""

from __future__ import annotations

import os
import sys
import tempfile
from importlib import resources
from pathlib import Path

SETTINGS = "settings.json"
#: The hook interpreter the template names: the agent home's own venv (a source checkout has one).
VENV_PYTHON = "${CLAUDE_PROJECT_DIR}/.venv/Scripts/python.exe"


def template_text() -> str:
    return (
        resources.files("edp_pool")
        .joinpath("claude_pool_template", SETTINGS)
        .read_text(encoding="utf-8")
    )


def render(agent_home: Path | None, python: str | None = None) -> str:
    """The template with its hook interpreter resolved for this machine: the agent home's .venv python
    when the home has one, else the interpreter the pool runs (an installed home has no .venv)."""
    text = template_text()
    if (
        agent_home is not None
        and (Path(agent_home) / ".venv" / "Scripts" / "python.exe").is_file()
    ):
        return text
    exe = (python or sys.executable).replace("\\", "/")
    return text.replace(VENV_PYTHON, exe)


def seed_settings(
    config_dir: Path, agent_home: Path | None = None, python: str | None = None
) -> bool:
    """Write <config_dir>/settings.json from the template when it is missing. Returns True when written.
    An existing file is left alone, whatever it holds (the owner's edits win)."""
    config_dir = Path(config_dir)
    dst = config_dir / SETTINGS
    if dst.exists():
        return False
    config_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=config_dir, prefix=f".{SETTINGS}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(render(agent_home, python))
        # atomic create-if-absent: a concurrent seed or an owner's file is never replaced
        try:
            os.link(tmp, dst)
        except FileExistsError:
            return False
        except OSError:  # no hard links on this filesystem: re-check, then move
            if dst.exists():
                return False
            os.replace(tmp, dst)
    finally:
        Path(tmp).unlink(missing_ok=True)
    return True


#: Keys an older template pinned that the fleet no longer sets there (S7: effort rides each seat's argv, so a
#: leftover `effortLevel` would hold every seat at the old level). An upgrade drops them.
RETIRED_KEYS = ("effortLevel",)
#: The template digest a config dir was last brought up to; a differing (or missing) stamp merges once.
STAMP = ".settings-template.sha256"


def _hook_tail(command: str) -> str:
    """A hook command without its interpreter (`"<python>" <rest>` -> `<rest>`), so the same hook matches
    whichever interpreter this machine renders."""
    if command.startswith('"') and '" ' in command:
        return command.split('" ', 1)[1]
    return command


def _merge(current: dict, template: dict) -> list[str]:
    """Bring `current` up to `template` in place: drop RETIRED_KEYS, add top-level keys it lacks, add hook
    events, matcher groups and hooks it lacks. Never changes a value the owner set. Returns what changed."""
    changed: list[str] = []
    for k in RETIRED_KEYS:
        if k in current and k not in template:
            current.pop(k)
            changed.append(f"dropped {k}")
    for k, v in template.items():
        if k != "hooks" and k not in current:
            current[k] = v
            changed.append(f"added {k}")
    hooks = current.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        return changed
    for event, groups in (template.get("hooks") or {}).items():
        have = hooks.setdefault(event, [])
        if not isinstance(have, list):
            continue
        for g in groups:
            mine = next((h for h in have if isinstance(h, dict) and h.get("matcher") == g.get("matcher")), None)
            if mine is None:
                have.append(g)
                changed.append(f"added {event} hook" + (f" ({g['matcher']})" if g.get("matcher") else ""))
                continue
            tails = {_hook_tail(str(h.get("command", ""))) for h in mine.get("hooks", []) if isinstance(h, dict)}
            for h in g.get("hooks", []):
                if _hook_tail(str(h.get("command", ""))) not in tails:
                    mine.setdefault("hooks", []).append(h)
                    changed.append(f"added {event} hook {_hook_tail(str(h.get('command', '')))[:60]}")
    return changed


def upgrade_settings(
    config_dir: Path, agent_home: Path | None = None, python: str | None = None
) -> list[str]:
    """After an upgrade (the shipped template changed since this dir was last brought up to it), merge the new
    template into an existing settings.json: retired pins dropped, new keys and hooks added, every value the
    owner set kept. Runs once per template change (STAMP), so a hook the owner later removes stays removed
    until the next release changes the template. Returns what changed; [] when nothing was due or the file is
    missing (seed_settings writes that) or unreadable (left alone; doctor reports it)."""
    import hashlib
    import json

    config_dir = Path(config_dir)
    dst = config_dir / SETTINGS
    rendered = render(agent_home, python)
    digest = hashlib.sha256(template_text().encode("utf-8")).hexdigest()
    stamp = config_dir / STAMP
    try:
        if stamp.read_text(encoding="ascii").strip() == digest:
            return []
    except OSError:
        pass
    if not dst.is_file():
        return []
    try:
        current = json.loads(dst.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []
    if not isinstance(current, dict):
        return []
    changed = _merge(current, json.loads(rendered))
    if changed:
        fd, tmp = tempfile.mkstemp(dir=config_dir, prefix=f".{SETTINGS}.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                json.dump(current, f, indent=2)
                f.write("\n")
            os.replace(tmp, dst)
        finally:
            Path(tmp).unlink(missing_ok=True)
    stamp.write_text(digest, encoding="ascii")
    return changed
