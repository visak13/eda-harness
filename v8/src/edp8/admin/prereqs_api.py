"""The setup wizard's "Your tools" step (t-08612be1b0): the prerequisites checklist and its Install button.

* ``GET /v1/admin/setup/prereqs`` — every row of the one manifest (:mod:`edp_contracts.prereqs`): found with
  its version, missing with the fix, or an optional feature that is off; harness rows add ``signed_in`` and the
  ``login`` command to run; plus the state of each install job.
* ``POST /v1/admin/setup/prereqs/{name}/install`` — runs THE install step, ``heronry prereqs install --only
  <name> --yes``, as a child process in the background (winget/brew/npm can take minutes), one job per tool.
  Only on an admin's click; the argv is built from the manifest name, never from the request.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from edp_contracts import prereqs as pq

from ..schemas import Participant
from .context import AdminContext

INSTALL_TIMEOUT_S = 1800


def install_argv(name: str) -> list[str]:
    """The one install step for one tool, run by this interpreter (a uv tool env or a bundle alike)."""
    return [sys.executable, "-m", "edp8.cli", "prereqs", "install", "--only", name, "--yes"]


def _run(argv: list[str]) -> tuple[int, str]:
    """The install step, no shell, output captured (tests replace this seam)."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=INSTALL_TIMEOUT_S, stdin=subprocess.DEVNULL, creationflags=flags)
        return r.returncode, ((r.stdout or "") + (r.stderr or ""))[-4000:]
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)


class Jobs:
    """One install job per tool: running → done|failed, visible in GET."""

    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()

    def state(self, name: str) -> dict[str, Any] | None:
        with self.lock:
            j = self.jobs.get(name)
            return dict(j) if j else None

    def _set(self, name: str, **kw: Any) -> None:
        with self.lock:
            self.jobs.setdefault(name, {}).update(kw)

    def start(self, name: str, by: str, *, background: bool = True) -> dict[str, Any]:
        argv = install_argv(name)
        self._set(name, state="running", by=by, started=time.time(), exit=None, output=None,
                  command=" ".join(argv[-5:]))

        def work() -> None:
            rc, out = _run(argv)
            pq.refresh_path()  # a tool winget just put on PATH is visible to the next GET
            self._set(name, state="done" if rc == 0 else "failed", exit=rc, output=out, finished=time.time())

        if background:
            threading.Thread(target=work, name=f"prereq-install-{name}", daemon=True).start()
        else:
            work()
        return self.state(name) or {}


def rows_view(jobs: Jobs) -> dict[str, Any]:
    from ..prereqs_cmd import login_command
    from .harnesses import signed_in

    out = []
    for r in pq.detect_all():
        row = r.to_dict()
        p = pq.by_name(r.name)
        if p.login:
            row["login"] = login_command(r.name)
            row["signed_in"] = signed_in(r.name) if r.state == "ok" else None
        row["job"] = jobs.state(r.name)
        out.append(row)
    return {"os": pq.this_os(), "rows": out, "harness_ok": any(x["state"] == "ok" for x in out
                                                               if x["need"] == "harness"),
            "bundled": [{"name": n, "why": w} for n, w in pq.BUNDLED],
            "not_needed": [{"name": n, "why": w} for n, w in pq.NOT_NEEDED]}


def router(ctx: AdminContext, admin_actor) -> APIRouter:
    r = APIRouter()
    jobs = Jobs()

    @r.get("/v1/admin/setup/prereqs")
    def prereqs_get(a: Participant = Depends(admin_actor)):
        return {"ok": True, "value": rows_view(jobs), "hint": ""}

    @r.post("/v1/admin/setup/prereqs/{name}/install")
    def prereqs_install(name: str, a: Participant = Depends(admin_actor)):
        try:
            p = pq.by_name(name)
        except KeyError as e:
            raise HTTPException(404, e.args[0]) from None
        j = jobs.state(p.name)
        if j and j.get("state") == "running":
            raise HTTPException(409, f"{p.name} is already being installed")
        st = pq.detect(p)
        if st.state == "ok":
            raise HTTPException(409, f"{p.name} is already installed ({st.version or st.path})")
        if not st.installable:
            raise HTTPException(409, f"{p.name} cannot be installed from here: {st.fix}")
        out = jobs.start(p.name, a.handle.lstrip("@"))
        return {"ok": True, "value": out, "hint": f"installing {p.name}: {st.fix}"}

    return r
