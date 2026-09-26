"""S12: arbitrary model ids route by catalog metadata through the pool stack."""

import json

from edp_pool.codex_launcher import is_codex_model
from edp_pool.composite_spawner import CompositeSpawner
from edp_pool.pi_launcher import is_pi_model


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
    stack = CompositeSpawner(claude, pi, roles=set(), route_model=lambda m: is_pi_model(m, str(tmp_path)))
    stack = CompositeSpawner(stack, codex, roles=set(), route_model=lambda m: is_codex_model(m, str(tmp_path)))
    for mid in ("plain-pi", "plain-codex", "gpt-looking-claude"):
        stack.launch(mid, "engineer", "engineer.test", model=mid)
    assert calls == [("pi", "plain-pi"), ("codex", "plain-codex"),
                     ("claude", "gpt-looking-claude")]
