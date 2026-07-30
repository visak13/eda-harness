"""s26 (d68/C9, user ruling d70) — NO LIVE GUIDE CALLS A TOOL THAT DOES NOT EXIST.

THE BLIND SPOT THIS CLOSES, stated precisely
--------------------------------------------
`tests/test_w4_roles.py::test_every_tool_a_roles_own_guides_instruct_it_to_call_is_in_its_toolset`
asks: *"of the REGISTERED tools, does a role's guide call one its toolset
withholds?"* Its candidate set is `_all_names()` — the registry itself
(`_gaps()`, test_w4_roles.py:727). A guide naming a verb that is in NO role's
toolset because it is in NO registry AT ALL is therefore invisible to it **by
construction**. A green class-guard run is NOT evidence that guides name only
real tools.

It hid `pattern-observer.md:28`, which called `pattern_observer_analyze(...)`
for months. That name is not one of the 86 registered tools, and `build_mcp`
fails **CLOSED** on such drift (`mcp_server.py:150-158`) — so "just add it to
`roles.py`" would take the MCP server down at startup for **every** shell. The
guide was the defect; d70 ruled it dead text and it is deleted.

This module asks the INVERTED question, and so its candidate set is the guide
text rather than the registry:

    every snake_case CALL FORM in a live shell-facing guide
    names a REGISTERED tool (or a declared non-tool vocabulary).

THE DISCRIMINATOR (and why it is not the same as test_w4_roles')
----------------------------------------------------------------
Same instruct-vs-mention rule (d64): a backticked MENTION is not a defect, a
CALL FORM is. Two deliberate tightenings over `_called_in`:

* **The paren must be ADJACENT.** `_called_in` tolerates `name (`, which in
  English prose matches every parenthetical: "your plan_id (`<recipe_id>`…)"
  (agentic-plan.md:29), "for each option in plan_options (or …)"
  (framework-ocak.md:88). Those are four false positives, not four bugs. A tool
  call in this corpus is always written `tool(args)`. `_called_in` can afford
  the leniency because its candidates are already known-real tool names; here
  the candidate set IS the text, so the leniency would manufacture findings —
  exactly what d64 forbids.
* **snake_case, no leading underscore.** MCP tools are all `lower_snake_case`.
  This drops the CamelCase harness tools (`CronCreate(`, `TaskStop(`,
  `Monitor(`) — which are real, just not MCP — and private identifiers quoted
  from source (`_orig(`, `_w(` in verification-craft.md:57).

Coding-standard #7: no `re`. `str.find` + an identifier-boundary check, the
same shape as `test_w4_roles._called_in` and `_guides_loaded_by`.
"""

import string
from pathlib import Path

from edp_claude.tools._tools import ALL_TOOL_CLASSES
from edp_claude.tools.roles import RETIRED_VERBS, ROLE_TOOLSETS

# The one direction of test-to-test import: s26 reads w4's corpus definitions to
# prove the SUPERSET property below. Never the reverse (that would be a cycle).
from test_w4_roles import (
    ROLE_COMMAND_FILE,
    UNSCANNED_GUIDES,
    _role_docs,
    _shared_guides,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMANDS_DIR = REPO_ROOT / ".claude" / "commands"
GUIDES_DIR = REPO_ROOT / "docs" / "guides"

RECORD_CONTEXT = "record_context"

# Non-tool snake_case call forms that legitimately appear in the corpus. Kept
# SHORT and REASONED — a long list here is how this gate would rot into the
# rubber stamp it was written to replace.
#
# The rx DSL is NOT listed: it is DERIVED from `RxRuntime`'s public methods
# below, because a hand-copied vocabulary is a vocabulary that drifts (the same
# argument test_w4_roles makes for importing `_CONSOLIDATED_OUT` from roles.py
# rather than re-spelling it).
NON_TOOL_CALL_FORMS: dict[str, str] = {
    "canonical_json": (
        "reactive-streams-effects.md:106 — a term inside the idempotency-key "
        "FORMULA `sha256(rule_id :: canonical_json(resolved …))`, describing "
        "`effects._canonical`. Notation in a hash definition, not an "
        "instruction to call an MCP verb."),
    # (The `generate_image` entry was removed with the gpt-image server, v7
    # follow-up 2026-07-16: visual/3D assets now go through Sol via the
    # `sol_author_asset` tool, which is REGISTERED in the edp-claude registry
    # this gate scans, so worker.md can call it with no allowlist exception.)
}

_IDENT_CHARS = frozenset(string.ascii_letters + string.digits + "_")


def _all_tool_names() -> set[str]:
    return {c.name for c in ALL_TOOL_CLASSES} | {RECORD_CONTEXT}


def _rx_dsl_names() -> set[str]:
    """The reactive spec vocabulary — `rx.broker(…)`, `switch_map(…)`,
    `recipe_events(…)` — read from `RxRuntime`'s public methods, which is what
    `compile_spec` actually resolves a spec string against. Derived, never
    re-spelled."""
    from edp_claude.reactive.runtime import RxRuntime

    return {n for n in vars(RxRuntime) if not n.startswith("_")}


def live_shell_files() -> list[Path]:
    """The LIVE shell-facing corpus: every role command file + every guide.

    Identical to `test_v6_docs._live_shell_files`. `docs/design/**` is
    deliberately OUT: DESIGN-v4.md, DESIGN-ML.md and ARCHITECTURE-DIAGRAM.md
    DESCRIBE a superseded design in prose. Historical prose is not a defect
    (d64), and scanning it would manufacture findings out of history."""
    return sorted(COMMANDS_DIR.glob("*.md")) + sorted(GUIDES_DIR.glob("*.md"))


def snake_call_forms(text: str) -> set[str]:
    """Every `lower_snake_case(` in `text` — the identifier IMMEDIATELY followed
    by an open paren.

    The character before the identifier must not be an identifier char, so
    `rx.broker(` yields `broker` (the `.` is a boundary) while `xrecall(` does
    not yield `recall`."""
    found: set[str] = set()
    start = 0
    while (i := text.find("(", start)) >= 0:
        start = i + 1
        j = i
        while j > 0 and text[j - 1] in _IDENT_CHARS:
            j -= 1
        name = text[j:i]
        if not name or name[0] == "_" or not name[0].isalpha():
            continue
        if name.islower() and "_" in name:
            found.add(name)
    return found


def unregistered_call_sites() -> dict[str, list[str]]:
    """name -> ["file:line", …] for every snake_case call form in the live
    corpus that is not a registered tool nor a declared non-tool vocabulary."""
    allowed = _all_tool_names() | _rx_dsl_names() | set(NON_TOOL_CALL_FORMS)
    offenders: dict[str, list[str]] = {}
    for path in live_shell_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1):
            for name in snake_call_forms(line) - allowed:
                offenders.setdefault(name, []).append(f"{rel}:{lineno}")
    return offenders


# ════════════════════════════════════════════════════════════════════════
# THE GATE
# ════════════════════════════════════════════════════════════════════════
def test_no_live_guide_calls_an_unregistered_tool():
    """d70. A guide that instructs a role to CALL a nonexistent verb cannot be
    followed, and `roles.py` cannot be fixed to make it followable: `build_mcp`
    fails CLOSED on drift, so transcribing the name into a role's frozenset
    takes the MCP server down at startup for every shell. The GUIDE is the
    defect."""
    offenders = unregistered_call_sites()
    assert not offenders, (
        "live guide(s) CALL a verb that is not a registered MCP tool. A role "
        "cannot follow such an instruction, and adding the name to "
        "tools/roles.py would make build_mcp fail closed at startup for EVERY "
        "shell (mcp_server.py:150-158). Delete the call form, or register the "
        "tool:\n" + "\n".join(
            f"  {name}(...) at {', '.join(sites)}"
            for name, sites in sorted(offenders.items())))


def test_the_two_dead_verbs_are_gone_from_the_live_corpus():
    """d70, pinned by NAME as well as by class. The class gate above would catch
    a reintroduction, but naming the two verbs the user ruled dead makes the
    regression unmistakable in the failure text."""
    for path in live_shell_files():
        text = path.read_text(encoding="utf-8")
        for dead in ("pattern_observer_analyze", "invoke_skill"):
            assert dead not in snake_call_forms(text), (
                f"{path.name} re-introduced a CALL FORM of {dead!r}, which d70 "
                "ruled dead guide text. It is not a registered tool.")


def test_invoke_skill_survives_as_a_described_instruction_kind_not_a_call():
    """The d64 triage, pinned so a later cleanup cannot over-delete.

    `invoke_skill` is NOT a tool — it is an `InstructionKind`
    (`schemas/instruction.py:25`) that `plan_fsm.py:168` EMITS TO the planner in
    `ACCEPTANCE_REVIEW`. `planner-phase-drive.md` documents it under
    "Instruction kinds:" as something the planner RECEIVES. That is a correct
    description of live FSM behaviour: deleting it would strand a planner that
    is handed the instruction. A correct exclusion must not be "fixed"."""
    from edp_claude.schemas.instruction import InstructionKind

    assert InstructionKind.INVOKE_SKILL == "invoke_skill"
    assert "invoke_skill" not in _all_tool_names()

    drive = (GUIDES_DIR / "planner-phase-drive.md").read_text(encoding="utf-8")
    assert "invoke_skill" in drive, (
        "planner-phase-drive.md must keep DESCRIBING the invoke_skill "
        "instruction kind — plan_fsm.py:168 still emits it")
    assert "invoke_skill" not in snake_call_forms(drive), (
        "…but never in CALL FORM: a planner receives it, it does not call it")


# ════════════════════════════════════════════════════════════════════════
# W6.4 — THE RETIRED-VERB GATE
#
# WHY IT LIVES HERE AND NOT IN test_w4_roles. The d17 class-guard asks "does a
# role's guide call a tool its toolset withholds?" — and it EXCLUDES retired verbs
# from its candidate set by construction (`_gaps()`: `exclude = set(RETIRED_VERBS)`),
# because a guide calling a verb NO role has is a stale guide, not a toolset gap.
# So the verb this milestone retires is exactly the verb that test cannot see. The
# guard has to be here, where the candidate set is the TEXT and the corpus is every
# command file + every guide — strictly wider than w4's role-attributed walk
# (`test_s26_corpus_is_a_strict_superset_of_the_w4_scanned_corpus` proves it), and
# so it also covers the shared reference docs and the UNSCANNED_GUIDES hatch.
#
# THE DISCRIMINATOR IS THE CALL FORM, AND THAT IS FORCED, NOT LAZY. A gate on the
# NAME is unshippable: `remember` is an ordinary English word, and the live corpus
# uses it that way six times ("you don't have to remember to re-ground",
# loop-and-heartbeat.md:111; worker.md:17; neuron.md:106; curiosity.md:177;
# pattern-observer.md:95; neuron-phase-d.md:154). A name gate would fail on English
# prose and get "fixed" by allowlisting the very files it should be watching.
# `record_step` is worse than that: a NAME gate matches `record_step_result(`, a
# LIVE tool on the planner surface — the gate would demand the deletion of a
# working call. The identifier-boundary + adjacent-paren rule in `snake_call_forms`
# is what makes `record_step_result(` not a call of `record_step`.
#
# WHAT THIS GATE THEREFORE CANNOT SEE, STATED RATHER THAN GLOSSED: an INSTRUCTING
# MENTION in prose ("ask the neuron to remember it"). That half was swept BY HAND
# (s29/a1) and re-greppable; this gate holds the mechanical half. Saying so is the
# point — a guard whose blind spot is undocumented reads as total coverage.
# ════════════════════════════════════════════════════════════════════════
def calls_of(text: str, names) -> set[str]:
    """The `names` appearing in CALL FORM — `name(`, identifier-boundary on the
    left, paren IMMEDIATELY on the right.

    NOT built on `snake_call_forms`, and the reason is load-bearing enough that
    reusing it would have shipped a VACUOUS gate (caught by
    `test_the_retired_gate_discriminates_the_shapes_that_forced_its_design`, which
    is why that test exists): `snake_call_forms` DISCOVERS unknown identifiers, so
    to stay snake_case it requires `"_" in name` — and `remember`, a retired verb,
    HAS NO UNDERSCORE. It would have been invisible, and the gate would have passed
    green while the verb it most needed to catch went unguarded.

    Here the candidate set is KNOWN (RETIRED_VERBS, imported from roles.py), so the
    identifier need not be re-discovered and the underscore rule is not merely
    unnecessary but fatal. Same str.find + boundary shape as
    `test_w4_roles._called_in` (coding-standard #7: no `re`).

    NOTE, and it is a live finding rather than a footnote: this same underscore rule
    means `snake_call_forms` — and therefore the UNREGISTERED-tool gate above —
    cannot see a call of ANY single-word tool (`remember`, `recall`, `observe`,
    `reply`, `whoami`, `reconcile`, …). A guide calling a nonexistent one-word verb
    is invisible to it. That is a THIRD structural blind spot in that gate, of the
    same family as the two already recorded, and it is reported, not patched here
    (widening the discovery rule to bare identifiers would sweep in every English
    word followed by a paren — a separate design problem)."""
    found: set[str] = set()
    for name in names:
        start = 0
        while (i := text.find(name, start)) >= 0:
            start = i + 1
            if i and text[i - 1] in _IDENT_CHARS:
                continue           # `xremember(` is not `remember(`
            j = i + len(name)
            if j < len(text) and text[j] == "(":
                found.add(name)    # `record_step_result(` never matches `record_step`
                break
    return found


def retired_call_sites() -> dict[str, list[str]]:
    """retired_verb -> ["file:line", …] for every CALL FORM of a W6.4-retired
    verb still standing in the live shell-facing corpus."""
    offenders: dict[str, list[str]] = {}
    for path in live_shell_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1):
            for name in calls_of(line, RETIRED_VERBS):
                offenders.setdefault(name, []).append(f"{rel}:{lineno}")
    return offenders


def test_no_live_guide_calls_a_retired_verb():
    """W6.4 ATOMICITY, enforced. Retiring a verb from the toolsets while a guide
    still INSTRUCTS it recreates the planner-CRUD regression class (d14): under
    EDP_ROLE_SCOPE=enforce the role is handed an instruction it is refused from
    following. The toolset half and the guide half are ONE change, and this is
    what holds them together afterwards."""
    offenders = retired_call_sites()
    assert not offenders, (
        "live guide(s) CALL a verb W6.4 RETIRED from every role toolset. Under "
        "enforce that call is refused and the guide cannot be followed. Rewrite "
        "the call to the verb's successor (get_specialist_docs / "
        "emit_recipe_event(kind='learning') / resolve_spec_learnings / add_step "
        "+ record_step_result / record_context(kind=…)):\n" + "\n".join(
            f"  {name}(...) at {', '.join(sites)}"
            for name, sites in sorted(offenders.items())))


def test_the_retired_gate_is_not_vacuous():
    """A gate over an empty or already-satisfied candidate set proves nothing.
    Pin that the set is real, non-trivial, DERIVED from roles.py (never
    re-spelled — a hand-copied list is a list that drifts), and that each name is
    a name with a defined retirement story. v7 P0 DEREGISTERED the retired
    classes outright (break-and-migrate), so a stale guide call of one now
    ALSO trips the unregistered-tool gate above — this gate remains the one
    that names the retirement rather than a generic unknown-tool failure."""
    assert len(RETIRED_VERBS) >= 8, sorted(RETIRED_VERBS)
    assert {"remember", "record_decision", "get_specialist_doc",
            "propose_spec_learning", "resolve_spec_learning",
            "record_step"} <= RETIRED_VERBS
    # v7 P0: deregistered — a retired verb resolves nowhere
    assert RETIRED_VERBS.isdisjoint(_all_tool_names())
    # and absent from every scoped surface => a call form really is unfollowable
    for role, toolset in ROLE_TOOLSETS.items():
        assert RETIRED_VERBS.isdisjoint(toolset), role


def test_the_retired_gate_discriminates_the_shapes_that_forced_its_design():
    """The two shapes that make a NAME-based gate unshippable, pinned so nobody
    "simplifies" this into a substring scan and then allowlists the fallout."""
    # 1. `remember` is an English word. Prose is not a call (d64) — but the CALL
    #    form must still be caught. THE UNDERSCORE TRAP: `snake_call_forms` cannot
    #    see `remember(` at all (it requires "_" in the identifier), which is why
    #    `calls_of` exists. Both halves pinned, or the gate silently goes vacuous.
    assert calls_of(
        "You never have to remember to re-ground after a compaction.",
        RETIRED_VERBS) == set()
    assert calls_of("remember(fact=…, domain=…)", RETIRED_VERBS) == {"remember"}
    assert snake_call_forms("remember(fact=…)") == set(), (
        "if this ever starts finding `remember`, snake_call_forms' underscore "
        "rule changed — re-check whether calls_of is still needed, and whether "
        "the unregistered-tool gate just widened to bare English words")
    assert calls_of("xremember(a)", RETIRED_VERBS) == set()   # boundary holds
    # 2. `record_step_result(` is a LIVE tool, not a call of retired `record_step`.
    assert "record_step_result" not in RETIRED_VERBS
    assert calls_of("record_step_result(recipe_id, step_id, result)",
                    RETIRED_VERBS) == set()
    assert calls_of("record_step(recipe_id, step)", RETIRED_VERBS) == {"record_step"}
    # 3. the plural successors are not calls of the singulars they retired
    assert calls_of("get_specialist_docs(spec_ids=[…])", RETIRED_VERBS) == set()
    assert calls_of("get_specialist_doc(spec_id=…)", RETIRED_VERBS) == {
        "get_specialist_doc"}
    assert calls_of("resolve_spec_learnings(spec_id=…, accept=[…])",
                    RETIRED_VERBS) == set()
    assert calls_of("resolve_spec_learning(spec_id=…)", RETIRED_VERBS) == {
        "resolve_spec_learning"}


# ════════════════════════════════════════════════════════════════════════
# NON-VACUITY — the discriminator, proved on the real shapes
# ════════════════════════════════════════════════════════════════════════
def test_call_form_discriminator_rejects_mentions_and_prose_parentheticals():
    """Every exclusion above is a decision that could hide a real defect, so
    each is pinned on the exact text that motivated it. Without these, the gate
    could be silently loosened to green."""
    # a CALL is a call — the shape the gate must catch
    assert snake_call_forms("`pattern_observer_analyze(...)` is your main") == {
        "pattern_observer_analyze"}
    # a backticked MENTION is not (d64: prose is not a defect)
    assert snake_call_forms("- `invoke_skill` — run the named skill") == set()
    # a prose parenthetical is not a call (the four real false positives)
    assert snake_call_forms("your plan_id (`<recipe_id>-<step_id>`,") == set()
    assert snake_call_forms("For each option in plan_options (or for") == set()
    # private identifiers quoted from source are not MCP tools
    assert snake_call_forms("(`def _w(self, *a, **kw): return _orig(self)`)") == set()
    # an identifier that merely CONTAINS a tool name is not that tool
    assert snake_call_forms("xcheck_inbox(") == {"xcheck_inbox"}
    assert snake_call_forms("check_inbox(") == {"check_inbox"}
    # a dotted receiver is a boundary: rx.broker(...) is `broker`, not `rx.broker`
    assert snake_call_forms('rx.recipe_events(recipe_id)') == {"recipe_events"}


def test_the_rx_dsl_vocabulary_is_derived_from_source_not_hand_listed():
    """If this were a hand-kept list it would drift from `compile_spec`, and a
    typo'd operator in a guide would read as a missing tool (or worse, a new
    operator would read as a defect and get "fixed" out of a guide)."""
    rx = _rx_dsl_names()
    assert {"recipe_events", "switch_map", "take_until", "combine_latest",
            "fork_join", "distinct_until_changed", "with_latest_from",
            "buffer_ms", "debounce_ms", "sample_ms", "timeout_ms"} <= rx
    # it is a vocabulary of NON-tools; no rx operator shadows a real MCP verb
    assert rx.isdisjoint(_all_tool_names())


def test_the_non_tool_allowlist_is_small_reasoned_and_live():
    """A bare allowlist becomes a dumping ground (test_w4_roles' own lesson).
    Every entry carries a reason AND must still appear in the corpus — a stale
    entry silently widens the gate."""
    assert len(NON_TOOL_CALL_FORMS) <= 3, (
        "this allowlist is growing; each entry blinds the gate to one name")
    corpus = "\n".join(p.read_text(encoding="utf-8") for p in live_shell_files())
    present = snake_call_forms(corpus)
    for name, reason in NON_TOOL_CALL_FORMS.items():
        assert len(reason) > 40, f"{name} needs a real reason, got {reason!r}"
        assert name in present, (
            f"{name!r} is allowlisted but no longer appears in the corpus — "
            "remove it so the gate stays as narrow as its evidence")


def test_the_gate_sees_a_real_registry_not_an_empty_one():
    """A silently-empty registry would make the gate pass vacuously by flagging
    nothing as allowed… and then fail loudly. The inverse — an empty CORPUS —
    would make it pass while looking at nothing. Pin both."""
    assert len(_all_tool_names()) > 50, "tool registry parsed as near-empty"
    files = live_shell_files()
    assert len(files) > 30, f"corpus parsed as near-empty: {len(files)} files"
    # and the corpus really does contain registered call forms to discriminate.
    # NOTE `pool_close_self` is deliberately NOT asserted: every guide writes it
    # as a bare mention ("`pool_close_self` — the pool reaps you"), never in call
    # form. Asserting it would pin a fact that is not true — the kind of
    # plausible-looking assertion this module exists to prevent.
    corpus = "\n".join(p.read_text(encoding="utf-8") for p in files)
    called = snake_call_forms(corpus)
    assert {"check_inbox", "read_object", "notify_above",
            "record_action_status"} <= called
    assert len(called & _all_tool_names()) > 40, (
        "the corpus should resolve dozens of REAL tool call forms; a near-zero "
        "count means the parser broke and the gate is looking at nothing")


# ════════════════════════════════════════════════════════════════════════
# d65 — A CATALOGUE ENTRY IS NOT A LOAD: the STRICT-SUPERSET property
#
# "No new gaps found" is never evidence that the corpus grew. When a derived
# EXCLUSION and a derived INCLUSION are computed over the same graph, widening
# reachability silently widens the exclusion too (s25/a4 shipped exactly that
# and caught it). So the relationship between THIS gate's corpus and
# test_w4_roles' is ASSERTED, not assumed.
# ════════════════════════════════════════════════════════════════════════
def _w4_role_attributed_guides() -> set[str]:
    scanned: set[str] = set()
    for role in ROLE_COMMAND_FILE:
        scanned |= {p.stem for p in _role_docs(role)}
    return scanned


def test_s26_corpus_is_a_strict_superset_of_the_w4_scanned_corpus():
    """d65. Everything the class-guard test looks at, this gate also looks at —
    and strictly more. If a future exclusion rule sweeps a guide OUT of a role's
    corpus, it stays inside this one, so the unregistered-tool gate cannot go
    blind as a side effect of a role-attribution change."""
    s26 = {p.stem for p in live_shell_files()}
    w4 = _w4_role_attributed_guides()

    assert w4 <= s26, sorted(w4 - s26)
    assert w4 < s26, "s26's corpus must be STRICTLY wider than the w4 walk"

    # …and the excess is exactly the docs the w4 walk cannot attribute to a role
    excess = s26 - w4
    assert set(_shared_guides()) <= excess, sorted(set(_shared_guides()) - excess)
    assert set(UNSCANNED_GUIDES) <= excess, sorted(set(UNSCANNED_GUIDES) - excess)


def test_every_guide_on_disk_is_inside_this_gate_however_it_is_classified():
    """The PARTITION, closed. A guide is role-attributed, shared, or declared
    unattributed — and in all three cases this gate reads it. There is no fourth
    bucket and no way to land in one that this gate does not scan."""
    on_disk = {p.stem for p in GUIDES_DIR.glob("*.md")}
    scanned_here = {p.stem for p in live_shell_files()}
    assert on_disk <= scanned_here, sorted(on_disk - scanned_here)

    # the three w4 buckets account for every guide — no unclassified remainder
    classified = (_w4_role_attributed_guides() | set(_shared_guides())
                  | set(UNSCANNED_GUIDES))
    assert on_disk <= classified, sorted(on_disk - classified)


def test_unscanned_guides_escape_role_attribution_but_not_this_gate():
    """THE TIGHTENING of the UNSCANNED_GUIDES escape hatch (s26/a2).

    Before: a future author could hide a gap by declaring a guide unattributed
    with a >30-char reason — it was then scanned by NOBODY, and its silence read
    as "no gaps".

    After: the declaration still buys exemption from ROLE attribution (a compiled
    specialist stack doc genuinely has no role, and framework-ocak.md's role is
    retired — that exemption is legitimate and is left alone). It no longer buys
    exemption from TOOL-NAME validation. A guide parked in UNSCANNED_GUIDES that
    calls a nonexistent verb fails `test_no_live_guide_calls_an_unregistered_tool`
    like any other."""
    scanned_here = {p.stem for p in live_shell_files()}
    for guide in UNSCANNED_GUIDES:
        assert guide in scanned_here, (
            f"{guide} is declared unattributed AND is outside this gate — the "
            "escape hatch is back")
    # the hatch is non-empty, so the guarantee above is not vacuous
    assert UNSCANNED_GUIDES
