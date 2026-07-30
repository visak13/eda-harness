"""Pool-side spawn defaults — the settings `build_env`/`build_argv` read.

The pool is what launches shells, so the pool is where spawn settings belong
(not the user's own claude-personal session). Changes affect FRESH SPAWNS ONLY;
a running shell's argv and env were fixed at launch and are not rewritten. The
panel banner says so.

=== EDP_SKIP_PERMISSIONS IS NOT A KEY HERE, AND THAT IS DELIBERATE ===

DESIGN-v6 §W12 lists `EDP_SKIP_PERMISSIONS` as a spawn-config toggle. THAT LINE
IS OVERRULED by a standing user constraint: he deliberately set up manual
permissions and will not dangerously-skip. It is not gated, not confirmed, not
disabled-in-the-UI — it is ABSENT. No browser POST may reach that switch, so
there is no switch to reach: `save_spawn_defaults` REFUSES the key rather than
silently dropping it, because a silent drop teaches a caller it worked.

The env var itself is untouched — the operator's own environment still governs
`spawner.launch`, exactly as before. What is removed is the PANEL'S REACH.
"""

import json
import os
import tempfile
from pathlib import Path

_PATH_ENV = "EDP_SPAWN_DEFAULTS"
_DEFAULT_PATH = Path(".pool-logs") / "spawn_defaults.json"

#: The whole settable surface. Anything else is dropped as unknown.
ALLOWED_KEYS = ("model", "spawn_mode", "rtk")

#: Names that must never be settable through this file, in any spelling. A
#: refusal is loud; a silent drop is how a dangerous toggle gets "supported".
BANNED_KEYS = frozenset({
    "skip_permissions",
    "EDP_SKIP_PERMISSIONS",
    "edp_skip_permissions",
    "dangerously_skip_permissions",
})


class BannedSpawnDefault(ValueError):
    """A caller tried to set a key the panel may never reach."""


def defaults_path(path=None) -> Path:
    if path is not None:
        return Path(path)
    return Path(os.environ.get(_PATH_ENV, str(_DEFAULT_PATH)))


def load_spawn_defaults(path=None) -> dict:
    """The pool's spawn defaults, or `{}`. NEVER raises: a corrupt or absent
    file must degrade to "no defaults" (byte-identical to pre-W12 behaviour),
    never to a failed spawn."""
    p = defaults_path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k in ALLOWED_KEYS}


def save_spawn_defaults(values: dict, path=None) -> dict:
    """Validate + atomically persist. Refuses `BANNED_KEYS` loudly; drops
    unknown keys. Returns what was written."""
    if not isinstance(values, dict):
        raise BannedSpawnDefault("spawn defaults must be an object")
    for k in values:
        if k in BANNED_KEYS:
            raise BannedSpawnDefault(
                f"{k!r} is not a spawn default and never will be: the user "
                "deliberately set up manual permissions. No panel surface may "
                "reach it."
            )
    clean = {k: v for k, v in values.items() if k in ALLOWED_KEYS}
    if "spawn_mode" in clean and clean["spawn_mode"] not in (
            "headless", "monitor"):
        raise BannedSpawnDefault(
            f"spawn_mode must be 'headless' or 'monitor', "
            f"got {clean['spawn_mode']!r}")
    if "rtk" in clean:
        clean["rtk"] = bool(clean["rtk"])
    p = defaults_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(clean, f, indent=2)
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return clean
