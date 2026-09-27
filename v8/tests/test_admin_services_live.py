"""S5 service control on a PRIVATE instance (c-40e35d1d5d): restarting the pool and the board through
`/v1/admin/services/*` goes through the supervisor's control port, gives a new started_at within 60 s and a
`service_restarted {by=<admin>}` event; the board's own process is replaced by the supervisor (the board
only asks). Free ports, a temp EDP_HOME and the no-survivor marker from test_cli_launcher."""

from __future__ import annotations

import json
import time

import httpx
import pytest

import test_cli_launcher as base
from edp_contracts.proc import scan_env_marker

inst = base.inst
V8 = base.V8

pytestmark = pytest.mark.skipif(
    not base._venv_py(base.ROOT / "edp-pool").is_file() or not base._venv_py(base.ROOT / "edp-broker").is_file(),
    reason="needs the edp-pool and edp-broker venvs")


def _wait(pred, timeout: float, what: str):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = pred()
            if last:
                return last
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise AssertionError(f"timed out after {timeout}s waiting for {what} (last={last!r})")


def _events(url: str, h: dict, svc: str) -> list[dict]:
    r = httpx.get(f"{url}/v1/events", params={"subject_id": f"service/{svc}"}, headers=h, timeout=10)
    return [e for e in r.json().get("value") or [] if e["kind"] == "service_restarted"]


def test_admin_restarts_pool_and_board_through_the_supervisor(inst):
    assert base.cli(inst, "init", "--harness", "claude", "--agent-home-source", str(V8)).returncode == 0
    try:
        r = base.cli(inst, "start")
        assert r.returncode == 0, r.stdout + r.stderr
        url = f"http://127.0.0.1:{inst['ports']['board']}"
        tok = json.loads((inst["home"] / "tokens.json").read_text(encoding="utf-8"))["owner"]
        h = {"X-Participant": "owner", "X-Token": tok}

        # a non-admin credential never reaches the route on the live instance either
        assert httpx.post(f"{url}/v1/admin/services/pool/restart", headers={"X-Participant": "owner"},
                          timeout=10).status_code == 403

        st = httpx.get(f"{url}/v1/admin/services", headers=h, timeout=20).json()["value"]
        rows = {x["service"]: x for x in st["services"]}
        assert st["supervisor"] == {"running": True, "control": True}, st["supervisor"]
        for svc in ("board", "pool", "mcp", "broker"):
            assert rows[svc]["pid"] and rows[svc]["port"] and rows[svc]["started_at"], rows[svc]
            assert {"uptime", "last_probe", "last_restart_reason", "health", "rev"} <= set(rows[svc]), rows[svc]

        # --- pool: synchronous answer from the supervisor
        pool_before = rows["pool"]["started_at"]
        t0 = time.monotonic()
        r = httpx.post(f"{url}/v1/admin/services/pool/restart", headers=h, json={"force": True}, timeout=120)
        assert r.status_code == 200, r.text
        def pool_new():
            rs = {x["service"]: x for x in httpx.get(f"{url}/v1/admin/services", headers=h, timeout=20).json()["value"]["services"]}
            return rs["pool"]["started_at"] if rs["pool"]["started_at"] not in (None, pool_before) else None
        _wait(pool_new, 60, "a new pool started_at")
        assert time.monotonic() - t0 < 60
        ev = _wait(lambda: _events(url, h, "pool"), 20, "the pool service_restarted event")
        assert ev[-1]["data"]["by"] == "owner", ev[-1]

        # --- board: 202 now, the supervisor replaces this process, /healthz shows a new started_at
        health_before = httpx.get(f"{url}/healthz", timeout=10).json()["started_at"]
        board_pid = rows["board"]["pid"]
        t0 = time.monotonic()
        r = httpx.post(f"{url}/v1/admin/services/board/restart", headers=h, timeout=30)
        assert r.status_code == 202, r.text
        assert r.json()["value"]["state"] == "restarting"
        _wait(lambda: (httpx.get(f"{url}/healthz", timeout=5).json().get("started_at") or health_before) != health_before,
              60, "a new board started_at on /healthz")
        assert time.monotonic() - t0 < 60
        # the supervisor records the restart right after the new listener answers
        def board_row():
            rs = {x["service"]: x for x in httpx.get(f"{url}/v1/admin/services", headers=h, timeout=20).json()["value"]["services"]}
            return rs["board"] if rs["board"].get("last_restart_reason") else None
        row = _wait(board_row, 20, "the supervisor's restart record for the board")
        assert row["pid"] and row["pid"] != board_pid, row
        assert row["last_restart_reason"] == "restart by owner" and row["restarts"] == 1, row
        ev = _wait(lambda: _events(url, h, "board"), 20, "the board service_restarted event")
        assert ev[-1]["data"]["by"] == "owner" and "control port" in ev[-1]["data"]["reason"], ev[-1]
    finally:
        stop = base.cli(inst, "stop")
    assert stop.returncode == 0, stop.stdout + stop.stderr
    assert scan_env_marker(base.MARKER, inst["env"][base.MARKER]) == []


def _fake_releases_api(tag: str):
    """A local stand-in for GitHub's releases API: GET /repos/<repo>/releases/latest -> {tag_name}."""
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = json.dumps({"tag_name": tag, "html_url": f"https://example.invalid/{tag}"}).encode()
            ok = self.path.endswith("/releases/latest")
            self.send_response(200 if ok else 404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body) if ok else 0))
            self.end_headers()
            if ok:
                self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_admin_update_check_and_apply_backup_stop_upgrade_start(inst, tmp_path):
    """Updates (c-40e35d1d5d): the Releases check against a fixture reports available; apply goes through
    the supervisor and runs backup -> stop -> upgrade -> start (the install is the declared
    EDP_UPDATE_INSTALL_CMD fake, the rest is real: test_update's fixture)."""
    import test_update as tu

    api = _fake_releases_api("v99.0.0")
    inst["env"]["EDP_UPDATE_API"] = f"http://127.0.0.1:{api.server_address[1]}"
    inst["env"]["EDP_UPDATE_COMPAT_CMD"] = tu._fake(tu.PRINT_ROWS, "[]", "0")
    inst["env"]["EDP_UPDATE_INSTALL_CMD"] = tu._fake(tu.RECORD, str(tmp_path / "installed.json"), "0", "{wheel}", "{with}")
    tok = tu._started(inst)
    try:
        url = f"http://127.0.0.1:{inst['ports']['board']}"
        h = {"X-Participant": "owner", "X-Token": tok}
        v = httpx.get(f"{url}/v1/admin/updates", params={"force": "true"}, headers=h, timeout=30).json()["value"]
        assert v["latest"] == "99.0.0" and v["available"] is True and v["apply_refusal"] is None, v
        assert httpx.post(f"{url}/v1/admin/updates/apply", headers={"X-Participant": "owner"},
                          timeout=10).status_code == 403

        before = tu._status(inst)
        health_before = httpx.get(f"{url}/healthz", timeout=10).json()["started_at"]
        rel = tu._release(tmp_path / "rel")
        r = httpx.post(f"{url}/v1/admin/updates/apply", headers=h, json={"release_url": str(rel),
                                                                           "previous_url": tu._prev(tmp_path)[1]},
                       timeout=90)
        assert r.status_code == 202, r.text
        assert r.json()["value"]["by"] == "owner" and r.json()["value"]["state"] == "updating"
        res = tu._wait_result(inst)
        assert res["state"] == "ok" and res["to"] == "99.0.0", res

        # backup -> stop (the detached `heronry update`'s own output), then upgrade -> start (the helper's log)
        out = next(inst["home"].rglob("update-run.out")).read_text(encoding="utf-8", errors="replace")
        i_backup, i_stop = out.index("backed up the DB to"), out.index("stopped the supervisor and services")
        assert i_backup < i_stop, out
        log = next(inst["home"].rglob("update.log")).read_text(encoding="utf-8", errors="replace")
        assert log.index("install exit 0") < log.index("start exit 0"), log
        assert len(list(tu._db(inst).parent.glob("backups/edp8-*.db"))) == 1
        installed = json.loads((tmp_path / "installed.json").read_text(encoding="utf-8"))
        assert sum(a.endswith("-99.0.0-py3-none-any.whl") for a in installed) == 4
        after = tu._status(inst)
        for svc in ("board", "broker", "pool", "mcp", "supervisor"):
            assert after[svc]["state"] == "up" and after[svc]["pid"] != before[svc]["pid"], (svc, after[svc])
        assert httpx.get(f"{url}/healthz", timeout=10).json()["started_at"] != health_before
        last = httpx.get(f"{url}/v1/admin/updates", headers=h, timeout=30).json()["value"]["last"]
        assert last["request"]["by"] == "owner" and last["result"]["state"] == "ok", last
    finally:
        api.shutdown()
        base.cli(inst, "stop", "--force")
