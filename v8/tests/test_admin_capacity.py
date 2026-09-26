"""S6 Admin → Services → Capacity (c-002a8ba1b5; design §4.14(d)) on a PRIVATE pool: a real edp-pool process
(FakeSpawner, free port, temp state file) behind the board's `/v1/admin/capacity`. The read lists the
total and live caps, each class cap (checker exempt), a per-role row for every role of every workflow a
running epic pins, and live usage; writes go through the pool's `/v1/limits` without a restart, clamp to
>= 1, and survive a restart of that pool process."""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from admin_support import ADMIN_H, BOB_H, make_env

ROOT = Path(__file__).resolve().parents[2]
POOL_PY = ROOT / "edp-pool" / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")

pytestmark = pytest.mark.skipif(not POOL_PY.is_file(), reason="needs the edp-pool venv")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class PrivatePool:
    def __init__(self, state: Path):
        self.state, self.port, self.proc = state, _free_port(), None
        self.url = f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        code = ("import uvicorn; from edp_pool.service import create_app; "
                f"uvicorn.run(create_app(state_path={str(self.state)!r}), host='127.0.0.1', port={self.port}, "
                "log_level='warning')")
        self.proc = subprocess.Popen([str(POOL_PY), "-c", code])
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                if httpx.get(f"{self.url}/v1/limits", timeout=1).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        raise AssertionError("private pool did not come up")

    def stop(self) -> None:
        # our own child, by its Popen handle (never by image name)
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(10)


@pytest.fixture
def pool(tmp_path, monkeypatch):
    p = PrivatePool(tmp_path / "pool-state.json")
    p.start()
    monkeypatch.setenv("EDP_POOL_URL", p.url)
    yield p
    p.stop()


@pytest.fixture
def env(tmp_path, monkeypatch, pool):
    e = make_env(tmp_path, monkeypatch)
    r = e.client.post("/v1/tickets", headers=ADMIN_H,
                      json={"kind": "epic", "work_type": "feature", "title": "running", "words": "w"})
    assert r.status_code == 200, r.text
    return e


def test_capacity_reads_caps_roles_and_usage(env, pool):
    for role, handle, cls in [("engineer", "engineer.s-1", "builder"), ("architect", "architect.e-1", "planner"),
                              ("qa", "qa.e-1", "checker")]:
        r = httpx.post(f"{pool.url}/v1/spawn", json={"role": role, "handle": handle, "capacity_class": cls,
                                                    "mode": "headless"}, timeout=20)
        assert r.status_code == 200, r.text
    v = env.client.get("/v1/admin/capacity", headers=ADMIN_H).json()["value"]
    assert v["total"]["in_use"] == 3 and v["live"]["in_use"] == 3
    assert v["live"]["cap"] == v["total"]["cap"] * 2
    cls = {c["class"]: c for c in v["classes"]}
    assert cls["builder"]["in_use"] == 1 and cls["planner"]["in_use"] == 1
    assert cls["checker"]["exempt"] and cls["checker"]["cap"] is None
    roles = {r["role"]: r for r in v["roles"]}
    # every spawnable role of the Standard workflow the running epic pins
    assert {"architect", "engineer", "qa", "adversary", "sme"} <= set(roles)
    assert roles["engineer"]["capacity_class"] == "builder" and roles["engineer"]["in_use"] == 1
    assert roles["engineer"]["workflows"] == ["standard@1"]
    assert "0 cap" in v["note"] and "Pausing" in v["note"]


def test_capacity_write_applies_now_clamps_and_survives_pool_restart(env, pool):
    r = env.client.put("/v1/admin/capacity", headers=ADMIN_H,
                       json={"max_total_shells": 0, "max_live_shells": 12, "classes": {"builder": 2, "planner": 0},
                             "role_caps": {"engineer": 1}})
    assert r.status_code == 200, r.text
    v = r.json()["value"]
    assert v["total"]["cap"] == 1 and v["live"]["cap"] == 12
    cls = {c["class"]: c for c in v["classes"]}
    assert cls["builder"]["cap"] == 2 and cls["planner"]["cap"] == 1 and cls["builder"]["overridden"]
    roles = {r["role"]: r for r in v["roles"]}
    assert roles["engineer"]["cap"] == 1 and roles["engineer"]["overridden"]
    # applied by the running pool without a restart
    lim = httpx.get(f"{pool.url}/v1/limits").json()
    assert lim["max_workers"] == 2 and lim["role_caps"] == {"engineer": 1}
    # and persisted: restart the private pool process on the same state file
    pool.stop()
    pool.start()
    v2 = env.client.get("/v1/admin/capacity", headers=ADMIN_H).json()["value"]
    assert v2["live"]["cap"] == 12 and {c["class"]: c["cap"] for c in v2["classes"]}["builder"] == 2
    assert {r["role"]: r["cap"] for r in v2["roles"]}["engineer"] == 1
    # clearing a role override falls back to the workflow's declared cap (none for Standard engineer)
    r = env.client.put("/v1/admin/capacity", headers=ADMIN_H, json={"role_caps": {"engineer": None},
                                                                  "clear": ["max_total_shells"]})
    roles = {x["role"]: x for x in r.json()["value"]["roles"]}
    assert roles["engineer"]["cap"] is None and not roles["engineer"]["overridden"]


def test_capacity_refusals_are_said(env, pool):
    assert env.client.get("/v1/admin/capacity", headers=BOB_H).status_code == 403
    r = env.client.put("/v1/admin/capacity", headers=ADMIN_H, json={"classes": {"checker": 3}})
    assert r.status_code == 422 and "exempt" in r.text
    assert env.client.put("/v1/admin/capacity", headers=ADMIN_H, json={}).status_code == 422
    pool.stop()
    r = env.client.get("/v1/admin/capacity", headers=ADMIN_H)
    assert r.status_code == 503 and "pool" in r.text
