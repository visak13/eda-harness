"""W15 (DESIGN-v6) — protected-spec hardening + shared actor attribution.

Covers the a2 mechanism (UNIT evidence; the live in-MCP refusal is
restart-gated per the action note):

  * Spec.protected is an ADDITIVE field — a legacy spec (no `protected`
    key) round-trips byte-shape-identical on a no-op load (o6), and the key
    only appears once a spec is genuinely protected.
  * store/attribution.actor() resolves {role, handle} IN CODE from the
    environment (principle-6) — never an argument.
  * A protected-spec write via add_spec_entry WITHOUT unlock=true is refused.
  * The (CAP+1)-th entry on a protected spec is refused with the
    "consolidate first" message (growth budget, d24 write-time cap).
  * Every spec_saved worklog record carries by:{role,handle}.
  * ensure_universal seeds a bounded, protected, distilled contract (seed
    count <= cap) and, on an EXISTING install, flags the live spec protected
    WITHOUT reseeding/truncating its entries. (W15/DESIGN-v6: the parallel
    ensure_orchestrator cases were retired/redirected here — the orchestrator
    spec-ness reverted to a directly-edited guide; the protected-spec
    subsystem now serves only the legit spec-universal.)
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from edp_contracts import ToolError, ToolOk

from edp_claude.schemas import SpecEntry, Specialization
from edp_claude.store.attribution import actor
from edp_claude.store.spec_store import PROTECTED_ENTRY_CAP, SpecStore


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _now():
    return datetime.now(UTC)


# ── (b) attribution.actor() — resolved in code, never supplied ──────────────

def test_actor_resolves_from_env_never_argument(monkeypatch):
    monkeypatch.setenv("EDP_ROLE", "worker")
    monkeypatch.setenv("EDP_HANDLE", "plan-x:a7")
    assert actor() == {"role": "worker", "handle": "plan-x:a7"}


def test_actor_defaults_unknown_when_env_absent(monkeypatch):
    # e.g. the neuron shell has no EDP_HANDLE — still a concrete `by`.
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    assert actor() == {"role": "unknown", "handle": "unknown"}


# ── (a) additive protected field — o6 byte-identity on a no-op load ─────────

def _legacy_spec_json(spec_id: str) -> dict:
    now = _now().isoformat()
    return {
        "spec_id": spec_id,
        "neuron_id": "n-legacy",
        "name": "Legacy Spec",
        "subject": "legacy",
        "entries": [
            {"kind": "step", "text": "do the thing", "note": "",
             "adherence": "expected", "link_role": None},
        ],
        "extends": ["spec-universal"],
        "created_at": now,
        "updated_at": now,
        "version": 3,
    }


def test_legacy_spec_roundtrips_byte_identical(tmp_path):
    """o6: a spec serialized before `protected` existed re-serializes with the
    SAME shape — the additive field is emission-gated (omitted at default).

    The canonical on-disk form is the model's own dump (so datetime encoding
    matches); a legacy doc simply lacks the `protected` key. Assert that dump
    omits `protected` and that a no-op load→dump is byte-shape-identical."""
    spec = Specialization.model_validate(_legacy_spec_json("spec-legacy"))
    on_disk = spec.model_dump(mode="json")   # canonical serialized form
    assert "protected" not in on_disk, (
        "an unprotected spec must NOT emit the protected key — that would "
        "alter every legacy spec's serialized shape (o6)."
    )
    # a no-op load of that on-disk doc re-serializes identically
    reloaded = Specialization.model_validate(on_disk).model_dump(mode="json")
    assert reloaded == on_disk


def test_protected_spec_emits_the_flag(tmp_path):
    spec = Specialization.model_validate(_legacy_spec_json("spec-p"))
    spec.protected = True
    dumped = spec.model_dump(mode="json")
    assert dumped.get("protected") is True


# ── (e) actor attribution stamped on the spec_saved worklog record ──────────

def test_spec_saved_worklog_carries_by_role_handle(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_ROLE", "worker")
    monkeypatch.setenv("EDP_HANDLE", "plan-z:a2")
    store = SpecStore(tmp_path)
    now = _now()
    store.save(Specialization(
        spec_id="spec-attr", neuron_id="n1", name="Attr", subject="s",
        entries=[], created_at=now, updated_at=now,
    ))
    wl = Path(tmp_path) / "spec-attr" / "worklog.jsonl"
    recs = [json.loads(x) for x in
            wl.read_text(encoding="utf-8").splitlines() if x.strip()]
    saved = [r for r in recs if r.get("kind") == "spec_saved"]
    assert saved, "no spec_saved worklog record written"
    assert saved[-1]["by"] == {"role": "worker", "handle": "plan-z:a2"}


# ── (c) protected write requires unlock=true (via the add_spec_entry tool) ──

async def _make_protected_spec(env, spec_id="spec-guard", n_entries=0):
    now = _now()
    entries = [SpecEntry(kind="step", text=f"e{i}") for i in range(n_entries)]
    env.ctx.specs.save(Specialization(
        spec_id=spec_id, neuron_id="ng", name="Guarded", subject="s",
        entries=entries, protected=True, created_at=now, updated_at=now,
    ))
    return spec_id


async def test_protected_write_without_unlock_is_refused(env):
    sid = await _make_protected_spec(env)
    res = await env.call("add_spec_entry", spec_id=sid, kind="step",
                         text="sneak an entry in")
    assert isinstance(res, ToolError), res
    assert res.code == "tool_precondition"
    assert "unlock" in res.message.lower()
    # the refused write must NOT have landed
    assert env.ctx.specs.load(sid).entries == []


async def test_protected_write_with_unlock_succeeds(env):
    sid = await _make_protected_spec(env)
    out = _ok(await env.call("add_spec_entry", spec_id=sid, kind="step",
                             text="an authorized amendment", unlock=True))
    assert out["version"] >= 1
    kinds = [e.text for e in env.ctx.specs.load(sid).entries]
    assert "an authorized amendment" in kinds


async def test_unprotected_spec_write_is_unguarded(env):
    """An ordinary spec keeps the frictionless, uncapped write path."""
    d = _ok(await env.call("create_specialization", name="Java",
                           subject="java", description="java"))
    sid = d["spec_id"]
    out = _ok(await env.call("add_spec_entry", spec_id=sid, kind="step",
                             text="no unlock needed here"))
    assert out["version"] >= 1


# ── (d) growth-budget cap — the (CAP+1)-th add is refused, write-time ───────

async def test_cap_plus_one_entry_refused_with_consolidate_message(env):
    # seed a protected spec already AT the cap
    sid = await _make_protected_spec(env, n_entries=PROTECTED_ENTRY_CAP)
    res = await env.call("add_spec_entry", spec_id=sid, kind="step",
                         text="the 26th entry", unlock=True)
    assert isinstance(res, ToolError), res
    assert res.code == "tool_precondition"
    assert "consolidate first" in res.message.lower()
    # the over-budget add must NOT have landed
    assert len(env.ctx.specs.load(sid).entries) == PROTECTED_ENTRY_CAP


async def test_cap_does_not_truncate_an_already_over_cap_spec_on_load(env):
    """The cap is ADD-time only: loading (or a metadata-only save of) an
    already-over-cap protected spec never drops entries."""
    over = PROTECTED_ENTRY_CAP + 40
    sid = await _make_protected_spec(env, spec_id="spec-over", n_entries=over)
    # a plain load preserves everything
    assert len(env.ctx.specs.load(sid).entries) == over
    # a metadata-only save (the _ensure_protected path) preserves everything
    spec = env.ctx.specs.load(sid)
    env.ctx.specs.save(spec)
    assert len(env.ctx.specs.load(sid).entries) == over


# ── (f) ensure_universal — bounded protected contract ───────────────────────
# W15 (DESIGN-v6): test_ensure_orchestrator_seeds_bounded_protected_contract
# RETIRED — the orchestrator spec-ness is retired (reverted to a guide), and
# the "ensure_* seeds a bounded protected contract" behavior is already
# covered by test_ensure_universal_seeds_protected below.


async def test_ensure_universal_seeds_protected(env):
    out = _ok(await env.call("ensure_universal"))
    assert out["created"] is True
    spec = env.ctx.specs.load(out["spec_id"])
    assert spec.protected is True
    assert len(spec.entries) <= PROTECTED_ENTRY_CAP


async def test_ensure_universal_flags_existing_without_reseeding(env):
    """On an EXISTING install: LOAD the live entries as-is and only add the
    protected flag — never replace them with the code seed (steer d12cd59d).
    W15 (DESIGN-v6): redirected from the retired ensure_orchestrator case to
    the still-protected spec-universal — the same preserve-and-flag path."""
    # simulate a live, pre-W15 universal spec: unprotected, custom entries
    now = _now()
    sid = "spec-universal"
    live_entries = [SpecEntry(kind="preference", text=f"live rule {i}")
                    for i in range(30)]
    env.ctx.specs.save(Specialization(
        spec_id=sid, neuron_id="universal", name="Universal Standards",
        subject="universal coding standards", entries=live_entries,
        extends=[], created_at=now, updated_at=now,
    ))

    out = _ok(await env.call("ensure_universal"))
    assert out["created"] is False
    spec = env.ctx.specs.load(sid)
    # entries preserved verbatim (no reseed, no truncation despite >cap)
    assert [e.text for e in spec.entries] == [e.text for e in live_entries]
    # flag added additively
    assert spec.protected is True


async def test_ensure_protected_is_idempotent(env):
    """Second ensure call is a no-op — it does not bump the version again."""
    _ok(await env.call("ensure_universal"))
    sid = "spec-universal"
    v1 = env.ctx.specs.load(sid).version
    _ok(await env.call("ensure_universal"))
    v2 = env.ctx.specs.load(sid).version
    assert v2 == v1, "already-protected spec must not be re-saved (idempotent)"
