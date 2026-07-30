"""W2 leg 6 (DESIGN-v6 §W2; d17) — SHELL-FACING DOC SYNC regression guard.

This pins the doc-vs-code coherence that a5 landed, so a later edit cannot
silently re-introduce the drift the redesign exists to kill:

* No ScheduleWakeup MANDATE survives in the LIVE guides/role files. Every
  remaining mention must be a RETIREMENT/anti-pattern reference (the self-paced
  loop uses a durable recurring CronCreate, never a one-shot ScheduleWakeup).
  The stale design doc REDESIGN-fsm-as-guide.md carries a RETIRED header.
* The stateless-grounding-epoch "echo the epoch" rule is present in the driver
  role files (worker + planner) — the shells that receive an epoch on every
  context/action push and run interactive turns.
* THE GROUNDING-KIND REGRESSION GUARD (the gap a3 hit at startup): every
  `notify_above(...)` / `broker_send(...)` kind PRESCRIBED in a role/guide file
  is a CORE BrokerKind. `grounding`/`fyi` were once in-process-only
  register_kinds — accepted by the MCP process but REJECTED by the SEPARATE
  broker process — so a prescribed-but-non-core kind is exactly the silent
  fallback-to-observation bug. The broker validates against CORE_KINDS only, so
  that is the registry this asserts against (not the in-process registry).

All assertions are done in PYTHON — never grep (the acceptance verify shell has
neither `env` nor `grep`, per d8). No env prefix is used; this test reads files
only, so no EDP_ROLE/EDP_HANDLE neutralisation is needed.
"""

import re
from pathlib import Path

from edp_contracts.broker import CORE_KINDS

REPO = Path(__file__).resolve().parents[1]
GUIDES = REPO / "docs" / "guides"
COMMANDS = REPO / ".claude" / "commands"
REDESIGN = REPO / "docs" / "design" / "REDESIGN-fsm-as-guide.md"

# A ScheduleWakeup mention is ALLOWED only if the same line frames it as retired
# / an anti-pattern (i.e. tells shells NOT to use it). A bare imperative to use
# it is a MANDATE and fails.
_RETIREMENT_MARKERS = (
    "not ", "n't ", "retired", "superseded", "out too", "out —", "fragile",
    "no longer", "historical", "instead of", "never", "deprecated", "was:",
)


def _live_shell_files():
    """The LIVE shell-facing docs: every guide + every role command file."""
    return sorted(GUIDES.glob("*.md")) + sorted(COMMANDS.glob("*.md"))


def test_no_schedulewakeup_mandate_in_live_docs():
    offenders = []
    for f in _live_shell_files():
        lines = f.read_text(encoding="utf-8").splitlines()
        for idx, line in enumerate(lines):
            if "schedulewakeup" not in line.lower():
                continue
            # A retirement/anti-pattern framing can wrap across a line break
            # (e.g. "... NOT one-shot\n`ScheduleWakeup` — s27 ..."), so judge on
            # the surrounding window, not the single line.
            window = " ".join(lines[max(0, idx - 1):idx + 2]).lower()
            if not any(m in window for m in _RETIREMENT_MARKERS):
                offenders.append(
                    f"{f.relative_to(REPO)}:{idx + 1}: {line.strip()}"
                )
    assert not offenders, (
        "ScheduleWakeup MANDATE(s) survive in live shell-facing docs (must be "
        "retired / framed as anti-pattern):\n" + "\n".join(offenders)
    )


def test_redesign_design_doc_is_retired_header_first():
    """The stale design doc keeps its ScheduleWakeup history but must announce
    RETIRED up top so no shell reads it as live guidance (ocak.md pattern)."""
    assert REDESIGN.exists(), f"missing {REDESIGN}"
    head = REDESIGN.read_text(encoding="utf-8").splitlines()[:15]
    head_blob = "\n".join(head).lower()
    assert "retired" in head_blob, (
        "REDESIGN-fsm-as-guide.md must carry a RETIRED marker in its first 15 "
        "lines pointing at the canonical loop-and-heartbeat guide."
    )


def test_epoch_echo_rule_present_in_driver_role_files():
    """The one-line epoch-echo rule reaches the shells that get an epoch and
    run interactive turns (worker + planner). neuron.md is human-overseen and
    its diff is surfaced for approval separately, so it is not asserted here."""
    for name in ("worker.md", "agentic-plan.md"):
        text = (COMMANDS / name).read_text(encoding="utf-8").lower()
        assert "echo the epoch" in text, (
            f"{name} is missing the epoch-echo rule ('echo the epoch ... on "
            "interactive turns')."
        )


# Kinds are extracted from the two verbs that cross the shell->BROKER boundary.
# emit_recipe_event uses a SEPARATE recipe-event registry, so it is deliberately
# excluded here — only broker-bound kinds are checked against CORE_KINDS.
_NOTIFY_KIND = re.compile(r'notify_above\(\s*kind=["\']([a-z_]+)["\']')
_BROKER_KIND = re.compile(r'broker_send\([^)]*kind=["\']([a-z_]+)["\']')


def test_every_prescribed_broker_kind_is_core():
    prescribed = {}  # kind -> first "file:line" it appears at
    for f in _live_shell_files():
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            for m in (*_NOTIFY_KIND.finditer(line), *_BROKER_KIND.finditer(line)):
                prescribed.setdefault(m.group(1), f"{f.relative_to(REPO)}:{i}")
    assert prescribed, "sanity: expected to find prescribed broker kinds"
    unregistered = {
        k: loc for k, loc in prescribed.items() if k not in CORE_KINDS
    }
    assert not unregistered, (
        "role/guide files prescribe notify_above/broker_send kind(s) that are "
        "NOT CORE BrokerKinds — the broker (a separate process, CORE_KINDS "
        "only) will REJECT them (the grounding-kind gap). Register them in "
        "edp_contracts.broker.CORE_KINDS or correct the guide:\n"
        + "\n".join(f"  {k!r} at {loc}" for k, loc in sorted(unregistered.items()))
    )
    # grounding + fyi specifically — the a5 fix — must be present.
    assert {"grounding", "fyi"} <= set(CORE_KINDS)


# ── orphan-detector doc/code coherence (2026-07-25) ───────────────────────
# The detector resolves a dispatched action to a backing handle. It used to
# consult ONLY the recorded batch head, which is wrong for a member that was
# re-dispatched STANDALONE after its head shell exited: `batch_group` is
# immutable post-authoring, so the record keeps naming a head that is
# legitimately gone, and a perfectly healthy worker was reported unbacked on
# every poll, forever, with no move available to the planner that fixed it.
# `driver.py` now checks the action's OWN handle FIRST and falls back to the
# head only when the action has no live session of its own.
#
# These pin the GUIDES to that behaviour. A guide is what a shell actually
# reads, so a guide still teaching head-only resolution would keep producing
# the old (wrong) hand-probing advice no matter how correct the code is —
# and a guide instructing something the code cannot do is the very drift
# class this module exists to guard.
_ORPHAN_GUIDES = ("loop-and-heartbeat.md", "planner-phase-drive.md",
                  "reactive-streams-reference.md", "reactive-streams.md")


def _guide(name: str) -> str:
    return (GUIDES / name).read_text(encoding="utf-8").lower()


def test_no_guide_teaches_head_only_orphan_resolution():
    """Any guide describing the batch-head resolution must ALSO say the
    member's own handle is consulted first — otherwise it teaches the bug."""
    offenders = []
    for name in _ORPHAN_GUIDES:
        text = _guide(name)
        # Only guides that actually discuss BATCH resolution are on the hook.
        # A bare "head" is not enough — reactive-streams.md says "in your head"
        # about something else entirely, and flagging that would manufacture a
        # finding rather than catch one.
        if "rx.orphaned" not in text or "batch" not in text:
            continue
        if "own handle" not in text:
            offenders.append(name)
    assert not offenders, (
        "guide(s) describe rx.orphaned's batch-head resolution without stating "
        "that the member's OWN handle is checked FIRST — that is the code's "
        "actual order and the fix for the immutable-batch_group false "
        f"positive: {offenders}")


def test_orphan_coverage_boundary_is_stated():
    """The detector joins RECORDED-UNDERWAY work against liveness, so an
    action that never STARTED is `pending` — undispatched, not orphaned — and
    the stream is correctly silent about it. Somebody will otherwise read a
    quiet orphan plane as 'every action has a shell behind it'."""
    text = _guide("loop-and-heartbeat.md")
    assert "coverage boundary" in text, (
        "loop-and-heartbeat must state rx.orphaned's coverage boundary "
        "explicitly (never-started work is pending, not orphaned)")
    assert "pending" in text and "undispatched" in text, (
        "the boundary must name the pending/undispatched case it does NOT "
        "cover, not merely gesture at having limits")


def test_chatty_sources_are_not_merged_into_the_inbox_driver():
    """One fate per subscription. A merge binds every leg together, so a
    flooding source can get the whole driver auto-stopped and take the
    DIRECTED INBOX with it — and going deaf is silent. Paid for on
    2026-07-25 when a false-positive orphan storm forced a planner to tear
    down the subscription carrying its own mail."""
    for name in ("loop-and-heartbeat.md", "reactive-streams.md"):
        text = _guide(name)
        assert "merge" in text and "inbox" in text, f"{name}: sanity"
        assert ("one fate" in text or "own subscription" in text
                or "its own `observe()`" in text), (
            f"{name} must warn against merging a chatty/newly-landed source "
            "into the driver that carries your inbox, and say to arm it "
            "separately")


def test_canonical_per_role_table_does_not_refilter_the_pool_leg():
    """The neuron's pool leg once carried `states=['dead']`. A shell that
    exits CLEANLY never passes through `dead` — its row just vanishes — so
    the filtered view is empty on both sides and change-detection never
    fires. That filter WAS the blindness; the canonical table must not
    reintroduce it."""
    rows = 0
    for line in (GUIDES / "loop-and-heartbeat.md").read_text(
            encoding="utf-8").splitlines():
        s = line.strip()
        if not (s.startswith("| **neuron**") or s.startswith("| **planner**")):
            continue
        rows += 1
        assert "rx.pool(" in s, f"per-role row lost its pool leg: {s[:80]}"
        pool_args = s.split("rx.pool(")[1].split(")")[0]
        assert "states=" not in pool_args, (
            "the canonical per-role table re-filtered the pool leg — a "
            f"cleanly-exiting shell is invisible to it: {s[:120]}")
    assert rows == 2, (
        f"expected the neuron + planner rows of the canonical table, found {rows}")


# ── the per-role table is a FLOOR, and wiring is re-checkable in flight ───
# The reactive layer offers far more than the three sources every recipe
# actually uses, and the guides were why: the cadence guide's per-role table
# is copyable, so a context-pressed shell copies it and never opens the
# decision map. Read as THE ANSWER rather than THE MINIMUM it produced three
# under-subscription stalls in one day (a pool leg filtered blind to clean
# exits, an orphan source nobody armed, a timeout nobody used).

def test_per_role_table_is_presented_as_a_floor_with_an_upgrade_path():
    text = _guide("loop-and-heartbeat.md")
    assert "floor" in text and "minimum" in text, (
        "the per-role table must say it is a FLOOR/MINIMUM, not the complete "
        "wiring — read as the answer, it suppresses composition")
    # the upgrade path must be INLINE: a second guide fetch is the thing a
    # context-pressed shell demonstrably does not do.
    for cue in ("fork-join", "timeout", "min_interval_ms"):
        assert cue in text, (
            f"the situation-to-composition table must name {cue!r} inline so "
            "composing does not require a second guide fetch")


def test_wiring_recheck_is_hung_on_the_already_computed_pacing_band():
    """The re-check must ride the heartbeat (guaranteed, recurring) rather
    than a moment the shell has to notice — an under-wired shell is by
    definition not noticing. But the loop is deliberately cheap, so the
    trigger must be a signal the loop ALREADY computes: `wait_reason` is a
    deterministic band from a table lookup (fsm/state_machines.PACING), free
    on every tick and silent on a steady one."""
    text = _guide("loop-and-heartbeat.md")
    assert "wait_reason" in text and "band" in text, (
        "the in-flight wiring re-check must hang off the already-computed "
        "pacing band, not a new computation or a mandatory checklist")
    assert "nothing told me otherwise" in text, (
        "'it must still be working, nothing told me otherwise' must be "
        "promoted from an observation into an explicit re-wire TRIGGER")
