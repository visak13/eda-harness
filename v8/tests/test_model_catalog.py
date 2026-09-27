"""S12: catalog migration, opaque-id routing, Admin validation and private stub spawn."""

from __future__ import annotations

import json

import pytest

from admin_support import ADMIN_H, make_env

from edp8 import harness, model_catalog, seat_choice, settings


def test_host_migration_preserves_role_order_defaults_and_caps(tmp_path):
    from pathlib import Path

    from edp_contracts.seats import parse

    source = json.loads((Path(__file__).resolve().parents[1] / "models.json").read_text(encoding="utf-8"))
    legacy = {k: v for k, v in source.items() if k != "models"}
    legacy["seats"] = {name: {k: v for k, v in row.items() if k not in {"provider", "effort_cap"}}
                       for name, row in legacy["seats"].items()}
    old_seats, old_roles = parse(legacy)
    migrated = model_catalog.migrate(legacy)
    assert migrated["role_models"] == source["role_models"]
    assert migrated["roles"] == source["roles"]
    new_seats, new_roles = parse(migrated)
    assert old_roles == new_roles
    for name in old_seats:
        before, after = old_seats[name], new_seats[name]
        assert (before.model, before.effort, before.context_window, before.auto_compact, before.max_output) == (
            after.model, after.effort, after.context_window, after.auto_compact, after.max_output)
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
    body["models"]["my-model"]["api_key"] = "must-not-enter-catalog"
    r = env.client.put("/v1/admin/models", json=body, headers=ADMIN_H)
    assert r.status_code == 422 and "credentials belong in secret settings" in r.text
    del body["models"]["my-model"]["api_key"]
    monkeypatch.setenv("EDP_PI_PROVIDER_CREDENTIALS", json.dumps({"openrouter": {"api_key": "test-only"}}))
    r = env.client.put("/v1/admin/models", json=body, headers=ADMIN_H)
    assert r.status_code == 200, r.text
    assert env.client.get("/v1/models", headers=ADMIN_H).json()["value"]["models"]["my-model"]["provider"] == "openrouter"
    r = env.client.post("/v1/admin/models/test-spawn", json={"model": "my-model", "role": "engineer"},
                        headers=ADMIN_H)
    assert r.status_code == 200 and "Stub seat received" in r.json()["value"]["reply"]
    assert r.json()["value"]["provider"] == "openrouter"
    body["models"].pop("my-model")
    body["role_models"]["engineer"] = ["base"]
    r = env.client.put("/v1/admin/models", json=body, headers=ADMIN_H)
    assert r.status_code == 200
    assert "my-model" not in env.client.get("/v1/models", headers=ADMIN_H).json()["value"]["models"]


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


# ---------------------------------------------------------------- S12 c-d38bf82b4a follow-ups (m-6724dc41ab)
def _row(harness="claude", **kw):
    base = {"harness": harness, "provider": harness, "effort_cap": "medium" if harness == "claude" else "high"}
    if harness == "claude":
        base.update(context_window=1_000_000, auto_compact=350_000)
    return {**base, **kw}


def test_unlisted_and_custom_roles_resolve_to_the_catalog_default(tmp_path, monkeypatch):
    """Owner bug m-549b8adc3a: a role with no role_models row still resolves to an explicit catalog model."""
    monkeypatch.delenv("EDP_HARNESSES", raising=False)
    raw = {"models": {"claude-opus-5-5": _row(), "claude-fable-5-1": _row()},
           "role_models": {"doctor": ["claude-fable-5-1"]}, "default_model": "claude-opus-5-5"}
    (tmp_path / "models.json").write_text(json.dumps(raw), encoding="utf-8")
    assert seat_choice.resolve(None, None, [], tmp_path, role="doctor").model == "claude-fable-5-1"
    for role in ("designer", "never-listed"):
        assert seat_choice.resolve(None, None, [], tmp_path, role=role).model == "claude-opus-5-5"
    # a default on an unselected harness falls to the first selected catalog model
    raw["models"]["gpt-x"] = _row("codex")
    raw["default_model"] = "gpt-x"
    (tmp_path / "models.json").write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setenv("EDP_HARNESSES", "claude")
    assert seat_choice.default_model(tmp_path) == "claude-fable-5-1"


def test_shipped_catalog_lists_doctor_and_a_default():
    from pathlib import Path

    shipped = json.loads((Path(__file__).resolve().parents[1] / "models.json").read_text(encoding="utf-8"))
    assert shipped["role_models"]["doctor"] and shipped["default_model"] in shipped["models"]
    for mid, row in shipped["models"].items():
        if row["harness"] == "codex":  # the window comes from Codex, never an invented number
            assert "context_window" not in row and "auto_compact" not in row, mid
        if row["harness"] == "claude":
            assert row["auto_compact"] == 350_000, mid  # owner ruling: Claude stays at 350k
    assert model_catalog.validate(shipped["models"], shipped["role_models"], shipped["default_model"]) == []


def test_merge_adds_new_rows_keeps_owner_edits_and_removals():
    v1 = {"models": {"a": _row(), "b": _row(), "c": _row()},
          "role_models": {"engineer": ["a", "b"], "qa": ["c"]}, "default_model": "a"}
    first, _ = model_catalog.merge(json.loads(json.dumps(v1)), v1)
    data = json.loads(json.dumps(first))
    data["models"]["b"]["auto_compact"] = 123_456   # owner edit
    del data["models"]["c"]                          # owner removal
    data["role_models"].pop("qa")
    data["role_models"]["engineer"] = ["a"]          # owner dropped b from the role
    v2 = json.loads(json.dumps(v1))
    v2["models"]["a"]["effort_cap"] = "low"          # shipped change to a row the owner never edited
    v2["models"]["b"]["auto_compact"] = 300_000      # shipped change to a row the owner edited
    v2["models"]["d"] = _row()                       # new model
    v2["role_models"]["engineer"].append("d")
    v2["role_models"]["doctor"] = ["d"]              # new role
    merged, changes = model_catalog.merge(data, v2)
    assert merged["models"]["a"]["effort_cap"] == "low"
    assert merged["models"]["b"]["auto_compact"] == 123_456
    assert "c" not in merged["models"] and "qa" not in merged["role_models"]
    assert merged["role_models"]["engineer"] == ["a", "d"]  # b stays out, d is new
    assert merged["role_models"]["doctor"] == ["d"]
    assert merged["_shipped"]["version"] == model_catalog.snapshot(v2)["version"] != first["_shipped"]["version"]
    assert "added role doctor" in changes
    again, more = model_catalog.merge(merged, v2)
    assert again == merged and more == []


def test_merge_into_a_pre_snapshot_copy_adds_rows_and_repairs_invented_codex_numbers(tmp_path):
    shipped = {"models": {"claude-opus-5-5": _row(), "gpt-6-sol": _row("codex")},
               "role_models": {"engineer": ["claude-opus-5-5"], "doctor": ["claude-opus-5-5"]},
               "default_model": "claude-opus-5-5"}
    old = {"models": {"claude-opus-5-5": _row(auto_compact=200_000),
                      "gpt-6-sol": _row("codex", context_window=272_000, auto_compact=200_000)},
           "role_models": {"engineer": ["claude-opus-5-5", "gpt-6-sol"]}}
    data_file, source = tmp_path / "data" / "models.json", tmp_path / "shipped.json"
    model_catalog.write(old, data_file)
    source.write_text(json.dumps(shipped), encoding="utf-8")
    changes = model_catalog.sync(data_file, source)
    got = json.loads(data_file.read_text(encoding="utf-8"))
    assert got["role_models"]["doctor"] == ["claude-opus-5-5"] and got["default_model"] == "claude-opus-5-5"
    assert got["role_models"]["engineer"] == ["claude-opus-5-5", "gpt-6-sol"]
    assert got["models"]["claude-opus-5-5"]["auto_compact"] == 200_000  # an owner number is never replaced
    assert "context_window" not in got["models"]["gpt-6-sol"]
    assert got["_shipped"]["version"] and changes
    assert model_catalog.sync(data_file, source) == []


def test_codex_rows_may_leave_window_to_codex_and_refusals_are_plain_text(tmp_path, monkeypatch):
    assert model_catalog.validate({"x": _row("codex")}, {"engineer": ["x"]}) == []
    assert model_catalog.validate({"x": _row("codex", auto_compact=500_000)}, {"engineer": ["x"]}) == []
    assert model_catalog.validate({"x": _row("codex", auto_compact=0)}, {"engineer": ["x"]})
    bare = {"harness": "claude", "provider": "claude", "effort_cap": "medium"}
    assert model_catalog.validate({"x": bare}, {"engineer": ["x"]})
    assert "default model 'y'" in model_catalog.validate({"x": _row()}, {"engineer": ["x"]}, "y")[0]
    home = tmp_path / "home"
    home.mkdir()
    base = {"models": {"base": _row()}, "role_models": {"engineer": ["base"]}, "default_model": "base"}
    (home / "models.json").write_text(json.dumps(base), encoding="utf-8")
    monkeypatch.setenv("EDP_AGENT_HOME", str(home))
    monkeypatch.setenv("EDP8_DATA", str(tmp_path / "data"))
    windows = {"gpt-6-sol": {"context_window": 272000, "auto_compact": 244800, "max_context_window": 872000}}
    monkeypatch.setattr(model_catalog, "codex_windows", lambda refresh=False: windows)
    env = make_env(tmp_path, monkeypatch)
    body = {"models": {"base": _row(), "gpt-6-sol": _row("codex")}, "role_models": {"engineer": ["base", "nope"]}}
    r = env.client.put("/v1/admin/models", json=body, headers=ADMIN_H)
    assert r.status_code == 422
    assert r.json()["error"]["message"] == "engineer: unknown model 'nope'"  # a sentence, never a repr
    body["role_models"]["engineer"] = ["base", "gpt-6-sol"]
    r = env.client.put("/v1/admin/models", json=body, headers=ADMIN_H)
    assert r.status_code == 200, r.text
    view = r.json()["value"]
    assert view["default_model"] == "base"  # an omitted default keeps the current one
    assert view["harness_defaults"]["gpt-6-sol"] == {**windows["gpt-6-sol"], "source": "codex debug models"}


def test_codex_windows_reads_codex_debug_models(monkeypatch):
    import subprocess
    from types import SimpleNamespace

    out = json.dumps({"models": [{"slug": "gpt-6-sol", "context_window": 272000, "max_context_window": 872000},
                                 {"slug": "broken"}]})
    monkeypatch.setattr("edp_contracts.toolpath.find_tool", lambda *a, **k: "codex")
    monkeypatch.setattr(model_catalog, "_codex_windows", None)
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: calls.append(argv) or SimpleNamespace(stdout=out))
    got = model_catalog.codex_windows(refresh=True)
    assert calls == [["codex", "debug", "models"]]
    assert got == {"gpt-6-sol": {"context_window": 272000, "max_context_window": 872000, "auto_compact": 244800}}


def test_read_falls_back_to_the_shipped_catalog_and_admin_never_500s(tmp_path, monkeypatch):
    # t-bdd34121ee: a home with no catalog reads the shipped one; a build shipping none is a plain 404
    from edp8 import materialise
    monkeypatch.setattr(settings, "agent_home", lambda: tmp_path / "empty-home")
    assert not (settings.data_dir() / "models.json").exists()
    assert model_catalog.read()["models"]
    env = make_env(tmp_path, monkeypatch)
    assert env.client.get("/v1/admin/models", headers=ADMIN_H).status_code == 200

    def no_source():
        raise FileNotFoundError("no source")
    monkeypatch.setattr(materialise, "source_root", no_source)
    r = env.client.get("/v1/admin/models", headers=ADMIN_H)
    assert r.status_code == 404 and "heronry init" in r.json()["error"]["message"], r.text


def test_no_checkout_outside_dev_mode(monkeypatch):
    # the editable-install record is a dev-mode lookup only; an installed board never looks for a checkout
    from edp8 import materialise
    monkeypatch.delenv("EDP_DEV", raising=False)
    assert materialise.checkout_root() is None
    monkeypatch.setenv("EDP_DEV", "1")
    root = materialise.checkout_root()
    assert root is not None and (root / "models.json").is_file()


def test_put_refuses_setting_a_default_on_an_unselected_harness(tmp_path, monkeypatch):
    """t-05df836c49 (qa m-d757122a72): with codex unselected, a PUT that makes a codex model a role's default
    (or the catalog default) is refused in words; a stale codex default the PUT leaves alone still saves."""
    home = tmp_path / "home"
    home.mkdir()
    base = {"models": {"claude-opus-5-5": _row(), "claude-fable-5-1": _row(), "gpt-6-astra": _row("codex")},
            "role_models": {"engineer": ["claude-opus-5-5", "gpt-6-astra"], "adversary": ["gpt-6-astra"]},
            "default_model": "claude-opus-5-5"}
    (home / "models.json").write_text(json.dumps(base), encoding="utf-8")
    monkeypatch.setenv("EDP_AGENT_HOME", str(home))
    monkeypatch.setenv("EDP8_DATA", str(tmp_path / "data"))
    monkeypatch.setattr(model_catalog, "codex_windows", lambda refresh=False: {})
    env = make_env(tmp_path, monkeypatch)
    monkeypatch.setenv("EDP_HARNESSES", "claude")
    body = {"models": base["models"], "role_models": {**base["role_models"], "engineer": ["gpt-6-astra", "claude-opus-5-5"]}}
    r = env.client.put("/v1/admin/models", json=body, headers=ADMIN_H)
    assert r.status_code == 422
    assert r.json()["error"]["message"] == "engineer: default gpt-6-astra needs the codex harness: select it or pick another"
    r = env.client.put("/v1/admin/models", json={**body, "role_models": base["role_models"], "default_model": "gpt-6-astra"},
                       headers=ADMIN_H)
    assert r.status_code == 422 and "default model gpt-6-astra needs the codex harness" in r.text
    # the adversary's stale codex default is unchanged by this PUT: it saves (the page warns instead)
    body["role_models"]["engineer"] = ["claude-fable-5-1", "claude-opus-5-5", "gpt-6-astra"]
    r = env.client.put("/v1/admin/models", json=body, headers=ADMIN_H)
    assert r.status_code == 200, r.text
    assert r.json()["value"]["role_models"]["adversary"] == ["gpt-6-astra"]
    # with codex selected the same default is accepted
    monkeypatch.setenv("EDP_HARNESSES", "claude,codex")
    body["role_models"]["engineer"] = ["gpt-6-astra", "claude-opus-5-5"]
    r = env.client.put("/v1/admin/models", json=body, headers=ADMIN_H)
    assert r.status_code == 200, r.text


def _pre_migration_model(home, role):
    """What the pool gave a role from the historic file: role_models[0], else its legacy `roles` seat."""
    from edp_contracts.seats import catalog_model_for, seat_for_role
    seat = seat_for_role(home, role)
    return catalog_model_for(home, role) or (seat.model if seat else None)


def test_s12_parity_on_the_real_pre_migration_catalog(tmp_path):
    """qa c-c0b35be596 (architect m-a3a8943c39): the real pre-S12 file (git show cb84bba^:v8/models.json, prose
    notes dropped) resolves every agent role to the same model after migration, on the board and the pool;
    a person's role (owner) has no model any more and is refused (owner m-da9a2ae62f)."""
    from pathlib import Path

    from edp_contracts.roles import NonAgentRole, is_non_agent
    from edp_contracts.seats import catalog_model_for, seat_for_role

    legacy = json.loads((Path(__file__).parent / "fixtures" / "models_pre_s12.json").read_text(encoding="utf-8"))
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir(), new.mkdir()
    (old / "models.json").write_text(json.dumps(legacy), encoding="utf-8")
    migrated = model_catalog.migrate(legacy)
    (new / "models.json").write_text(json.dumps(migrated), encoding="utf-8")
    roles = set(legacy["role_models"]) | set(legacy["roles"])
    assert "owner" in roles and "sme" in roles
    for col in [k for k in migrated if k == "role_models" or k.startswith("roles")]:
        assert not any(is_non_agent(r) for r in migrated[col]), col
    for role in sorted(roles):
        if is_non_agent(role):
            with pytest.raises(NonAgentRole):
                seat_choice.resolve(None, None, [], new, role=role)
            assert catalog_model_for(new, role) is None and seat_for_role(new, role) is None
            continue
        before = _pre_migration_model(old, role)
        assert before, role
        assert seat_choice.resolve(None, None, [], new, role=role).model == before, role
        assert _pre_migration_model(new, role) == before, role  # the pool's lookup on the migrated file


def test_migration_invents_no_window_for_a_non_claude_row():
    """S12 c-f9ccee4071 (owner m-bfe93b313c): a migrated Codex or Pi row carries no invented window or
    compaction (Codex reports its own); a number the legacy seat row wrote survives, and a Claude row keeps
    the fleet's 1M / 350k."""
    from pathlib import Path

    legacy = json.loads((Path(__file__).parent / "fixtures" / "models_pre_s12.json").read_text(encoding="utf-8"))
    legacy["role_models"]["engineer"].append("openai/gpt-new")
    legacy["seats"]["tuned-codex"] = {"model": "gpt-tuned", "harness": "codex", "auto_compact": 400000,
                                      "context_window": 900000}
    legacy["role_models"]["sme"].append("tuned-codex")
    rows = model_catalog.migrate(legacy)["models"]
    for mid in ("gpt-6-astra", "gpt-6-sol", "openai/gpt-new"):
        assert rows[mid]["harness"] != "claude", mid
        assert "context_window" not in rows[mid] and "auto_compact" not in rows[mid], (mid, rows[mid])
    assert (rows["tuned-codex"]["context_window"], rows["tuned-codex"]["auto_compact"]) == (900000, 400000)
    assert (rows["claude-opus-5-5"]["context_window"], rows["claude-opus-5-5"]["auto_compact"]) == (1_000_000, 350_000)


def test_the_shipped_codex_seat_row_carries_no_invented_window():
    from pathlib import Path

    raw = json.loads((Path(__file__).resolve().parents[1] / "models.json").read_text(encoding="utf-8"))
    for name, row in {**raw["seats"], **raw["models"]}.items():
        if row.get("harness") == "codex":
            assert "context_window" not in row and "auto_compact" not in row, name
