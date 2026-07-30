"""v7 — pool-owned external-neuron drivers (the codex neuron's
CronCreate+Monitor analog, armed via arm_external_driver -> these routes).

Pinned: arm spawns the driver (seam patched), re-arm replaces, registration
persists and is respawned on startup, disarm kills + forgets, spawn failure
refuses honestly (never a believed-but-absent heartbeat).
"""

import edp_pool.service as service_mod
from fastapi.testclient import TestClient

from edp_pool.service import PoolService, create_app
from edp_pool.spawner import FakeSpawner

H = {"Host": "127.0.0.1"}


def _svc(tmp_path, monkeypatch, pids):
    def fake_spawn(recipe_id, cmd, heartbeat_secs, broker_url):
        pids.append((recipe_id, cmd, heartbeat_secs))
        return 4000 + len(pids)
    monkeypatch.setattr(service_mod, "spawn_neuron_driver", fake_spawn)
    return PoolService(FakeSpawner(), state_path=tmp_path / "state.json")


def test_arm_spawns_and_persists(tmp_path, monkeypatch):
    pids = []
    svc = _svc(tmp_path, monkeypatch, pids)
    out = svc.arm_neuron_driver("recipe-x", "codex exec {PROMPT}", 900)
    assert out["ok"] and out["pid"] == 4001
    assert pids == [("recipe-x", "codex exec {PROMPT}", 900)]
    # persisted: a fresh service over the same state file knows it
    svc2 = PoolService(FakeSpawner(), state_path=tmp_path / "state.json")
    assert "recipe-x" in svc2.neuron_drivers


def test_rearm_replaces_not_duplicates(tmp_path, monkeypatch):
    pids = []
    svc = _svc(tmp_path, monkeypatch, pids)
    svc.arm_neuron_driver("recipe-x", "cmd1 {PROMPT}", 900)
    svc.arm_neuron_driver("recipe-x", "cmd2 {PROMPT}", 600)
    assert len(svc.neuron_drivers) == 1
    assert svc.neuron_drivers["recipe-x"]["cmd"] == "cmd2 {PROMPT}"


def test_respawn_on_startup(tmp_path, monkeypatch):
    pids = []
    svc = _svc(tmp_path, monkeypatch, pids)
    svc.arm_neuron_driver("recipe-x", "cmd {PROMPT}", 900)
    svc2 = _svc(tmp_path, monkeypatch, pids)   # same state file, new proc
    svc2.respawn_neuron_drivers()
    assert len(pids) == 2, "startup must re-spawn the persisted driver"
    assert svc2.neuron_drivers["recipe-x"]["pid"] == 4002


def test_disarm_forgets(tmp_path, monkeypatch):
    svc = _svc(tmp_path, monkeypatch, [])
    svc.arm_neuron_driver("recipe-x", "cmd {PROMPT}", 900)
    out = svc.disarm_neuron_driver("recipe-x")
    assert out["ok"] and svc.neuron_drivers == {}
    assert svc.disarm_neuron_driver("recipe-x")["ok"]   # idempotent


def test_spawn_failure_refuses_honestly(tmp_path, monkeypatch):
    monkeypatch.setattr(service_mod, "spawn_neuron_driver",
                        lambda *a: None)
    svc = PoolService(FakeSpawner(), state_path=tmp_path / "state.json")
    out = svc.arm_neuron_driver("recipe-x", "cmd {PROMPT}", 900)
    assert out["ok"] is False and "NOT armed" in out["refused"]
    assert svc.neuron_drivers == {}


def test_http_routes(tmp_path, monkeypatch):
    pids = []
    svc = _svc(tmp_path, monkeypatch, pids)
    c = TestClient(create_app(svc))
    r = c.post("/v1/neuron-driver", headers=H,
               json={"recipe_id": "recipe-x", "cmd": "x {PROMPT}"})
    assert r.status_code == 200 and r.json()["ok"]
    assert len(c.get("/v1/neuron-driver", headers=H).json()) == 1
    r = c.delete("/v1/neuron-driver/recipe-x", headers=H)
    assert r.status_code == 200 and r.json()["ok"]
    assert c.get("/v1/neuron-driver", headers=H).json() == []
