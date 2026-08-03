"""Guard: spawned-role activators must read the env brief and be
autonomous (no interactive menu) — regression for the 2026-05-18 HITL
where /worker dropped into a 'what should I do?' prompt."""

from pathlib import Path

_CMD = Path(__file__).resolve().parents[1] / ".claude" / "commands"
_GUIDES = Path(__file__).resolve().parents[1] / "docs" / "guides"


def _body(name: str) -> str:
    return (_CMD / f"{name}.md").read_text(encoding="utf-8").lower()


def _guide(name: str) -> str:
    return (_GUIDES / f"{name}.md").read_text(encoding="utf-8").lower()


def test_worker_reads_env_brief_and_is_autonomous():
    b = _body("worker")
    assert "edp_handle" in b
    assert "edp_role" in b
    assert "autonomous" in b
    # must explicitly forbid prompting the user / menus
    assert "never prompt the user" in b or "do not ask the user" in b
    assert "plan_id" in b and "action_id" in b
    assert "record_action_status" in b


def test_planner_reads_env_brief_and_is_autonomous():
    b = _body("agentic-plan")
    assert "edp_handle" in b
    assert "recipe_id" in b and "step_id" in b
    assert "autonomous" in b
    assert "never prompt the user" in b or "do not ask the user" in b


def test_neuron_stays_user_facing():
    # the neuron is the human's main shell — it must NOT claim to read a
    # spawn env brief (its goal comes from the user).
    b = _body("neuron")
    assert "edp_handle" not in b


def test_neuron_resumes_before_creating():
    # THE cross-session rule: neuron must call resolve_recipe FIRST and
    # honour `resume` (regression for the /clear killer-check failure).
    # Phase 3: the rule now lives in neuron-phase-a (init); the
    # dispatcher points at the phase guides. Check both surfaces.
    b = _body("neuron")
    a = _guide("neuron-phase-a")
    assert "neuron-phase-a" in b  # dispatcher routes to A
    assert "resolve_recipe" in a
    assert "resume" in a
    assert "**do not author a new recipe.**" in a


def test_ocak_is_retired_comprehension_is_tool_forced():
    # v5 P1 marker on the legacy /ocak pointer file (kept as a
    # tombstone). The CURRENT comprehension design lives in the
    # post-HITL sweep doc, but the pointer must still surface that
    # OCAK-as-skill is retired.
    b = _body("ocak")
    assert "retired" in b


def test_neuron_drives_post_hitl_comprehension_and_intent_tools():
    # Post-HITL sweep 2026-05-20 + Phase 3 phasing (2026-05-21):
    # comprehension is REASON-first, specialists on-demand. The
    # mechanics live in neuron-phase-b (comprehension). The
    # `answer_branch` / `record_branch_verdict` legacy is gone
    # everywhere (neither brief nor any phase guide).
    b = _body("neuron")
    phase_b = _guide("neuron-phase-b")
    phase_a = _guide("neuron-phase-a")
    # Legacy out everywhere:
    for body in (b, phase_a, phase_b):
        assert "answer_branch" not in body
        assert "record_branch_verdict" not in body
    # New flow surfaces in Phase B (v2.2: curiosity-driven, not solo
    # free-reasoning — the neuron routes decisions, doesn't decide):
    assert "consult_curiosity" in phase_b
    assert "do not decide alone" in phase_b or "you do not decide alone" \
        in phase_b
    assert "consult_specialist" in phase_b
    # Intent tools surfaced in the right phases:
    assert "start_recipe" in phase_a
    # Dispatcher carries the invariants that span phases:
    assert "real goal" in b
    assert "do not self-evaluate" in b
    # Pushed context invariant preserved:
    assert "context.recap" in b


def test_neuron_done_writes_honest_final_outcome():
    # Phase 3: the close-the-recipe honesty rules live in
    # neuron-phase-e (evaluate) now, with the dispatcher pointing to it.
    e = _guide("neuron-phase-e")
    b = _body("neuron")
    assert "neuron-phase-e" in b  # dispatcher routes to E
    assert "final_outcome" in e
    assert "succeeded" in e and "partial" in e
    assert "**never report a partial close to the user as success.**" in e
    assert "close_recipe" in e


def test_neuron_phase_d_carries_event_router():
    # The operational-curiosity phase — the neuron-phase-d.md
    # event-router table on the new substrate (reply, AskUserQuestion,
    # branch_reviewer / curiosity — /critic retired in v2.4).
    d = _guide("neuron-phase-d")
    # Each kind from the team-comms substrate is in the table:
    assert "question" in d and "progress" in d
    assert "observation" in d and "alert" in d
    # The verbatim discipline from the old design:
    assert "do not self-evaluate" in d
    # Domain correctness routes through the PLANNER's reviewer leg —
    # branch_reviewer was deleted by owner ruling 2026-08-04, and /critic
    # was retired in v2.4. Absence asserted for both, with the positive
    # control that the replacement route is actually named.
    assert "branch_reviewer" not in d
    assert "reviewer leg" in d
    assert "/critic" not in d
    # Uses the new reply tool (not respond / addressing):
    assert "reply" in d
    assert "respond(" not in d  # old tool name
    # Anti-pattern: busy polling
    assert "polling" in d or "busy" in d
    # s17 heartbeat-unification (2026-06-07): the wait/self-wake on `wait`
    # is now the UNIFIED durable recurring CronCreate whose prompt is the
    # lean "reconcile then next_action" — NOT a /neuron re-run (which
    # re-expands the dispatcher + re-dumps decisions every tick) and NOT
    # one-shot ScheduleWakeup. Monitor is the primary wake; the cron is the
    # backstop, idempotently re-confirmed (CronList→CronCreate) on every
    # wait. Crash handling (child_crashed) is preserved (Gap 2 still held).
    assert "croncreate" in d
    assert "reconcile" in d and "next_action" in d
    # the heartbeat must NEVER re-run the /neuron dispatcher
    assert "/neuron" in d and "never" in d
    # Monitor-primary / cron-backstop + idempotent re-confirm
    assert "backstop" in d
    assert "monitor" in d
    assert "cronlist" in d
    # crash handling still surfaced
    assert "child_crashed" in d


def test_neuron_carries_curiosity_layer():
    # Post-HITL sweep 2026-05-20: the brief teaches HOW to think
    # (curiosity, dissent, real-goal-hunting), not just what protocol
    # call to make next. This is the ideology layer the user named.
    b = _body("neuron")
    assert "real goal" in b
    assert "disagree" in b or "dissent" in b
    assert "collaborator" in b
    assert "assumptions" in b


# --- wake (cron-heartbeat) activator prose --------------------------------

def test_planner_arms_heartbeat_and_closes_on_terminal():
    # Planner = waiting parent: protocol-forced cron on `wait`, no LLM
    # discretion; on terminal it notifies the neuron + reaps itself.
    # 2026-05-31 phasing: the wait/heartbeat + finalize protocol lives in
    # the drive phase guide (loaded once the plan exists); the dispatcher
    # only routes there + owns the between-phase /clear.
    b = _guide("planner-phase-drive")
    assert "croncreate" in b
    # 2026-05-25: cadence is adaptive + self-restoring (re-arm every
    # wait), not a fixed once-armed heartbeat_secs cron.
    assert "cronlist" in b and "every wait" in b
    # d36 (load-bearing USER directive): /clear is dead logic — the agent
    # cannot self-fire a slash command — so it was swept from every
    # playbook. Lock its ABSENCE in (was: assert "/clear" in b).
    assert "/clear" not in b
    # 2026-05-20 HITL: plan_closed must go to the <recipe_id> inbox the
    # recipe polls, NEVER addressed to an invented literal "my-neuron"
    # (the broker resolves through its alias map; an unmapped literal →
    # dead letter → recipe waits forever). Lock the positive form in and
    # the buggy form out.
    assert "plan_closed" in b
    # s25/a4: the close broadcast moved from `broker_send(to="<recipe_id>", …)`
    # to `notify_above(kind="plan_closed", …)`. SAME wire message — notify_above
    # sends to=parent with an arbitrary kind, a planner's parent IS the
    # <recipe_id>, and `plan_closed` is in CORE_KINDS — but no new reach: the
    # planner does not hold broker_send, whose arbitrary `to=` would hand every
    # planner unrestricted addressing. Lock the new positive form in, and lock
    # broker_send OUT (a guide may not instruct a verb the role lacks).
    assert "notify_above" in b
    assert "broker_send" not in b
    assert "<recipe_id>" in b          # still names the inbox it lands in
    assert 'to="my-neuron"' not in b   # the exact 2026-05-20 wedge
    # the dispatcher routes to the drive guide (d36: the between-phase
    # /clear it used to own is gone — a slash command can't be self-fired).
    d = _body("agentic-plan")
    assert "planner-phase-drive" in d
    assert "/clear" not in d
    # s16 adoption: broker addressing is no longer "verbatim, no aliases" —
    # the broker resolves through its alias map (unmapped concrete recipient
    # falls back to itself), so an invented "my-neuron" still dead-letters.
    # Lock the corrected warning in (was: assert "verbatim" in b ...).
    assert "alias map" in b and "dead letter" in b
    assert "crondelete" in b
    assert "pool_close_self" in b
    assert "record_plan" in b          # the replan branch
    # c1: brief-from-disk fix (no next_action before record_plan).
    # 2026-05-31: the planner GROUNDS in the recipe via the recipe_id LINK
    # (read_object('recipe') → outcomes/decisions) before authoring, so it
    # plans on the real intent — not a misread of the step string (the
    # wrong-plan-discard token burn). That discipline now lives in the
    # GROUND phase guide, loaded before authoring.
    g = _guide("planner-phase-ground")
    assert 'read_object("recipe"' in g
    assert "expected_outcomes" in g and "misread" in g


def test_worker_two_way_via_upfront_cron_and_closes_cleanly():
    # Team-architecture Phase 2 (2026-05-21): workers are now full
    # two-way team members. Heartbeat cron armed at Step 0 (upfront,
    # before the task) so they can ask_above + end turn + check_inbox
    # on wake. On done: CronDelete → record_action_status →
    # pool_close_self.
    b = _body("worker")
    assert "pool_close_self" in b
    assert "croncreate" in b  # Step 0 heartbeat
    assert "check_inbox" in b  # the receive-side tool
    assert "ask_above" in b  # the send-side tool
    # close happens AFTER recording status, not before.
    assert b.index("record_action_status") < b.index("pool_close_self")
    # heartbeat torn down on close.
    assert "crondelete" in b
    # blocker fallback path preserved (record failed + stop).
    assert "failed" in b


def test_neuron_heartbeat_is_durable_cron_and_never_self_closes():
    # s17 heartbeat-unification (2026-06-07): the neuron self-pacing
    # heartbeat is now the UNIFIED durable recurring CronCreate whose
    # prompt is the lean "reconcile then next_action" — NOT a /neuron
    # re-run (re-expands the dispatcher + re-dumps decisions every tick)
    # and NOT one-shot ScheduleWakeup / /loop. The Monitor push is the
    # primary wake, the cron is the backstop, idempotently re-confirmed
    # (CronList→CronCreate) on every wait. The brief stays short; the
    # offloaded operational detail + the never-self-close invariant live
    # in the loaded-on-demand protocol-reference guide.
    g = _guide("neuron-protocol-reference")
    # durable recurring cron with the lean reconcile+next_action prompt
    assert "croncreate" in g
    assert "reconcile" in g and "next_action" in g
    # the heartbeat must NEVER re-expand the /neuron dispatcher
    assert "/neuron" in g and "never" in g
    # Monitor-primary / cron-backstop + idempotent re-confirm
    assert "backstop" in g
    assert "cronlist" in g
    # the never-self-close invariant preserved (offloaded to the guide)
    assert "pool_close_self" in g


def test_protocol_reference_guide_exists_and_is_loadable():
    # Post-HITL sweep 2026-05-20: brief offloads protocol prose into a
    # guide loaded on demand via get_guide('neuron-protocol-reference').
    g = _guide("neuron-protocol-reference")
    assert "wait pattern" in g or "heartbeat" in g
    assert "context block" in g
    assert "close_recipe" in g
    assert "broker" in g


def test_planner_dispatcher_stays_thin_and_phases_one_at_a_time():
    # 2026-05-31: the root failure was a monolithic agentic-plan.md that
    # loaded vocab + reactive-streams + a shape guide + the recipe + the
    # whole dispatch loop in ONE turn (~30k tokens before replying →
    # hallucination). The dispatcher is now thin: it routes to ground →
    # author → drive, each loaded on demand. Guard both halves so it can't
    # silently re-fatten back into the monolith.
    d = _body("agentic-plan")
    # routes to all three phases via get_guide, one at a time
    for phase in ("planner-phase-ground", "planner-phase-author",
                  "planner-phase-drive"):
        assert phase in d
    assert "one at a time" in d or "one phase guide" in d
    # the heavy content must NOT be re-inlined into the dispatcher:
    # the 7-shape selection table belongs to the author guide, not here.
    shape_names_inline = sum(
        s in d for s in
        ("linear-build", "modular-build", "poc-iterate-build",
         "diagnose-fix-verify", "research-synthesize",
         "creative-production", "gather-validate-submit"))
    assert shape_names_inline == 0, "shape table re-inlined into dispatcher"
    # the dispatch-loop instruction prose belongs to the drive guide.
    assert "dispatch_action" not in d
    # a thin dispatcher stays small (the monolith was 323 lines).
    line_count = len((_CMD / "agentic-plan.md").read_text(
        encoding="utf-8").splitlines())
    assert line_count < 130, f"dispatcher grew to {line_count} lines"


# --- Phase 4: shape pipelines for planner ---------------------------------

def test_planner_dispatcher_carries_shape_selection_table():
    # Phase 4 (2026-05-21): the planner picks a shape based on the work,
    # then loads the shape guide. 2026-05-31 phasing: the shape selection
    # table + authoring mechanics moved into the AUTHOR phase guide; the
    # dispatcher only routes to it. Check both surfaces (the neuron-phase
    # pattern: dispatcher routes, phase guide carries the mechanic).
    d = _body("agentic-plan")
    # The dispatcher routes to the three planner phases via get_guide:
    assert "get_guide" in d
    for phase in ("planner-phase-ground", "planner-phase-author",
                  "planner-phase-drive"):
        assert phase in d
    # The author guide carries the actual shape table + authoring rules:
    b = _guide("planner-phase-author")
    # All 7 shape names must be in the selection table:
    for shape in ("linear-build", "modular-build", "poc-iterate-build",
                  "diagnose-fix-verify", "research-synthesize",
                  "creative-production", "gather-validate-submit"):
        assert shape in b
    # Each routes through get_guide:
    assert "get_guide" in b
    # If the planner can't pick, escalate (not self-resolve):
    assert "ask_above" in b
    # outcome-verify: planner must author a deterministic verify block
    # for file-producing actions (catches false-dones). Under d30 the
    # framework runs no gate — the DUAL-GATE (worker in-shell + reviewer
    # re-run) is what stops a false-done.
    assert "verify" in b
    assert "file_exists" in b
    assert "dual-gate" in b
    # incremental plan builders (2026-05-22): no monolithic plan object.
    assert "create_plan" in b and "add_action" in b


def test_all_planner_shape_guides_exist():
    # Each of the 7 shape guides must be loadable. Key markers verify
    # the WHEN-IT-APPLIES + core mechanics survived the port.
    expectations = {
        "planner-shape-linear-build": ["routine", "leaf actions",
                                       "acceptance"],
        "planner-shape-modular-build": ["axes of variation",
                                        "axes-of-variation",
                                        "decomposition"],
        "planner-shape-poc-iterate-build": ["stage a", "stage b", "gate",
                                            "benchmark"],
        "planner-shape-diagnose-fix-verify": ["reproduce",
                                              "regression",
                                              "root cause"],
        "planner-shape-research-synthesize": ["survey", "synthesize",
                                              "single-shell"],
        "planner-shape-creative-production": ["reference survey",
                                              "feasibility",
                                              "prior art"],
        "planner-shape-gather-validate-submit": ["validate",
                                                 "irreversible",
                                                 "schema"],
    }
    for name, markers in expectations.items():
        body = _guide(name)
        for m in markers:
            assert m.lower() in body.lower(), f"{name} missing {m!r}"
