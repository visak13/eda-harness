"""W7 part 4 (DESIGN-v6 §W7.4) — Rx-noise suppression.

Two code deliverables, both pinned here:

  (a) the per-spec `min_interval_ms` RATE-LIMIT knob on observe() (default 0 =
      today's every-emission behavior), so a chatty stream can't machine-gun
      the watching Monitor — applied PER-SOURCE, to the polled snapshot planes
      only, BEFORE the merge;
  (b) per-role observe() wake kind-sets (ROLE_WAKE_KINDS) that PRESERVE each
      role's primary wakes — the regression guard against a prior draft that
      dropped plan_closed/done/question.

HISTORY, because it is the reason (a) is shaped the way it is. The knob first
shipped as `ops.debounce` applied to the COMPILED (merged) pipeline. Debounce
is not rate-limiting: it waits for the stream to go SILENT for the whole window
and keeps only the LAST item of the burst. Merge a 2-second poller (rx.pool)
into the spec and the quiet never comes — so a once-only critical event
(a worklog `action_status_changed`/`done`) was not delayed, it was DISCARDED,
and the surviving emission was the pool snapshot that beat it. A planner went
deaf to its worker's `done` for four minutes with a live Monitor and a correct
filter (s29). d31/s15 had already fixed the EMISSION half of this — the legible
done IS written to the worklog, and that fix is intact; what was never guarded
was DELIVERY.

`test_a_critical_event_survives_a_continuous_chatty_co_source` is the test whose
ABSENCE is why that shipped. It goes RED against the merged-stream debounce AND
against a naive throttle-on-merge — a single knob on a merged stream is the
wrong SHAPE, whatever the operator.
"""

import threading
import time

import reactivex as rx
from edp_contracts import ToolError, ToolOk
from reactivex import operators as ops
from reactivex.subject import Subject

from edp_claude.reactive import ROLE_PRIMARY_WAKES, ROLE_WAKE_KINDS, RxRuntime
from edp_claude.reactive.runtime import (
    CRITICAL_SOURCES,
    RATE_LIMITABLE_SOURCES,
    compile_spec,
)


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


# ── (a) the per-source rate-limit knob ──────────────────────────────────────
# A planner's real spec: one CRITICAL event plane merged with one CHATTY poller.
SPEC = "rx.merge(rx.worklog(plan_id=pid), rx.pool(scope=pid))"
KNOB_MS = 200          # the knob, ON, as a planner would set it
PING_S = 0.02          # the pool poller: continuous, far faster than the window
RUN_S = 1.0            # it pings throughout — the quiet never comes
DONE_AT_S = 0.5        # the one critical event, mid-run
DONE = {"kind": "action_status_changed", "action_id": "a1", "status": "done"}


def _provider(critical: Subject, chatty: Subject):
    """Deterministic source_provider: `worklog` is the critical plane, `pool`
    the chatty one. Same names the real RealSources provides."""
    def provide(name, **_kw):
        if name == "worklog":
            return critical
        if name == "pool":
            return chatty
        raise AssertionError(f"unexpected source {name!r}")
    return provide


def _fixed(critical, chatty):
    """The FIX: the knob goes to the RUNTIME, so it lands on the chatty source
    as the spec builds it — before the spec's own rx.merge."""
    runtime = RxRuntime(_provider(critical, chatty), rate_limit_ms=KNOB_MS)
    return compile_spec(SPEC, runtime, {"pid": "p1"})


def _merged(operator):
    """The DEFECTIVE shape, in both its flavours: compile the spec with the knob
    OFF at the sources, then put ONE operator on the merged pipeline — which is
    exactly what the driver used to do after compile_spec."""
    def build(critical, chatty):
        runtime = RxRuntime(_provider(critical, chatty))
        return compile_spec(SPEC, runtime, {"pid": "p1"}).pipe(operator)
    return build


def _drive(build) -> list:
    """Run one scenario in real time: a poller pinging continuously throughout,
    and ONE critical `done` in the middle. Returns everything delivered."""
    critical, chatty = Subject(), Subject()
    out: list = []
    sub = build(critical, chatty).subscribe(on_next=out.append)
    try:
        t0 = time.monotonic()
        ticks = [0]

        def ping():
            while time.monotonic() - t0 < RUN_S:
                chatty.on_next([{"handle": "w1", "liveness": "alive",
                                 "tick": ticks[0]}])
                ticks[0] += 1
                time.sleep(PING_S)

        pinger = threading.Thread(target=ping, daemon=True)
        pinger.start()
        time.sleep(DONE_AT_S)
        critical.on_next(DONE)              # the event the shell must not miss
        pinger.join()
        # let any wait-for-quiet operator flush whatever it was holding: this is
        # what makes the failure legible — it flushes the POOL SNAPSHOT that won
        # the collapse, not the done.
        time.sleep(KNOB_MS / 1000.0 * 2)
        assert ticks[0] > 10, "the co-source must be continuously chatty"
        return out
    finally:
        sub.dispose()


def _dones(out: list) -> list:
    return [e for e in out if isinstance(e, dict) and e.get("kind")
            == "action_status_changed"]


def test_a_critical_event_survives_a_continuous_chatty_co_source():
    """THE forcing test. A low-frequency CRITICAL event (a worklog action-done)
    MUST be delivered even though a high-frequency poller is merged into the
    same spec and the rate-limit knob is ON."""
    out = _drive(_fixed)
    assert _dones(out) == [DONE], (
        "the done was starved by the chatty co-source", out)


def test_the_knob_still_quiets_the_chatty_plane():
    """The knob's PURPOSE is preserved: the poller's ~50 pings collapse to a
    handful of wakes. Fixing starvation must not cost the ability to rate-limit
    (that would trade one defect for another)."""
    out = _drive(_fixed)
    pings = [e for e in out if not isinstance(e, dict)]
    # ~50 raw pings in RUN_S; the knob caps them at one per KNOB_MS window.
    assert len(pings) <= int(RUN_S * 1000 / KNOB_MS) + 2, len(pings)
    assert pings, "the chatty plane is quieted, not silenced"


def test_RED_merged_stream_debounce_discards_the_critical_event():
    """The SHIPPED DEFECT, pinned so it can never come back: one debounce on the
    MERGED stream. The stream never goes quiet (the poller sees to that), so the
    done is discarded and the survivor is a pool snapshot — d31's empty-batch
    symptom, one layer downstream."""
    out = _drive(_merged(ops.debounce(KNOB_MS / 1000.0)))
    assert _dones(out) == [], "this shape is supposed to LOSE the done"
    assert out and not isinstance(out[-1], dict), (
        "the survivor of the collapse is the chatty pool snapshot", out)


def test_RED_naive_throttle_on_the_merged_stream_also_discards_it():
    """And the obvious 'fix' is not one. sample/throttle_first on the MERGED
    stream still picks its survivor from a stream a poller dominates, so the
    done still loses. A SINGLE KNOB ON A MERGED STREAM IS THE WRONG SHAPE,
    WHATEVER THE OPERATOR — which is why the fix is per-source."""
    out = _drive(_merged(ops.sample(KNOB_MS / 1000.0)))
    assert _dones(out) == [], "this shape is supposed to LOSE the done too"


def test_critical_sources_are_never_rate_limited_even_with_the_knob_on():
    # Identity, not "usually fine": with the knob set as high as you like, a
    # critical source comes back UNTOUCHED — no operator, so nothing to starve.
    src = rx.of("a")
    rt = RxRuntime(lambda *a, **k: src, rate_limit_ms=60_000)
    assert rt.worklog(plan_id="p") is src
    assert rt.recipe(recipe_id="r") is src
    assert rt.broker(recipient="me") is src
    assert rt.pool(scope="p") is not src        # only the chatty plane is capped


# ── s29/a4 (REVIEW FINDING) — the guard above was NARROWER THAN ITS OWN NAME ──
# It hand-listed THREE planes (worklog/recipe/broker) while CRITICAL_SOURCES
# declares FIVE. `recipe_events` — the neuron's flowback channel, carrying the
# once-only `learning`/`discovery`/`blocker` edges — was outside it, and an
# IDENTITY check cannot reach it anyway: recipe_events legitimately pipes
# `ops.filter`, so it is never `is src` even when correct.
#
# MEASURED, not reasoned: wrapping `recipe_events` in `self._rate_limited(...)`
# left the ENTIRE claude suite GREEN. A critical plane could silently acquire the
# very starvation this milestone exists to prevent, on the one plane a neuron
# depends on to hear a `blocker`.
#
# THE CONSTANTS WERE DECORATIVE, which is the deeper half. RATE_LIMITABLE_SOURCES
# / CRITICAL_SOURCES drove NOTHING: the real gating is which source METHOD calls
# `_rate_limited`. Adding "worklog" to RATE_LIMITABLE_SOURCES changed no
# behaviour and broke no test. So this guard asks the question by INTERCEPTING
# THE OPERATOR rather than comparing identities, and it DERIVES its plane list
# from the constant — which is what finally makes the table load-bearing.
def _limited_planes(monkeypatch, rt) -> callable:
    """Return a probe that reports whether building a source applied the
    rate-limit operator, by intercepting `_rate_limited` itself."""
    applied: list[bool] = []
    orig = RxRuntime._rate_limited

    def spy(self, source):
        applied.append(True)
        return orig(self, source)

    monkeypatch.setattr(RxRuntime, "_rate_limited", spy)

    def probe(build) -> bool:
        applied.clear()
        build()
        return bool(applied)

    return probe


def test_no_critical_plane_applies_the_rate_limit_operator(monkeypatch):
    """Every plane in CRITICAL_SOURCES, derived — not three of the five."""
    rt = RxRuntime(lambda *a, **k: rx.of("a"), rate_limit_ms=60_000)
    probe = _limited_planes(monkeypatch, rt)

    builders = {
        "broker":        lambda: rt.broker(recipient="me"),
        "topic":         lambda: rt.topic(name="t"),
        "worklog":       lambda: rt.worklog(plan_id="p"),
        "recipe":        lambda: rt.recipe(recipe_id="r"),
        "recipe_events": lambda: rt.recipe_events(recipe_id="r"),
    }
    # the list is DERIVED: a new critical plane with no builder fails here rather
    # than slipping through unexercised.
    assert set(builders) == CRITICAL_SOURCES, sorted(
        CRITICAL_SOURCES.symmetric_difference(builders))

    for name, build in builders.items():
        assert not probe(build), (
            f"CRITICAL source {name!r} applied the rate-limit operator. A "
            "once-only edge (an action `done`, a `blocker`) can now be "
            "discarded by a knob setting — the exact starvation W7.4 fixed.")


def test_every_rate_limitable_plane_really_does_apply_it():
    """The POSITIVE control, equally derived.

    IDENTITY, deliberately — NOT the `_rate_limited` spy above. The spy counts
    the CALL, so it would stay green against a `_rate_limited` whose body had
    decayed to `return src`: the method is still called, the operator is simply
    gone. (Measured: it did. This control was written with the spy first and
    passed against exactly that mutation — a positive control that cannot fail is
    the same vacuity this module keeps catching.) Comparing the RETURNED
    observable to the raw source cannot be fooled that way: a no-op knob hands
    back `src` itself."""
    src = rx.of("a")
    rt = RxRuntime(lambda *a, **k: src, rate_limit_ms=60_000)

    builders = {
        "pool":     lambda: rt.pool(scope="p"),
        "plan":     lambda: rt.plan(plan_id="p"),
        "external": lambda: rt.external(url="u"),
        # orphaned (2026-07-25) is a polled JOIN of plan/recipe state against
        # pool liveness, and the orphan condition is STICKY — it persists until
        # something heals it — so sampling can only DELAY a wake, never discard
        # one. That stickiness is exactly what makes it safe to rate-limit,
        # unlike the once-only edges next door.
        "orphaned": lambda: rt.orphaned(plan_id="p"),
    }
    assert set(builders) == RATE_LIMITABLE_SOURCES, sorted(
        RATE_LIMITABLE_SOURCES.symmetric_difference(builders))

    for name, build in builders.items():
        assert build() is not src, (
            f"{name!r} is declared RATE_LIMITABLE but the knob never reached "
            "it — either the method dropped its _rate_limited() call or the "
            "operator itself has decayed to a no-op. The chatty plane is "
            "unbounded.")


def test_knob_off_is_identity_passthrough_on_every_source():
    # 0 (the default) returns the SAME observable object on every plane — the
    # strongest proof the default cannot change today's pipeline.
    src = rx.of("a")
    rt = RxRuntime(lambda *a, **k: src)
    assert rt.pool(scope="p") is src
    assert rt.plan(plan_id="p") is src
    assert rt.external(url="u") is src
    assert RxRuntime(lambda *a, **k: src, rate_limit_ms=-5).pool() is src


def test_main_hands_the_knob_to_the_runtime_and_never_wraps_the_pipeline(
        monkeypatch, tmp_path):
    """The seam that broke, pinned. The knob must reach the RUNTIME (so it lands
    per-source, before the spec's merge) and the COMPILED pipeline must reach
    `run` UNWRAPPED. A future edit that re-applies one operator after
    compile_spec — the original defect — fails here."""
    from edp_claude.reactive import driver

    seen: dict = {}
    compiled = rx.of("compiled-pipeline")

    class _SpyRuntime:
        def __init__(self, provider, rate_limit_ms=0.0):
            seen["rate_limit_ms"] = rate_limit_ms

    monkeypatch.setattr(driver, "RxRuntime", _SpyRuntime)
    monkeypatch.setattr(driver, "compile_spec", lambda *a, **k: compiled)
    monkeypatch.setattr(driver, "run",
                        lambda obs, **k: seen.update(ran=obs))

    spec_file = tmp_path / "s.spec"
    spec_file.write_text("rx.broker(me)", encoding="utf-8")
    driver.main(["--spec-file", str(spec_file), "--min-interval-ms", "250"])

    assert seen["rate_limit_ms"] == 250        # per-source, before the merge
    assert seen["ran"] is compiled             # NOT wrapped after compile


def test_the_two_source_classes_are_disjoint_and_complete():
    # The split IS the fix, so it is pinned: a plane is either a polled snapshot
    # (rate-limitable — the newest supersedes the last) or a once-only event
    # (critical — never limited). Nothing may be both.
    assert not (RATE_LIMITABLE_SOURCES & CRITICAL_SOURCES)
    assert {"pool", "plan", "external", "orphaned"} == RATE_LIMITABLE_SOURCES
    assert {"worklog", "broker", "recipe_events"} <= CRITICAL_SOURCES


# ── (a) observe() tool wiring ────────────────────────────────────────────────

async def test_observe_threads_min_interval_ms_when_set(env):
    out = _ok(await env.call(
        "observe", spec="rx.broker(me)", bindings={"me": "x"},
        min_interval_ms=250))
    assert "--min-interval-ms 250" in out["monitor_cmd"]


async def test_observe_default_omits_min_interval_flag(env):
    # default 0 → command byte-identical to today's (no flag), so existing
    # behavior + the idempotent-reuse cmd equality are preserved.
    out = _ok(await env.call(
        "observe", spec="rx.broker(me)", bindings={"me": "x"}))
    assert "--min-interval-ms" not in out["monitor_cmd"]


async def test_observe_min_interval_still_returns_consumable_on_bad_spec(env):
    res = await env.call("observe", spec="1 + 1", min_interval_ms=100)
    assert isinstance(res, ToolError)          # validation still fires first


# ── (b) per-role wake kind-sets preserve primary wakes ───────────────────────

def test_every_role_broker_set_contains_its_primary_wakes():
    # The exact regression a prior W7 draft introduced: dropping the primary
    # wake kinds. Each role's primary wakes MUST remain a subset of its set.
    for role, primary in ROLE_PRIMARY_WAKES.items():
        broker_kinds = set(ROLE_WAKE_KINDS[role]["broker"])
        assert set(primary) <= broker_kinds, role


def test_primary_wakes_are_the_load_bearing_kinds():
    # plan_closed / done / question are the load-bearing wakes named in the
    # design — assert each lands in the role that owns it.
    assert "plan_closed" in ROLE_WAKE_KINDS["neuron"]["broker"]
    assert "question" in ROLE_WAKE_KINDS["neuron"]["broker"]
    assert "done" in ROLE_WAKE_KINDS["planner"]["broker"]
    assert "question" in ROLE_WAKE_KINDS["planner"]["broker"]
    assert set(ROLE_WAKE_KINDS["worker"]["broker"]) == {"answer", "steer"}


def test_neuron_keeps_flowback_and_crash_planes():
    # neuron ALSO subscribes the FLOWBACK channel + a dead-only pool wake.
    assert set(ROLE_WAKE_KINDS["neuron"]["recipe_events"]) == {
        "learning", "discovery", "blocker",
        "spec_learning_proposed", "review_finding"}
    assert ROLE_WAKE_KINDS["neuron"]["pool_states"] == ["dead"]


def test_w5_consult_and_steer_ack_kinds_are_absent():
    # W7 is the baseline; W5 (NOT this action) adds consult/steer-ack. They
    # must be absent here so W7 doesn't smuggle W5's scope in.
    for role in ("neuron", "planner", "worker"):
        broker = set(ROLE_WAKE_KINDS[role]["broker"])
        assert "consult" not in broker, role
        assert "steer-ack" not in broker, role
