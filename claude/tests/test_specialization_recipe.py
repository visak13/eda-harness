"""specialization_recipe — the versioned recipe (vision phase 3).

Knowledge-as-links + the memory layer (steps/checklists/anti-patterns/
preferences/work-order), built incrementally; versioned (rollback
anchor); loadable by a specialist shell.
"""

from edp_contracts import ToolError, ToolOk


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


async def _spec(env):
    d = _ok(await env.call("create_specialization", name="Java Expert",
                           subject="Java / DDD", description="java ddd"))
    return d["spec_id"]


async def test_entries_build_incrementally_and_version_bumps(env):
    sid = await _spec(env)
    v1 = _ok(await env.call("add_spec_entry", spec_id=sid, kind="step",
                            text="model the aggregate roots first"))
    v2 = _ok(await env.call("add_spec_entry", spec_id=sid, kind="link",
                            text="https://martinfowler.com/bliki/DDD_Aggregate.html",
                            note="aggregate boundaries"))
    _ok(await env.call("add_spec_entry", spec_id=sid, kind="anti_pattern",
                       text="anemic domain model"))
    assert v2["version"] > v1["version"]
    spec = env.ctx.specs.load(sid)
    kinds = [e.kind for e in spec.entries]
    assert kinds == ["step", "link", "anti_pattern"]
    # knowledge-as-links: the URL is stored verbatim in text
    link = next(e for e in spec.entries if e.kind == "link")
    assert link.text.startswith("https://") and link.note


async def test_get_specialization_returns_the_recipe(env):
    sid = await _spec(env)
    _ok(await env.call("add_spec_entry", spec_id=sid, kind="checklist",
                       text="run the contract tests"))
    out = _ok(await env.call("get_specialization", spec_id=sid))
    assert out["spec"]["spec_id"] == sid
    assert any(e["kind"] == "checklist" for e in out["spec"]["entries"])


async def test_record_spec_version_writes_checkpoint(env):
    import json
    from pathlib import Path
    sid = await _spec(env)
    _ok(await env.call("add_spec_entry", spec_id=sid, kind="step",
                       text="do the thing"))
    out = _ok(await env.call("record_spec_version", spec_id=sid,
                             summary="reviewed: covers DDD basics"))
    assert out["version"] >= 1
    wl = Path(env.ctx.specs.root) / sid / "worklog.jsonl"
    entries = [json.loads(x) for x in
               wl.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert any(e.get("kind") == "version_checkpoint"
               and "reviewed" in e.get("summary", "") for e in entries)


async def test_add_entry_to_unknown_spec_is_precondition(env):
    res = await env.call("add_spec_entry", spec_id="nope", kind="step",
                         text="x")
    assert isinstance(res, ToolError)
    assert res.code == "tool_precondition"


async def test_get_unknown_spec_returns_null(env):
    out = _ok(await env.call("get_specialization", spec_id="nope"))
    assert out["spec"] is None


# ── SPECIALIZATION-LAYERED-RULESETS.md (2026-06-01), Stage 1 ──────────────
# Additive schema: SpecEntry.adherence + link_role, Specialization.extends,
# Action.concerns. Defaults must keep all pre-2026-06-01 data valid.

def test_legacy_spec_entry_dict_loads_with_defaults():
    # an entry persisted before 2026-06-01 has no adherence / link_role.
    from edp_claude.schemas import SpecEntry
    e = SpecEntry.model_validate({"kind": "checklist", "text": "run tests"})
    assert e.adherence == "expected"     # default weight, not discarded
    assert e.link_role is None


def test_legacy_specialization_dict_gains_universal_parent():
    # a spec persisted before 2026-06-01 has no `extends`; it must default
    # to the universal layer as its implicit parent (acceptance criterion).
    from datetime import datetime, timezone

    from edp_claude.schemas import Specialization
    now = datetime.now(timezone.utc)
    s = Specialization.model_validate({
        "spec_id": "spec-legacy", "neuron_id": "n-legacy",
        "name": "Legacy", "subject": "x",
        "entries": [{"kind": "step", "text": "do x"}],
        "created_at": now.isoformat(), "updated_at": now.isoformat(),
    })
    assert s.extends == ["spec-universal"]
    assert s.entries[0].adherence == "expected"


def test_legacy_action_dict_has_empty_concerns():
    from edp_claude.schemas import Action
    a = Action.model_validate({
        "action_id": "a1", "description": "build it", "status": "pending",
        "executor_mode": "subagent",
        "acceptance": {"kind": "manual_review"},
    })
    assert a.concerns == []


async def test_add_spec_entry_carries_adherence_and_link_role(env):
    sid = await _spec(env)
    _ok(await env.call("add_spec_entry", spec_id=sid, kind="link",
                       text="https://owasp.org/Top10/", link_role="ruleset",
                       adherence="required", note="OWASP top 10"))
    _ok(await env.call("add_spec_entry", spec_id=sid, kind="preference",
                       text="prefer composition", adherence="preferred"))
    spec = env.ctx.specs.load(sid)
    ruleset = next(e for e in spec.entries if e.link_role == "ruleset")
    assert ruleset.adherence == "required"
    pref = next(e for e in spec.entries if e.kind == "preference")
    assert pref.adherence == "preferred" and pref.link_role is None
    # a freshly created spec defaults its static parent to the universal layer
    assert spec.extends == ["spec-universal"]
