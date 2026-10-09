"""Is a commit on main? The one read-only git question the pain store asks (e0cec S6).

An epic's architect may resolve a pain `fixed` when it cites a commit reachable from `main`; the board checks
that here, in the checkout it runs from (EDP8_REPO, else the dev checkout). The caller never passes a path or a
ref, only a sha, and git only reads. A board with no checkout cannot check, so the architect's `fixed` is refused
there and the owner or doctor resolves it.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from . import materialise, settings

_SHA = re.compile(r"^[0-9a-f]{7,40}$")


def _repo() -> str | None:
    env = settings.env_raw("EDP8_REPO")
    if env:
        return env
    root = materialise.checkout_root()
    return str(root) if root else None


def commit_on_main(sha: str) -> tuple[bool, str]:
    """(reachable, why-not): is `sha` an ancestor of `main` in the checkout this board runs from?"""
    if not _SHA.match(sha or ""):
        return False, f"{sha!r} is not a commit sha"
    repo = _repo()
    if repo is None:
        return False, "this board has no git checkout to check the commit against; the owner or doctor resolves it"
    try:
        r = subprocess.run(["git", "-C", repo, "merge-base", "--is-ancestor", sha, "main"],
                           capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"git could not run here ({type(e).__name__})"
    if r.returncode == 0:
        return True, ""
    if r.returncode == 1:
        return False, f"{sha} is not on main"
    return False, (r.stderr or "git could not check the commit").strip()[:200]


_REMOTE_YES: set[str] = set()
_REMOTE_NO: dict[str, float] = {}
_REMOTE_RECHECK_S = 60.0


def commit_on_remote(sha: str) -> bool:
    """Is `sha` contained in a remote-tracking ref of the checkout (what was last fetched or pushed)? Offline and
    read-only. False when the sha is unknown, unpushed, or the board has no checkout: a link to GitHub must not 404."""
    import time
    if not _SHA.match(sha or ""):
        return False
    if sha in _REMOTE_YES:
        return True
    if time.monotonic() - _REMOTE_NO.get(sha, -1e9) < _REMOTE_RECHECK_S:
        return False
    repo = _repo()
    found = False
    if repo is not None:
        try:
            r = subprocess.run(["git", "-C", repo, "for-each-ref", "--count=1", "--format=%(refname)",
                                f"--contains={sha}", "refs/remotes/"], capture_output=True, text=True, timeout=15)
            found = r.returncode == 0 and bool(r.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            found = False
    if found:
        _REMOTE_YES.add(sha)
    else:
        _REMOTE_NO[sha] = time.monotonic()
    return found
