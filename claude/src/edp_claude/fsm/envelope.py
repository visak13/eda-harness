"""Question envelope — code-composed context for upward/user-facing questions
(DESIGN-v7 §2.1).

THE ROOT CAUSE THIS CLOSES: `compose_consult_question` auto-composed rich,
action-specific context — but only for the STUCK-ACTION CONSULT path. Every
other upward question (`ask_above`) shipped a bare `body={"question": …}`,
and the neuron then relayed context-free options to the user (the DESIGN-v6
finding: "a neuron that asks the user questions with zero attached context").

`compose_question_envelope` is the GENERALIZATION: given whichever of the
loaded objects (plan / action / recipe / step) the caller has in play, it
assembles the same ingredients the consult question always had —

  - the GOAL line (plan goal, falling back to the recipe's verbatim user goal),
  - WHAT-I-WAS-DOING (the action description, or the step description for a
    planner-level question with no action in play),
  - the ACCEPTANCE DIFF (EXPECTED / VERIFY / ACTUAL) when an action is in play,
  - WHAT-BLOCKS-ON-THIS (the actions/steps whose depends_on names this one —
    what the answerer is holding up by not answering),
  - pass-through OPTION slots (the asker's proposed answers, untouched).

ENRICHMENT BY CONSTRUCTION, NOT BY INSTRUCTION: the tool layer (`ask_above`)
attaches the composed envelope in code — there is no refusal path and no
guide-compliance dependency. A question can no longer arrive bare unless the
asker had literally no lineage to compose from.

PURE MODULE (principle 6): no IO, no clock, no LLM. Callers thread in the
already-loaded objects, exactly as `plan_fsm` threads in `worklog_tail` and
`live_action_ids`. `plan_fsm.compose_consult_question` is now a thin caller
of this module (its consult text is pinned by tests and stays equivalent).
"""

# Cap for the one-line renderings of dependent actions/steps inside
# `blocks_on_this` — enough to identify the work, bounded so a plan with long
# descriptions cannot balloon a question body (CORE-#18 discipline).
_BLOCK_LINE_CAP = 160


def acceptance_diff(a) -> str:
    """What acceptance EXPECTED vs what was actually recorded, as prose. This is
    half the auto-composed question — the half that says what "done" was
    supposed to mean and what the action produced instead.

    Moved here from `plan_fsm._acceptance_diff` (DESIGN-v7 2.1) so the consult
    path and the envelope path render ONE diff shape; `plan_fsm` re-imports it.
    Never returns empty: the EXPECTED/ACTUAL lines are always emitted, with
    explicit "(none recorded)" / "(nothing recorded)" markers."""
    exp = (getattr(a.acceptance, "expected", "") or "").strip()
    act = (getattr(a.acceptance, "actual", None) or "").strip()
    verify = getattr(a.acceptance, "verify", None)
    lines = [f"EXPECTED: {exp or '(none recorded)'}"]
    if verify:
        v = verify if isinstance(verify, dict) else verify.model_dump()
        cmd = v.get("cmd") or v.get("check") or ""
        if cmd:
            lines.append(f"VERIFY: {cmd}")
    lines.append(f"ACTUAL: {act or '(nothing recorded)'}")
    return "\n".join(lines)


def _one_line(text, cap: int = _BLOCK_LINE_CAP) -> str:
    """First line of `text`, length-capped — the projection used for the
    dependent-work listing (identify, don't reproduce)."""
    s = str(text or "").strip().splitlines()
    first = s[0].strip() if s else ""
    return (first[:cap].rstrip() + "…") if len(first) > cap else first


def _blocks_on_action(plan, action) -> list[str]:
    """The plan's actions whose depends_on names `action` — the work the
    answerer is holding up. Plan order, one capped line each."""
    out: list[str] = []
    aid = getattr(action, "action_id", None)
    for a2 in getattr(plan, "actions", None) or []:
        if aid and aid in (getattr(a2, "depends_on", None) or []):
            out.append(f"{a2.action_id}: {_one_line(a2.description)}")
    return out


def _blocks_on_step(recipe, step) -> list[str]:
    """The recipe's steps whose depends_on names `step` — same shape one level
    up, for a planner-level (no-action) question."""
    out: list[str] = []
    sid = getattr(step, "step_id", None)
    for s2 in getattr(recipe, "steps", None) or []:
        if sid and sid in (getattr(s2, "depends_on", None) or []):
            out.append(f"{s2.step_id}: {_one_line(s2.description)}")
    return out


def compose_question_envelope(*, plan=None, action=None, recipe=None,
                              step=None, options=None) -> dict:
    """Assemble the question envelope from whichever objects are in play.

    Every argument is optional — the envelope is composed from what the caller
    COULD load, never refused for what it couldn't (enrichment by construction;
    a worker mid-crash-recovery with only its plan still gets a goal line).

    Returned dict (keys omitted when there is nothing to say, so the envelope
    never carries empty filler):
      goal            — the plan's goal, else the recipe's verbatim user goal.
      doing           — what the asker was doing: the action description, else
                        the step description (planner-level question).
      acceptance_diff — EXPECTED/VERIFY/ACTUAL, only when an action is in play
                        (never empty then — see `acceptance_diff`).
      blocks_on_this  — capped one-liners of the actions (or steps) whose
                        depends_on names the asker's work: what the answer
                        unblocks. Omitted when nothing depends on it.
      options         — the asker's proposed answers, passed through VERBATIM
                        (the neuron relays these to the user unedited).
      asked_from      — the ids the envelope was composed from, so a relay can
                        `read_object` deeper without re-deriving lineage.

    PURE: no IO — every object arrives loaded."""
    env: dict = {}

    goal = getattr(plan, "goal", None) or getattr(
        recipe, "user_goal_verbatim", None)
    if goal:
        env["goal"] = goal

    doing = getattr(action, "description", None) or getattr(
        step, "description", None)
    if doing:
        env["doing"] = doing

    if action is not None:
        env["acceptance_diff"] = acceptance_diff(action)

    blocks: list[str] = []
    if plan is not None and action is not None:
        blocks = _blocks_on_action(plan, action)
    elif recipe is not None and step is not None:
        blocks = _blocks_on_step(recipe, step)
    if blocks:
        env["blocks_on_this"] = blocks

    if options:
        env["options"] = options

    asked_from: dict = {}
    for key, obj, attr in (("recipe_id", recipe, "recipe_id"),
                           ("plan_id", plan, "plan_id"),
                           ("step_id", step, "step_id"),
                           ("action_id", action, "action_id")):
        val = getattr(obj, attr, None)
        if val:
            asked_from[key] = val
    if asked_from:
        env["asked_from"] = asked_from

    return env
