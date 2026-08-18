"""Reactive layer — operator composition (injected sources, no I/O),
spec compiler, NDJSON sink, and the real filesystem worklog tail.
"""

import io
import json
import time
from datetime import timezone

import reactivex as rx

from edp_claude.reactive import RxRuntime, SpecError, compile_spec
from edp_claude.reactive.driver import (
    RealConfig,
    RealSources,
    _follow_only,
    _parse_ts,
    run,
)


def _provider(mapping):
    """source_provider that returns a fixed Observable per source name."""
    def _p(name, **kw):
        if name not in mapping:
            raise ValueError(f"no test source {name!r}")
        return mapping[name]
    return _p


def _collect(observable):
    out = []
    observable.subscribe(on_next=out.append)
    return out


# ── compile_spec ────────────────────────────────────────────────────────────
def test_compile_returns_observable():
    runtime = RxRuntime(_provider({"broker": rx.of({"kind": "done"})}))
    obs = compile_spec("rx.broker(me)", runtime, {"me": "neuron:r1"})
    assert _collect(obs) == [{"kind": "done"}]


def test_compile_rejects_non_observable():
    runtime = RxRuntime(_provider({}))
    try:
        compile_spec("1 + 1", runtime)
    except SpecError as e:
        assert "Observable" in str(e)
    else:
        raise AssertionError("expected SpecError")


def test_compile_surfaces_eval_error():
    runtime = RxRuntime(_provider({}))
    try:
        compile_spec("rx.nonexistent_source()", runtime)
    except SpecError as e:
        assert "failed to evaluate" in str(e)
    else:
        raise AssertionError("expected SpecError")


def test_compile_blocks_dangerous_builtins():
    runtime = RxRuntime(_provider({}))
    try:
        compile_spec("__import__('os')", runtime)
    except SpecError:
        pass  # no __import__ in the restricted builtins
    else:
        raise AssertionError("expected SpecError (import must be blocked)")


# ── broker follow-only default (FA2-F1) ──────────────────────────────────────
def _broker_msgs(historical, new):
    """An injected broker observable: N historical (ts <= the connect cutoff)
    followed by M new (ts > cutoff) broker-shaped dicts, each carrying a `ts`
    — exactly what a fresh subscribe sees (retained inbox, then live)."""
    return rx.of(*historical, *new)


def test_broker_follow_only_yields_only_new():
    # N=3 historical + M=2 new across the connect-time boundary → follow-only
    # yields EXACTLY the M new (0 historical): the ~10x first-subscribe inbox
    # replay storm is gone, while every genuinely new message still wakes.
    cutoff = _parse_ts("2026-06-07T12:00:00+00:00")
    historical = [{"ts": f"2026-06-07T11:0{i}:00+00:00", "kind": "answer",
                   "h": i} for i in range(3)]
    new = [{"ts": f"2026-06-07T12:0{i}:00+00:00", "kind": "answer", "m": i}
           for i in range(1, 3)]
    got = _collect(_follow_only(_broker_msgs(historical, new), cutoff))
    assert len(got) == 2                                   # exactly M
    assert all("h" not in d for d in got)                  # 0 historical
    assert [d["m"] for d in got] == [1, 2]                 # the new, in order


def test_broker_replay_yields_full_history():
    # replay path (cutoff=None) → no boundary → all N+M delivered, mirroring
    # rx.worklog(replay=True). This is the explicit catch-up opt-in.
    historical = [{"ts": f"2026-06-07T11:0{i}:00+00:00", "h": i}
                  for i in range(3)]
    new = [{"ts": f"2026-06-07T12:0{i}:00+00:00", "m": i} for i in range(1, 3)]
    got = _collect(_follow_only(_broker_msgs(historical, new), None))
    assert len(got) == 5                                   # N + M, nothing cut


def test_broker_follow_only_boundary_is_strict_and_keeps_unparseable():
    # strict `>` (matches the broker's `m.ts > since`): a message AT the
    # cutoff is dropped; one microsecond later is kept; an unparseable ts is
    # KEPT (never silently dropped — the broker already applied the boundary).
    cutoff = _parse_ts("2026-06-07T12:00:00+00:00")
    msgs = rx.of(
        {"ts": "2026-06-07T12:00:00+00:00", "edge": "equal"},
        {"ts": "2026-06-07T12:00:00.000001+00:00", "edge": "after"},
        {"no_ts": True, "edge": "unparseable"},
    )
    edges = [d["edge"] for d in _collect(_follow_only(msgs, cutoff))]
    assert "equal" not in edges
    assert edges == ["after", "unparseable"]


def test_parse_ts_assumes_utc_for_naive_and_handles_garbage():
    assert _parse_ts("2026-06-07T12:00:00").tzinfo is timezone.utc
    assert _parse_ts("not-a-ts") is None
    assert _parse_ts(None) is None


def test_runtime_broker_forwards_replay_default_follow_only():
    # rx.broker default → replay=False reaches the provider (follow-only);
    # replay=True opts back into history. Symmetric with rx.worklog(replay=…).
    captured = []

    def provider(name, **kw):
        captured.append(kw.get("replay"))
        return rx.of({"kind": "done"})

    runtime = RxRuntime(provider)
    compile_spec("rx.broker(me)", runtime, {"me": "x"})
    compile_spec("rx.broker(me, replay=True)", runtime, {"me": "x"})
    compile_spec("rx.topic('t')", runtime)
    assert captured == [False, True, False]   # broker default, opt-in, topic


# ── combinators / operators (the exercise patterns) ──────────────────────────
def test_broker_kind_filter():
    msgs = rx.of({"kind": "done"}, {"kind": "steer"}, {"kind": "done"})
    runtime = RxRuntime(_provider({"broker": msgs}))
    obs = compile_spec("rx.broker(me, kinds=['done'])", runtime,
                       {"me": "x"})
    assert _collect(obs) == [{"kind": "done"}, {"kind": "done"}]


def test_merge_unifies_planes():
    runtime = RxRuntime(_provider({
        "broker": rx.of({"src": "msg"}),
        "worklog": rx.of({"src": "progress"}),
        "pool": rx.of({"src": "crash"}),
    }))
    obs = compile_spec(
        "rx.merge(rx.broker(me), rx.worklog(pid), rx.pool())",
        runtime, {"me": "x", "pid": "p1"})
    srcs = {e["src"] for e in _collect(obs)}
    assert srcs == {"msg", "progress", "crash"}


def test_fork_join_wave_gate_needs_completion_shaping():
    # each leg take(1) so fork_join can terminate; emits a tuple of lasts.
    runtime = RxRuntime(_provider({
        "broker": rx.of({"action_id": "a", "kind": "done"}),
    }))
    spec = (
        "rx.fork_join("
        "  rx.broker(me).pipe(rx.take(1)),"
        "  rx.broker(me).pipe(rx.take(1)),"
        ")")
    obs = compile_spec(spec, runtime, {"me": "x"})
    out = _collect(obs)
    assert len(out) == 1 and len(out[0]) == 2  # one tuple, two legs


def test_three_strikes_as_operator():
    events = rx.of(*[{"kind": "verify_pending"}] * 4)
    runtime = RxRuntime(_provider({"worklog": events}))
    spec = (
        "rx.worklog(pid).pipe("
        "  rx.filter(lambda m: m['kind'] == 'verify_pending'),"
        "  rx.scan(lambda acc, _: acc + 1, 0),"
        "  rx.filter(lambda n: n >= 3),"
        ")")
    obs = compile_spec(spec, runtime, {"pid": "p1"})
    assert _collect(obs) == [3, 4]  # fires once 3 strikes reached


def test_distinct_until_changed_dedups():
    rows = rx.of("alive", "alive", "dead", "dead", "alive")
    runtime = RxRuntime(_provider({"pool": rows}))
    obs = compile_spec(
        "rx.pool().pipe(rx.distinct_until_changed())", runtime)
    assert _collect(obs) == ["alive", "dead", "alive"]


def test_switch_map_composes():
    # switchMap = "a steer supersedes in-flight work": map each steer to a
    # new inner stream, cancelling the previous. A hot Subject (steers
    # arriving over time) models the real use; switch_latest needs a
    # non-synchronous source (a bare of() emits before it can flatten).
    from reactivex.subject import Subject

    steers = Subject()
    runtime = RxRuntime(_provider({"broker": steers}))
    obs = compile_spec(
        "rx.broker(me).pipe(rx.switch_map(lambda s: rx.of('wave:' + s)))",
        runtime, {"me": "x"})
    out = []
    obs.subscribe(on_next=out.append)
    steers.on_next("A")
    steers.on_next("B")
    assert out == ["wave:A", "wave:B"]


def test_take_until_disposes_at_boundary():
    runtime = RxRuntime(_provider({
        "worklog": rx.of({"p": 1}, {"p": 2}),
        "recipe": rx.empty(),
    }))
    # recipe(...) is empty → take_until won't cut early here; sanity that
    # the operator composes and passes values through.
    obs = compile_spec(
        "rx.worklog(pid).pipe(rx.take_until(rx.recipe(rid)))",
        runtime, {"pid": "p1", "rid": "r1"})
    assert _collect(obs) == [{"p": 1}, {"p": 2}]


# ── rx.topic sugar (Phase 1-B domain ingestion) ──────────────────────────────
def test_topic_binds_to_broker_recipient_prefix():
    # rx.topic(name) is THIN sugar: it must resolve to the broker source
    # with recipient `topic:<name>` — no new transport. Capture exactly what
    # the provider is asked for.
    captured = {}

    def provider(name, **kw):
        captured["name"] = name
        captured["recipient"] = kw.get("recipient")
        return rx.of({"kind": "observation", "body": {"q": "hi"}})

    runtime = RxRuntime(provider)
    obs = compile_spec("rx.topic('hmi.ask_submitted')", runtime)
    out = _collect(obs)
    assert captured["name"] == "broker"               # routes via broker
    assert captured["recipient"] == "topic:hmi.ask_submitted"  # prefixed
    assert out == [{"kind": "observation", "body": {"q": "hi"}}]


def test_topic_subscriber_receives_published_message():
    # The publish convention is broker_send(to="topic:<name>", ...). Model a
    # publish with a hot Subject bound to that recipient and assert an
    # rx.topic(name) subscriber receives it.
    from reactivex.subject import Subject

    topic = Subject()

    def provider(name, **kw):
        assert name == "broker"
        assert kw.get("recipient") == "topic:ml.hop_completed"
        return topic

    runtime = RxRuntime(provider)
    obs = compile_spec("rx.topic('ml.hop_completed')", runtime)
    got = []
    obs.subscribe(on_next=got.append)
    # a domain emitter publishes onto the topic recipient
    topic.on_next({"kind": "observation", "body": {"hop": 2}})
    assert got == [{"kind": "observation", "body": {"hop": 2}}]


def test_topic_passes_kind_filter_through_to_broker():
    # kinds= must pass straight through to broker's existing kind-filter, so
    # the sugar preserves broker semantics (not a parallel impl).
    msgs = rx.of({"kind": "observation"}, {"kind": "noise"},
                 {"kind": "observation"})
    runtime = RxRuntime(_provider({"broker": msgs}))
    obs = compile_spec(
        "rx.topic('hmi.ask_submitted', kinds=['observation'])", runtime)
    assert _collect(obs) == [{"kind": "observation"}, {"kind": "observation"}]


# ── NDJSON sink ──────────────────────────────────────────────────────────────
def test_run_emits_ndjson():
    buf = io.StringIO()
    run(rx.of({"a": 1}, {"a": 2}), out=buf)
    lines = [json.loads(x) for x in buf.getvalue().splitlines()]
    assert lines[0] == {"event": {"a": 1}}
    assert lines[1] == {"event": {"a": 2}}
    assert lines[-1] == {"completed": True}


def test_run_emits_error_line():
    buf = io.StringIO()
    run(rx.throw(ValueError("boom")), out=buf)
    lines = [json.loads(x) for x in buf.getvalue().splitlines()]
    assert any("error" in d and "boom" in d["error"] for d in lines)


# ── real filesystem worklog tail (no server needed) ──────────────────────────
def test_real_worklog_replay_true_replays_history(tmp_path):
    wl = tmp_path / ".plans" / "p1" / "worklog.jsonl"
    wl.parent.mkdir(parents=True)
    wl.write_text(
        json.dumps({"kind": "lock_acquired"}) + "\n"
        + json.dumps({"kind": "verify_pending"}) + "\n",
        encoding="utf-8")
    sources = RealSources(RealConfig(repo_root=tmp_path, poll_ms=50))
    runtime = RxRuntime(sources)
    # replay=True opts into full history; take(2) completes deterministically.
    obs = compile_spec(
        "rx.worklog(plan_id=pid, replay=True).pipe(rx.take(2))",
        runtime, {"pid": "p1"})
    out = []
    done = []
    obs.subscribe(on_next=out.append, on_completed=lambda: done.append(True))
    deadline = time.monotonic() + 5
    while not done and time.monotonic() < deadline:
        time.sleep(0.05)
    assert [r["kind"] for r in out] == ["lock_acquired", "verify_pending"]


def test_real_worklog_default_follow_only_skips_history(tmp_path):
    # default (replay=False): pre-existing entries are NOT replayed as
    # wakes (the s6 'historical plan_saved replays' noise). Only appends
    # made AFTER subscription wake the stream.
    wl = tmp_path / ".plans" / "p1" / "worklog.jsonl"
    wl.parent.mkdir(parents=True)
    wl.write_text(json.dumps({"kind": "plan_saved"}) + "\n", encoding="utf-8")
    sources = RealSources(RealConfig(repo_root=tmp_path, poll_ms=30))
    runtime = RxRuntime(sources)
    obs = compile_spec("rx.worklog(plan_id=pid)", runtime, {"pid": "p1"})
    got = []
    sub = obs.subscribe(on_next=got.append)
    time.sleep(0.2)                       # several polls of the history
    assert got == []                       # history NOT replayed
    with wl.open("a", encoding="utf-8") as f:   # a genuinely new append
        f.write(json.dumps({"kind": "verify_pending"}) + "\n")
    deadline = time.monotonic() + 2
    while not got and time.monotonic() < deadline:
        time.sleep(0.03)
    sub.dispose()
    assert [r["kind"] for r in got] == ["verify_pending"]   # only the new one


def test_real_plan_emits_only_on_status_change(tmp_path):
    # data-plane reduction: rx.plan() re-reads the whole plan each tick but
    # must wake ONLY when an action status actually transitions — not the
    # same dict every poll (the snapshot flood).
    pf = tmp_path / ".plans" / "p1.json"
    pf.parent.mkdir(parents=True)
    pf.write_text(json.dumps({"actions": [
        {"action_id": "a1", "status": "in_progress"}]}), encoding="utf-8")
    sources = RealSources(RealConfig(repo_root=tmp_path, poll_ms=30))
    runtime = RxRuntime(sources)
    obs = compile_spec("rx.plan(plan_id=pid)", runtime, {"pid": "p1"})
    got = []
    sub = obs.subscribe(on_next=got.append)
    time.sleep(0.2)                       # many polls of the SAME status
    pf.write_text(json.dumps({"actions": [
        {"action_id": "a1", "status": "done"}]}), encoding="utf-8")
    deadline = time.monotonic() + 2
    while len(got) < 2 and time.monotonic() < deadline:
        time.sleep(0.03)
    sub.dispose()
    # deduped: one emit for the initial state, one for the change — NOT
    # dozens of identical "in_progress" snapshots. F3b: each emission is
    # {snapshot, changed} so the wake NAMES the transition.
    assert [d["snapshot"]["a1"] for d in got] == ["in_progress", "done"]
    assert got[0]["changed"] == {}          # baseline — nothing to diff yet
    assert got[1]["changed"] == {
        "a1": {"from": "in_progress", "to": "done"}}
