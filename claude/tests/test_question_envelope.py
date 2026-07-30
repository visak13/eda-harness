"""DESIGN-v7 2.1 — the QUESTION ENVELOPE: auto-composed context on every
upward question.

THE ROOT CAUSE (DESIGN-v6 finding): `compose_consult_question` auto-composed
rich context — but only for the stuck-action consult path. `ask_above` shipped
bare `body={"question": …}`, and the neuron relayed context-free options to
the user. These tests lock the fix at both layers:

- the PURE layer (`fsm/envelope.compose_question_envelope`): goal line,
  what-I-was-doing, acceptance diff, what-blocks-on-this, pass-through
  options — composed from threaded-in objects, no IO;
- the TOOL layer (`ask_above`): enrichment happens IN CODE on every send
  (no refusal path, no guide compliance), the asker's explicit body keys WIN
  on collision, and the envelope survives BOTH routes (two-hop via the parent
  and audience='neuron' direct).

Also pins that `compose_consult_question` — now a thin caller of the envelope
— still renders its pinned stuck-consult prose (the byte-level pin lives in
test_w10b_model_tiering.test_t6h; here we pin the delegation is real).
"""

from edp_contracts import ToolOk


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


async def _scaffold(env):
    """Recipe → step → plan → a1 (with acceptance) ← a2 depends_on a1."""
    rid = _ok(await env.call("start_recipe", goal="ship the parser",
                             domain="api"))["recipe_id"]
    sid = _ok(await env.call("add_step", recipe_id=rid,
                             description="build the tokenizer step",
                             execution="spawn_planner"))["step_id"]
    pid = _ok(await env.call("create_plan", recipe_id=rid, step_id=sid,
                             shape="poc-iterate-build",
                             goal="build the tokenizer"))["plan_id"]
    _ok(await env.call("add_action", plan_id=pid, action_id="a1",
                       description="write the lexer table",
                       acceptance_expected="lexer table covers all tokens"))
    _ok(await env.call("add_action", plan_id=pid, action_id="a2",
                       description="wire lexer into the parser",
                       depends_on=["a1"]))
    return rid, sid, pid


def _question_at(msgs):
    qs = [x for x in msgs if x.kind == "question"]
    assert len(qs) == 1, [x.kind for x in msgs]
    return qs[0]


# ── worker-level: plan goal + action description + acceptance diff ──────────

async def test_worker_ask_above_carries_composed_envelope(env, monkeypatch):
    _, _, pid = await _scaffold(env)
    monkeypatch.setenv("EDP_HANDLE", f"{pid}:a1")
    monkeypatch.setenv("EDP_ROLE", "worker")
    _ok(await env.call("ask_above", question="is the token set frozen?"))

    q = _question_at(await env.ctx.broker.poll(pid, since_ts=None))
    envlp = q.body.get("envelope")
    assert envlp, "ask_above must attach body['envelope'] in code"
    # goal line names the PLAN goal
    assert envlp["goal"] == "build the tokenizer"
    # what-I-was-doing is the action's own description
    assert envlp["doing"] == "write the lexer table"
    # acceptance diff carries the EXPECTED/ACTUAL shape (VERIFY when recorded)
    assert "EXPECTED: lexer table covers all tokens" in envlp["acceptance_diff"]
    assert "ACTUAL:" in envlp["acceptance_diff"]
    # what-blocks-on-this: a2 depends on a1, so the answer unblocks it
    assert any(b.startswith("a2:") for b in envlp["blocks_on_this"])
    # provenance ids let the relay read deeper without re-deriving lineage
    assert envlp["asked_from"]["plan_id"] == pid
    assert envlp["asked_from"]["action_id"] == "a1"
    # the question text itself is untouched
    assert q.body["question"] == "is the token set frozen?"


async def test_asker_explicit_body_keys_win_on_collision(env, monkeypatch):
    _, _, pid = await _scaffold(env)
    monkeypatch.setenv("EDP_HANDLE", f"{pid}:a1")
    monkeypatch.setenv("EDP_ROLE", "worker")
    _ok(await env.call(
        "ask_above", question="q",
        body={"envelope": {"goal": "MY OWN framing"},
              "options": ["freeze", "extend"]}))
    q = _question_at(await env.ctx.broker.poll(pid, since_ts=None))
    # the asker's explicit envelope REPLACES the composed one entirely —
    # enrichment never clobbers deliberate content.
    assert q.body["envelope"] == {"goal": "MY OWN framing"}
    assert q.body["options"] == ["freeze", "extend"]


async def test_envelope_survives_audience_neuron_route(env, monkeypatch):
    rid, _, pid = await _scaffold(env)
    monkeypatch.setenv("EDP_HANDLE", f"{pid}:a1")
    monkeypatch.setenv("EDP_ROLE", "worker")
    _ok(await env.call("ask_above", audience="neuron",
                       question="does the goal allow a bigger token set?"))
    # the DIRECT route delivers the same enriched body to the neuron's inbox
    q = _question_at(await env.ctx.broker.poll(rid, since_ts=None))
    envlp = q.body.get("envelope")
    assert envlp and envlp["goal"] == "build the tokenizer"
    assert envlp["doing"] == "write the lexer table"
    assert "EXPECTED:" in envlp["acceptance_diff"]


# ── step-level: a planner asking with NO action in play ─────────────────────

async def test_planner_step_level_envelope_without_action(env, monkeypatch):
    rid, sid, pid = await _scaffold(env)
    # a second step depending on the first — the step-level blocks slot
    sid2 = _ok(await env.call("add_step", recipe_id=rid,
                              description="integrate the parser end-to-end",
                              execution="spawn_planner"))["step_id"]
    _ok(await env.call("update_object", type="step",
                       ids={"recipe_id": rid, "step_id": sid2},
                       patch={"depends_on": [sid]}))
    monkeypatch.setenv("EDP_HANDLE", f"{rid}:{sid}")
    monkeypatch.setenv("EDP_ROLE", "planner")
    _ok(await env.call("ask_above", question="split this step?"))

    q = _question_at(await env.ctx.broker.poll(rid, since_ts=None))
    envlp = q.body.get("envelope")
    assert envlp, "a planner-level question is enriched too"
    # goal: the plan exists for this step, so its goal leads
    assert envlp["goal"] == "build the tokenizer"
    # doing: the STEP description (no action in play)
    assert envlp["doing"] == "build the tokenizer step"
    # no action → no acceptance diff slot (never empty filler)
    assert "acceptance_diff" not in envlp
    # the dependent step is what blocks on the answer
    assert any(b.startswith(f"{sid2}:") for b in envlp["blocks_on_this"])
    assert envlp["asked_from"]["step_id"] == sid
    assert envlp["asked_from"]["recipe_id"] == rid


# ── the pure layer directly ──────────────────────────────────────────────────

def test_pure_envelope_composes_from_whatever_is_threaded_in():
    from edp_claude.fsm.envelope import compose_question_envelope

    # nothing in play → empty dict (the tool layer then omits the key)
    assert compose_question_envelope() == {}

    # options pass through VERBATIM
    env = compose_question_envelope(options=[{"label": "A", "detail": "x"}])
    assert env["options"] == [{"label": "A", "detail": "x"}]
    assert "goal" not in env and "acceptance_diff" not in env


def test_compose_consult_question_is_a_thin_caller_of_the_envelope():
    """The consult path and the envelope path must render ONE diff shape —
    the refactor is real delegation, not a parallel copy."""
    import inspect

    from edp_claude.fsm import plan_fsm
    from edp_claude.fsm.envelope import acceptance_diff

    src = inspect.getsource(plan_fsm.compose_consult_question)
    assert "compose_question_envelope" in src
    # the diff renderer lives in envelope.py only; plan_fsm re-imports it
    assert not hasattr(plan_fsm, "_acceptance_diff"), (
        "plan_fsm should no longer carry its own acceptance-diff copy")

    class _A:
        action_id = "a1"

        class acceptance:
            expected = ""
            actual = None
            verify = None

    d = acceptance_diff(_A())
    assert "(none recorded)" in d and "(nothing recorded)" in d


def test_envelope_module_is_pure():
    """Principle 6: the envelope is composed, never fetched — no IO, no LLM."""
    import inspect

    import edp_claude.fsm.envelope as envelope

    src = inspect.getsource(envelope)
    for forbidden in ("ctx.", "await ", "requests.", "open(", "Path("):
        assert forbidden not in src, (
            f"envelope.py performs IO ({forbidden!r}); it must stay pure")
