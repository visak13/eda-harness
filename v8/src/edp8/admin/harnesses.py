"""Admin → Integrations → Seat harnesses (design-e963c656f5 §4.10 harness row, §4.11).

* Detection: path (setting, else PATH), `--version`, and signed-in state for claude, codex and pi.
* Latest version: the npm registry's `latest` tag of each vendor package (unknown when offline).
* **Update when idle**: the app never updates a harness on its own (strategyhl-86b4805322 §5). On an
  admin's click it runs the VENDOR's update command, and only while no seat of that harness is live on the
  pool: with seats live it refuses (409), or with `wait: true` it waits in the background until none is,
  then runs it and re-probes the version. A pool that cannot say which seats are live counts as busy.
* Selection: at least one of claude/codex; a selection without codex runs the adversary on Fable, so it
  needs the recorded risk acknowledgement (`fable_ack: true` records it once, POST /v1/harness/fable-ack's
  record). Stored as `seats.harnesses` in config.toml.
"""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from edp_contracts.toolpath import find_tool, probe_version, tool_argv

from .. import harness, pool_adapter, seat_choice, settings
from ..schemas import Participant
from . import net
from .context import AdminContext

BIN_KEYS = {"claude": "EDP_CLAUDE_BIN", "codex": "EDP_CODEX_BIN", "pi": "EDP_PI_BIN"}
NPM_PACKAGES = {"claude": "@anthropic-ai/claude-code", "codex": "@openai/codex",
                "pi": "@earendil-works/pi-coding-agent"}
WAIT_POLL_S = 30.0
WAIT_MAX_S = 12 * 3600.0
UPDATE_TIMEOUT_S = 900


class UpdateIn(BaseModel):
    wait: bool = False   # seats live: wait in the background until none is, instead of refusing


class SelectionIn(BaseModel):
    harnesses: list[str]
    fable_ack: bool = False


def _run(argv: list[str], timeout: float = UPDATE_TIMEOUT_S) -> tuple[int, str]:
    """The vendor update command, no shell (tests replace this seam)."""
    try:
        r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, stdin=subprocess.DEVNULL)
        return r.returncode, ((r.stdout or "") + (r.stderr or ""))[-2000:]
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)


def _probe(path: str) -> str | None:
    try:
        return probe_version(tool_argv(path), timeout=10.0)
    except Exception:  # noqa: BLE001 — a missing node for a .js shim: version unknown
        return None


def signed_in(h: str) -> bool | None:
    """True/False when the harness's own credential store says so; None when it cannot be told."""
    if h == "claude":
        from ..setup import claude_signed_in
        return claude_signed_in()
    home = Path.home()
    if h == "codex":
        return (home / ".codex" / "auth.json").is_file()
    if h == "pi":
        return (home / ".pi" / "agent" / "auth.json").is_file() or None
    return None


def latest_version(h: str) -> str | None:
    base = str(settings.get("EDP_NPM_REGISTRY")).rstrip("/")
    try:
        with net.client(timeout=5.0) as c:
            r = c.get(f"{base}/{NPM_PACKAGES[h]}/latest")
        return str(r.json().get("version")) if r.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        return None


def update_argv(h: str, path: str | None) -> list[str]:
    """The vendor's own update command: `claude update`; npm for codex and pi."""
    if h == "claude":
        if not path:
            raise HTTPException(409, "claude is not installed here")
        return [*tool_argv(path), "update"]
    npm = find_tool("npm")
    if not npm:
        raise HTTPException(409, f"npm is not on PATH; update {h} with its own installer")
    return [*tool_argv(npm), "install", "-g", f"{NPM_PACKAGES[h]}@latest"]


def live_seats_by_harness() -> dict[str, list[str]] | None:
    """{harness: [handle]} of the pool's active seats; None when the pool cannot say."""
    got = pool_adapter.sessions()
    if not got.get("ok"):
        return None
    rows = got.get("value")
    if isinstance(rows, dict):
        rows = rows.get("sessions") or rows.get("value") or []
    reg = seat_choice._registry(seat_choice.agent_home())
    models = reg.get("models") if isinstance(reg.get("models"), dict) else {}
    seats = reg.get("seats") if isinstance(reg.get("seats"), dict) else {}
    out: dict[str, list[str]] = {h: [] for h in harness.HARNESSES}
    for r in rows or []:
        if isinstance(r, dict) and r.get("state") == "active":
            routed = harness.harness_of(r.get("model"), models) or harness.harness_of(r.get("model"), seats)
            if routed in out:
                out[routed].append(str(r.get("handle")))
    return out


class Updater:
    """One update job per harness: waiting → running → done|failed, visible in GET."""

    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()

    def state(self, h: str) -> dict[str, Any] | None:
        with self.lock:
            j = self.jobs.get(h)
            return dict(j) if j else None

    def _set(self, h: str, **kw: Any) -> None:
        with self.lock:
            self.jobs.setdefault(h, {}).update(kw)

    def busy(self, h: str) -> bool:
        j = self.state(h)
        return bool(j and j.get("state") in ("waiting", "running"))

    def run_now(self, h: str, path: str | None, by: str) -> dict[str, Any]:
        argv = update_argv(h, path)
        before = _probe(path) if path else None
        self._set(h, state="running", by=by, started=time.time(), before=before, argv=argv[-4:])
        rc, out = _run(argv)
        path_after = find_tool(h, key=BIN_KEYS[h]) or path
        after = _probe(path_after) if path_after else None
        self._set(h, state="done" if rc == 0 else "failed", exit=rc, output=out[-800:], after=after,
                  finished=time.time())
        return self.state(h) or {}

    def wait_then_run(self, h: str, path: str | None, by: str) -> None:
        poll, max_s = WAIT_POLL_S, WAIT_MAX_S
        self._set(h, state="waiting", by=by, since=time.time(), exit=None, output=None)

        def loop() -> None:
            deadline = time.monotonic() + max_s
            while time.monotonic() < deadline:
                live = live_seats_by_harness()
                if live is not None and not live.get(h):
                    self.run_now(h, path, by)
                    return
                self._set(h, live=None if live is None else live.get(h))
                time.sleep(poll)
            self._set(h, state="failed", output=f"gave up after {int(max_s)}s: seats stayed live")

        threading.Thread(target=loop, name=f"harness-update-{h}", daemon=True).start()


def detect(updater: Updater, live: dict[str, list[str]] | None, *, with_latest: bool) -> list[dict[str, Any]]:
    picked = harness.selected(seat_choice._registry(seat_choice.agent_home()))
    rows = []
    for h in harness.HARNESSES:
        path = find_tool(h, key=BIN_KEYS[h])
        rows.append({"harness": h, "selected": h in picked, "installed": bool(path), "path": path,
                     "version": _probe(path) if path else None, "signed_in": signed_in(h) if path else None,
                     "latest": latest_version(h) if with_latest else None,
                     "live_seats": None if live is None else live.get(h, []),
                     "update": updater.state(h)})
    return rows


def router(ctx: AdminContext, admin_actor) -> APIRouter:
    r = APIRouter()
    updater = Updater()

    def _ack_path():
        return harness.ack_path(getattr(ctx.board.store, "path", None))

    @r.get("/v1/admin/harnesses")
    def harnesses_get(latest: bool = True, a: Participant = Depends(admin_actor)):
        reg = seat_choice._registry(seat_choice.agent_home())
        picked = harness.selected(reg)
        ack = harness.read_ack(_ack_path())
        return {"ok": True, "value": {
            "harnesses": detect(updater, live_seats_by_harness(), with_latest=latest),
            "selected": list(picked), "fable_ack": ack,
            "fable_notice": harness.FABLE_RISK_NOTICE if "codex" not in picked else None}, "hint": ""}

    @r.post("/v1/admin/harnesses/{h}/update")
    def harness_update(h: str, b: UpdateIn | None = None, a: Participant = Depends(admin_actor)):
        b = b or UpdateIn()
        if h not in harness.HARNESSES:
            raise HTTPException(404, f"unknown harness {h!r} (one of {', '.join(harness.HARNESSES)})")
        path = find_tool(h, key=BIN_KEYS[h])
        if not path:
            raise HTTPException(409, f"{h} is not installed here; install it first")
        if updater.busy(h):
            raise HTTPException(409, f"an update of {h} is already {updater.state(h)['state']}")
        update_argv(h, path)  # refuse now (409) when the vendor command cannot run at all
        live = live_seats_by_harness()
        busy = live is None or bool(live.get(h))
        if busy and not b.wait:
            who = "the pool cannot say which seats are live" if live is None else \
                f"{len(live[h])} {h} seat(s) are live: {', '.join(live[h][:5])}"
            raise HTTPException(409, f"update when idle: {who}; let them finish or park them, or ask to wait")
        if busy:
            updater.wait_then_run(h, path, a.handle.lstrip("@"))
            return {"ok": True, "value": updater.state(h),
                    "hint": f"waiting until no {h} seat is live, then the vendor update runs"}
        out = updater.run_now(h, path, a.handle.lstrip("@"))
        if out.get("state") != "done":
            raise HTTPException(502, f"{h} update exited {out.get('exit')}: {str(out.get('output') or '')[-300:]}")
        return {"ok": True, "value": out, "hint": f"{h} {out.get('before')} -> {out.get('after')}"}

    @r.put("/v1/admin/harnesses/selection")
    def harness_selection(b: SelectionIn, a: Participant = Depends(admin_actor)):
        picked = [h for h in harness.HARNESSES if h in {x.strip().lower() for x in b.harnesses}]
        unknown = sorted({x.strip().lower() for x in b.harnesses} - set(harness.HARNESSES))
        if unknown:
            raise HTTPException(400, f"unknown harness {', '.join(unknown)}")
        problem = harness.validate(picked)
        if problem:
            raise HTTPException(409, f"refused: {problem}")
        if settings.env_raw("EDP_HARNESSES") is not None:
            raise HTTPException(409, "EDP_HARNESSES is set by the environment (read-only here)")
        reg = seat_choice._registry(seat_choice.agent_home())
        ack = harness.read_ack(_ack_path())
        if "codex" not in picked and ack is None:
            if not b.fable_ack:
                raise HTTPException(409, f"a selection without codex needs the risk acknowledgement "
                                         f"(fable_ack: true): {harness.FABLE_RISK_NOTICE}")
            path = _ack_path()
            if path is None:
                raise HTTPException(409, "an in-memory board cannot record the acknowledgement")
            ack = harness.write_ack(path, a.id)
        from ..setup import write_config
        write_config({"seats.harnesses": picked})
        return {"ok": True, "value": {"selected": list(harness.selected(reg)), "fable_ack": ack,
                                      "restart_required": ["board"]},
                "hint": "applies to new spawns; restart the board for the catalog"}

    return r
