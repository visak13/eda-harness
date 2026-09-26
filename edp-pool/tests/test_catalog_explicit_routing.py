"""S12: arbitrary model ids route by catalog metadata through the pool stack."""

import json

from edp_pool.codex_launcher import catalog_routes_codex
from edp_pool.composite_spawner import CompositeSpawner
from edp_pool.pi_launcher import catalog_routes_pi
from edp_pool.pty_launcher import build_env


class Fake:
    def __init__(self, name, calls):
        self.name = name
        self.calls = calls

    def launch(self, _sid, _role, _handle, **kwargs):
        self.calls.append((self.name, kwargs.get("model")))


def test_arbitrary_ids_route_to_pi_codex_and_claude(tmp_path):
    (tmp_path / "models.json").write_text(json.dumps({"models": {
        "plain-pi": {"harness": "pi", "provider": "openrouter"},
        "plain-codex": {"harness": "codex", "provider": "codex"},
        "gpt-looking-claude": {"harness": "claude", "provider": "claude"},
    }}), encoding="utf-8")
    calls = []
    claude = Fake("claude", calls)
    pi = Fake("pi", calls)
    codex = Fake("codex", calls)
    stack = CompositeSpawner(claude, pi, roles=set(), route_model=lambda m: catalog_routes_pi(m, str(tmp_path)))
    stack = CompositeSpawner(stack, codex, roles=set(), route_model=lambda m: catalog_routes_codex(m, str(tmp_path)))
    for mid in ("plain-pi", "plain-codex", "gpt-looking-claude"):
        stack.launch(mid, "engineer", "engineer.test", model=mid)
    assert calls == [("pi", "plain-pi"), ("codex", "plain-codex"),
                     ("claude", "gpt-looking-claude")]


def test_claude_catalog_entry_controls_compaction_window(tmp_path, monkeypatch):
    (tmp_path / "models.json").write_text(json.dumps({"models": {
        "opaque": {"harness": "claude", "provider": "claude", "auto_compact": 123456}},
        "seats": {"builder": {"model": "other", "auto_compact": 350000}},
        "roles": {"engineer": "builder"}}), encoding="utf-8")
    monkeypatch.delenv("EDP_AUTO_COMPACT_WINDOW", raising=False)
    monkeypatch.delenv("EDP_AUTO_COMPACT_WINDOW_ENGINEER", raising=False)
    env = build_env("s", "engineer", "engineer.s", None, agent_home=str(tmp_path), model="opaque")
    assert env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "123456"
