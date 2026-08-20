"""observe() MCP tool — validates the rx spec, persists it, returns a
consumable {subscription_id, bound_to, monitor_cmd}."""

from pathlib import Path

from edp_contracts import ToolError, ToolOk


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


async def test_observe_returns_subscription_and_monitor_cmd(env):
    out = _ok(await env.call(
        "observe",
        spec="rx.merge(rx.broker(me), rx.worklog(plan_id), rx.pool())",
        bindings={"me": "neuron:r1", "plan_id": "p1"}))
    assert out["subscription_id"].startswith("sub-")
    assert set(out["bound_to"]) == {"broker", "worklog", "pool"}
    cmd = out["monitor_cmd"]
    assert "edp_claude.reactive.driver" in cmd
    assert "--spec-file" in cmd
    assert "--bindings-file" in cmd


async def test_observe_monitor_cmd_is_bash_safe(env):
    # 2026-05-29 planner Inc.2: bare `python` resolved to the wrong venv
    # and backslash paths broke under bash. The cmd must pin THIS venv's
    # interpreter (sys.executable) and use forward-slash paths.
    import sys

    out = _ok(await env.call(
        "observe", spec="rx.broker(me)", bindings={"me": "x"}))
    cmd = out["monitor_cmd"]
    # no Windows backslashes anywhere (bash strips them → exit 127)
    assert "\\" not in cmd
    # pinned to the running interpreter (not bare `python`)
    assert not cmd.startswith("python ")
    assert Path(sys.executable).name in cmd          # e.g. python.exe
    assert Path(sys.executable).as_posix() in cmd


async def test_observe_monitor_cmd_bakes_agent_home_and_urls(env):
    # 2026-06-01 "rx not working": the driver subprocess resolves its
    # worklog path from EDP_AGENT_HOME and broker/pool from the URL envs.
    # The Monitor may NOT inherit this MCP server's env, so the cmd must
    # BAKE them in — otherwise the driver tails the wrong file (silently
    # dead subscription) and the planner falls back to the slow heartbeat.
    out = _ok(await env.call(
        "observe", spec="rx.worklog(plan_id)", bindings={"plan_id": "p1"}))
    cmd = out["monitor_cmd"]
    agent_home = env.ctx.recipes.root.parent.as_posix()
    # the baked agent_home is the SAME root the plan store writes under, so
    # the driver tails <agent_home>/.plans/p1/worklog.jsonl — the real path
    assert f'EDP_AGENT_HOME="{agent_home}"' in cmd
    assert "EDP_BROKER_URL=" in cmd and "EDP_POOL_URL=" in cmd
    # env is set BEFORE the interpreter invocation (bash inline-env form)
    assert cmd.index("EDP_AGENT_HOME") < cmd.index("reactive.driver")


async def test_observe_persists_spec_file(env):
    out = _ok(await env.call(
        "observe", spec="rx.broker(me)", bindings={"me": "x"},
        subscription_id="sub-fixed"))
    assert out["subscription_id"] == "sub-fixed"
    spec_path = env.ctx.recipes.root.parent / ".reactive" / "sub-fixed.spec"
    assert spec_path.read_text(encoding="utf-8") == "rx.broker(me)"


async def test_observe_rejects_non_observable_spec(env):
    res = await env.call("observe", spec="1 + 1")
    assert isinstance(res, ToolError)
    assert "Observable" in res.message


async def test_observe_rejects_bad_spec(env):
    res = await env.call("observe", spec="rx.no_such_source()")
    assert isinstance(res, ToolError)
    assert "failed to evaluate" in res.message


async def test_observe_blocks_dangerous_builtins(env):
    res = await env.call("observe", spec="__import__('os').system('echo hi')")
    assert isinstance(res, ToolError)   # no __import__ in restricted builtins


async def test_observe_no_bindings_omits_bindings_flag(env):
    out = _ok(await env.call("observe", spec="rx.timer(1000)"))
    assert "--bindings-file" not in out["monitor_cmd"]
    assert out["bound_to"] == []        # timer is pure (no provider source)


# ── s17 FA2-F2 / RC2: idempotent reuse + stale-artifact GC ──────────────────

async def test_observe_same_subscription_id_is_idempotent(env):
    # Re-arming the SAME subscription (same sid + spec + bindings) must NOT
    # mint a second driver: it returns reused=True + the identical monitor_cmd,
    # and leaves exactly one .spec artifact. (RC2: one logical subscription =
    # one live driver.)
    root = env.ctx.recipes.root.parent / ".reactive"
    first = _ok(await env.call(
        "observe", spec="rx.broker(me)", bindings={"me": "x"},
        subscription_id="sub-idem"))
    assert first["reused"] is False
    second = _ok(await env.call(
        "observe", spec="rx.broker(me)", bindings={"me": "x"},
        subscription_id="sub-idem"))
    assert second["reused"] is True
    assert second["subscription_id"] == "sub-idem"
    assert second["monitor_cmd"] == first["monitor_cmd"]
    assert list(root.glob("sub-idem.spec")) == [root / "sub-idem.spec"]
    # F42#3: .spec + .bindings.json + .runtime.json (owner/rate identity)
    assert len(list(root.glob("sub-idem*"))) == 3


async def test_observe_same_sid_different_spec_is_respec_not_reuse(env):
    # A DIFFERENT spec under the same sid is a genuine re-spec, not a reuse:
    # reused=False and the persisted spec is overwritten.
    root = env.ctx.recipes.root.parent / ".reactive"
    _ok(await env.call(
        "observe", spec="rx.broker(me)", bindings={"me": "x"},
        subscription_id="sub-respec"))
    out = _ok(await env.call(
        "observe", spec="rx.worklog(plan_id)", bindings={"plan_id": "p1"},
        subscription_id="sub-respec"))
    assert out["reused"] is False
    assert (root / "sub-respec.spec").read_text(encoding="utf-8") == \
        "rx.worklog(plan_id)"


async def test_observe_generated_sid_is_never_reused(env):
    # Without an explicit subscription_id every call is a fresh subscription.
    a = _ok(await env.call("observe", spec="rx.broker(me)", bindings={"me": "x"}))
    b = _ok(await env.call("observe", spec="rx.broker(me)", bindings={"me": "x"}))
    assert a["reused"] is False and b["reused"] is False
    assert a["subscription_id"] != b["subscription_id"]


async def test_observe_gc_sweeps_stale_specs_keeps_live_and_subdirs(env, monkeypatch):
    # GC sweeps abandoned sub-*.spec triplets older than the TTL on the next
    # arm, never the one being armed, and never the registry/ + effect_audit/
    # subdirs.
    import os

    from edp_claude.tools import _tools

    root = env.ctx.recipes.root.parent / ".reactive"
    root.mkdir(parents=True, exist_ok=True)
    # an abandoned triplet, backdated well past the TTL
    for suffix in (".spec", ".bindings.json", ".effect.json"):
        (root / f"sub-stale{suffix}").write_text("old", encoding="utf-8")
    old = 1.0   # epoch second 1 → ancient
    for suffix in (".spec", ".bindings.json", ".effect.json"):
        os.utime(root / f"sub-stale{suffix}", (old, old))
    # the durable subdirs that must survive
    (root / "registry").mkdir(exist_ok=True)
    (root / "registry" / "rule.json").write_text("{}", encoding="utf-8")
    (root / "effect_audit").mkdir(exist_ok=True)
    (root / "effect_audit" / "log.jsonl").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(_tools, "_REACTIVE_SPEC_TTL_SECS", 60)
    out = _ok(await env.call(
        "observe", spec="rx.broker(me)", bindings={"me": "y"},
        subscription_id="sub-fresh"))
    assert out["reused"] is False

    # stale triplet gone …
    assert not (root / "sub-stale.spec").exists()
    assert not (root / "sub-stale.bindings.json").exists()
    assert not (root / "sub-stale.effect.json").exists()
    # … the freshly-armed one kept …
    assert (root / "sub-fresh.spec").exists()
    # … and the durable subdirs untouched.
    assert (root / "registry" / "rule.json").exists()
    assert (root / "effect_audit" / "log.jsonl").exists()


def test_gc_stale_subscriptions_is_age_scoped_and_keeps_target(tmp_path):
    # Direct unit of the GC helper: only artifacts older than ttl are swept;
    # the `keep` sid and recent artifacts survive.
    import os

    from edp_claude.tools._tools import _gc_stale_subscriptions

    root = tmp_path / ".reactive"
    root.mkdir()
    for sid, mtime in (("sub-old", 1.0), ("sub-recent", 9_990.0),
                       ("sub-keep", 1.0)):
        (root / f"{sid}.spec").write_text("s", encoding="utf-8")
        os.utime(root / f"{sid}.spec", (mtime, mtime))

    removed = _gc_stale_subscriptions(
        root, keep="sub-keep", ttl_secs=60, now_ts=10_000.0)

    assert removed == 1                              # only sub-old
    assert not (root / "sub-old.spec").exists()
    assert (root / "sub-recent.spec").exists()       # within ttl
    assert (root / "sub-keep.spec").exists()         # protected target
