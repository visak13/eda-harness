"""v7 follow-up — panel-driven durable suspend/resume.

The routes shell out to claude's recipe_ctl (the real W11 tool layer); the
subprocess seam (`run_recipe_ctl`) is a module function so these tests patch
it and pin the ROUTE contract: verb mapping, verbatim envelope relay, and
the guard chain. The ctl itself is smoke-tested in the claude project.
"""

import edp_pool.service as service_mod
from fastapi.testclient import TestClient

from edp_pool.service import PoolService, create_app
from edp_pool.spawner import FakeSpawner


def _client(tmp_path, monkeypatch, calls):
    def fake_ctl(verb, recipe_id, timeout_s=300):
        calls.append((verb, recipe_id))
        return {"ok": True, "data": {"recipe_id": recipe_id, "verb": verb},
                "error": None}
    monkeypatch.setattr(service_mod, "run_recipe_ctl", fake_ctl)
    svc = PoolService(FakeSpawner(), state_path=tmp_path / "state.json")
    return TestClient(create_app(svc))


def test_suspend_route_drives_the_ctl_and_relays_verbatim(
        tmp_path, monkeypatch):
    calls = []
    c = _client(tmp_path, monkeypatch, calls)
    r = c.post("/v1/recipes/recipe-x/suspend", headers={"Host": "127.0.0.1"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["data"]["verb"] == "suspend"
    assert calls == [("suspend", "recipe-x")]


def test_resume_route_is_distinct_from_the_process_resume(
        tmp_path, monkeypatch):
    calls = []
    c = _client(tmp_path, monkeypatch, calls)
    r = c.post("/v1/recipes/recipe-x/resume-recipe", headers={"Host": "127.0.0.1"})
    assert r.status_code == 200 and calls == [("resume", "recipe-x")]
    # the W12 process-level fan-out still exists, untouched, at /resume
    r2 = c.post("/v1/recipes/recipe-x/resume", headers={"Host": "127.0.0.1"})
    assert r2.status_code == 200
    assert "handles" in r2.json()   # the process fan-out shape, not the ctl


def test_ctl_refusal_is_relayed_not_paraphrased(tmp_path, monkeypatch):
    def refusing(verb, recipe_id, timeout_s=300):
        return {"ok": False, "data": None,
                "error": "unknown recipe 'recipe-x'"}
    monkeypatch.setattr(service_mod, "run_recipe_ctl", refusing)
    svc = PoolService(FakeSpawner(), state_path=tmp_path / "state.json")
    c = TestClient(create_app(svc))
    r = c.post("/v1/recipes/recipe-x/suspend", headers={"Host": "127.0.0.1"})
    assert r.json()["ok"] is False
    assert "unknown recipe" in r.json()["error"]
