"""S12: catalog migration, opaque-id routing, Admin validation and private stub spawn."""

from __future__ import annotations

import json

from admin_support import ADMIN_H, make_env

from edp8 import harness, model_catalog, seat_choice, settings


def test_host_migration_preserves_role_order_defaults_and_caps(tmp_path):
    from pathlib import Path
    source = json.loads((Path(__file__).resolve().parents[1] / "models.json").read_text(encoding="utf-8"))
    legacy = {k: v for k, v in source.items() if k != "models"}
    migrated = model_catalog.migrate(legacy)
    assert migrated["role_models"] == source["role_models"]
    assert migrated["roles"] == source["roles"]
    assert migrated["seats"] == source["seats"]
    (tmp_path / "models.json").write_text(json.dumps(migrated), encoding="utf-8")
    for role, ids in source["role_models"].items():
        assert seat_choice.resolve(None, None, [], tmp_path, role=role).model == ids[0]
        for mid in ids:
            cap = migrated["models"][mid]["effort_cap"]
            effort = seat_choice.resolve(mid, "high", [], tmp_path, role=role).effort
            assert effort == ("medium" if cap == "medium" else "high")


def test_opaque_ids_route_only_by_metadata(tmp_path, monkeypatch):
    raw = {"models": {"my-model": {"harness": "pi", "provider": "openrouter", "effort_cap": "high"},
                      "gpt-looking": {"harness": "claude", "provider": "claude", "effort_cap": "medium"},
                      "plain": {"harness": "codex", "provider": "codex", "effort_cap": "high"}},
           "role_models": {"engineer": ["my-model", "plain", "gpt-looking"]}}
    (tmp_path / "models.json").write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setenv("EDP_AGENT_HOME", str(tmp_path))
    assert seat_choice.is_pi_seat("my-model", tmp_path)
    assert not seat_choice.is_pi_seat("plain", tmp_path)
    assert harness.harness_of("gpt-looking", raw["models"]) == "claude"
    assert seat_choice.resolve("my-model", "high", [], tmp_path, role="engineer").effort == "high"
    assert seat_choice.resolve("gpt-looking", "high", [], tmp_path, role="engineer").effort == "medium"


def test_admin_catalog_validation_and_stub_spawn(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    base = model_catalog.migrate({"seats": {}, "role_models": {"engineer": ["base"]}})
    base["models"]["base"] = {"harness": "claude", "provider": "claude", "effort_cap": "medium",
                                "context_window": 1000000, "auto_compact": 350000}
    (home / "models.json").write_text(json.dumps(base), encoding="utf-8")
    monkeypatch.setenv("EDP_AGENT_HOME", str(home))
    monkeypatch.setenv("EDP8_DATA", str(tmp_path / "data"))
    env = make_env(tmp_path, monkeypatch)
    body = {"models": {**base["models"], "my-model": {"harness": "bad", "provider": "openrouter",
             "effort_cap": "high", "context_window": 200000, "auto_compact": 100000}},
            "role_models": {"engineer": ["my-model", "base"]}}
    r = env.client.put("/v1/admin/models", json=body, headers=ADMIN_H)
    assert r.status_code == 422 and "unknown harness" in r.text
    body["models"]["my-model"]["harness"] = "pi"
    r = env.client.put("/v1/admin/models", json=body, headers=ADMIN_H)
    assert r.status_code == 422 and "credential missing" in r.text
    monkeypatch.setenv("EDP_PI_PROVIDER_CREDENTIALS", json.dumps({"openrouter": {"api_key": "test-only"}}))
    r = env.client.put("/v1/admin/models", json=body, headers=ADMIN_H)
    assert r.status_code == 200, r.text
    assert env.client.get("/v1/models", headers=ADMIN_H).json()["value"]["models"]["my-model"]["provider"] == "openrouter"
    r = env.client.post("/v1/admin/models/test-spawn", json={"model": "my-model", "role": "engineer"},
                        headers=ADMIN_H)
    assert r.status_code == 200 and "Stub seat received" in r.json()["value"]["reply"]
    assert r.json()["value"]["provider"] == "openrouter"


def test_init_copy_of_v8_respects_codex_only_selection(tmp_path, monkeypatch):
    from pathlib import Path

    from edp8.setup import init_cmd
    source = Path(__file__).resolve().parents[1]
    target = tmp_path / "installed"
    monkeypatch.setenv("EDP8_HOME", str(target))
    monkeypatch.delenv("EDP_AGENT_HOME", raising=False)
    monkeypatch.delenv("EDP_HARNESSES", raising=False)
    assert init_cmd(["--force", "--yes", "--harness", "codex", "--agent-home-source", str(source)]) == 0
    raw = model_catalog.read()
    assert "harnesses" not in raw
    assert harness.selected(raw) == ("codex",)
    catalog = seat_choice.catalog(settings.agent_home())
    assert catalog["engineer"] == ["gpt-6-sol"]
