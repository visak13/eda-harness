"""v7 — arm/disarm_external_driver: the external neuron's
CronCreate+Monitor analog, as MCP verbs (the pool HTTP seam patched).
"""

from datetime import datetime, timezone

import edp_claude.tools._tools as tools_mod
from edp_contracts import ToolOk

from edp_claude.schemas import Recipe

RID = "recipe-extdrv"


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _save_recipe(env):
    now = datetime.now(timezone.utc)
    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=RID, user_goal_verbatim="g", domain="generic",
        state="executing",
        comprehension={"branches": [], "expected_outcomes": []},
        steps=[{"step_id": "s1", "kind": "work", "description": "d",
                "status": "in_progress", "depends_on": [],
                "execution": "spawn_planner"}],
        context={}, created_at=now, updated_at=now,
    )))


async def test_arm_posts_the_registration(env, monkeypatch):
    _save_recipe(env)
    sent = []
    monkeypatch.setattr(
        tools_mod, "_pool_http",
        lambda m, p, payload=None: (sent.append((m, p, payload)),
                                    {"ok": True, "note": "armed"})[-1])
    d = _ok(await env.call("arm_external_driver", recipe_id=RID,
                           resume_cmd="codex exec resume --last {PROMPT}",
                           heartbeat_secs=900))
    assert d["ok"] and sent[0][0] == "POST"
    assert sent[0][2]["recipe_id"] == RID
    assert sent[0][2]["heartbeat_secs"] == 900


async def test_arm_refuses_cmd_without_prompt_token(env, monkeypatch):
    _save_recipe(env)
    monkeypatch.setattr(tools_mod, "_pool_http",
                        lambda *a, **k: {"ok": True})
    res = await env.call("arm_external_driver", recipe_id=RID,
                         resume_cmd="codex exec resume --last")
    assert not isinstance(res, ToolOk) and "{PROMPT}" in str(res)


async def test_arm_refuses_when_pool_down_never_silent(env, monkeypatch):
    _save_recipe(env)
    def boom(*a, **k):
        raise ConnectionError("pool down")
    monkeypatch.setattr(tools_mod, "_pool_http", boom)
    res = await env.call("arm_external_driver", recipe_id=RID,
                         resume_cmd="x {PROMPT}")
    assert not isinstance(res, ToolOk)
    assert "NOT armed" in str(res)


async def test_disarm(env, monkeypatch):
    _save_recipe(env)
    calls = []
    monkeypatch.setattr(
        tools_mod, "_pool_http",
        lambda m, p, payload=None: (calls.append((m, p)),
                                    {"ok": True, "note": "stopped"})[-1])
    d = _ok(await env.call("disarm_external_driver", recipe_id=RID))
    assert d["ok"] and calls == [("DELETE", f"/v1/neuron-driver/{RID}")]
