"""W11 doc-sync invariant: every surface that ENUMERATES role toolsets agrees
with `ROLE_TOOLSETS` about who holds `suspend_recipe` / `resume_recipe`.

WHY THIS IS A PROPERTY TEST AND NOT A GREP (s22/a5's durable lesson): "when an
invariant spans N surfaces, the acceptance verify must ENUMERATE the N surfaces,
not spot-check one. A doc-sync invariant with a single-file grep as its gate will
pass while broken." W5/a3's `findstr consult` over 2 of 4 files reported PASS
while the push plane was silently dead. So the surfaces live in a module-level
table below, and a surface that legitimately does NOT enumerate toolsets is an
EXPLICIT skip carrying its reason — visibly considered, not forgotten.

`ROLE_TOOLSETS` (the code) is the sole source of truth. Role lists are never
hand-copied here; they are read from the table, so a role added in code cannot
silently escape this gate.

SCOPE — the sibling axis belongs to a6. `tests/test_w4_roles.py` asserts
GUIDES -> TOOLSETS ("every tool a role's own guides instruct it to CALL is in
that role's toolset"), with its own corpus scan and call-form discriminator.
This file asserts the opposite direction, DOCS -> ROLE_TOOLSETS ("every surface
that ENUMERATES a role's toolset agrees with the code"). Deliberately NO second
guide-corpus tool scan lives here: a rival scanner with a different
discriminator would contradict a6's.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from edp_claude.tools.roles import ROLE_TOOLSETS

# tests/test_w11_docs_sync.py -> parents[1] == the repo root.
REPO_ROOT = Path(__file__).resolve().parents[1]

# The two verbs W11 added. Both are neuron-only; `_NEURON` is DERIVED
# (`_ALL_TOOL_NAMES - SPECIALIST_ONLY - _CONSOLIDATED_OUT`), so this holds by
# construction in code — the drift risk is entirely in prose.
W11_VERBS = ("suspend_recipe", "resume_recipe")
OWNING_ROLE = "neuron"

# The launcher protocol. Transcripts live under `CLAUDE_CONFIG_DIR`, which only
# the launcher pins, so the BARE form silently finds nothing and the user cannot
# diagnose why. `_launcher_for_config_dir` derives the launcher from the config
# dir the capture hook recorded; `claude-personal` is the concrete example.
LAUNCHER_RESUME = "claude-personal --resume"
BARE_RESUME = "claude --resume"

# The from-anywhere wrapper the design doc once named. It does not exist in this
# repo; the docs note it as ABSENT rather than inventing it.
ABSENT_WRAPPER = "eda.bat"

# The `/neuron resume <recipe_id>` activation — W11's first entry point.
NEURON_COMMAND = ".claude/commands/neuron.md"
RESUME_ACTIVATION = "/neuron resume <recipe_id>"


@dataclass(frozen=True)
class Surface:
    """A doc that a reader could take as authority on who holds a tool.

    `enumerates` = it lists a role's toolset, so it MUST name both W11 verbs and
    attribute them to the neuron. Otherwise `reason` records WHY it is exempt —
    an exempt surface must still exist, because a skip pointing at a renamed or
    deleted file is a silent hole in the enumeration, and that is how a table
    like this rots.
    """
    path: str
    enumerates: bool
    reason: str = ""

    def __post_init__(self) -> None:
        if self.enumerates == bool(self.reason):
            raise ValueError(
                f"{self.path}: a surface either enumerates toolsets or carries "
                "a skip reason — never both, never neither"
            )

    def text(self) -> str:
        return (REPO_ROOT / self.path).read_text(encoding="utf-8")


SURFACES: tuple[Surface, ...] = (
    # ── enumerating: these three tell a reader which tools the neuron holds ──
    Surface(NEURON_COMMAND, enumerates=True),
    Surface("docs/guides/neuron-protocol-reference.md", enumerates=True),
    Surface("docs/design/v6-audit/role-toolsets-derived.md", enumerates=True),

    # ── considered and exempt: none of these enumerate a ROLE's toolset ──
    Surface(
        "docs/guides/architecture-vocabulary.md", enumerates=False,
        reason="Enumerates per-OBJECT ops (recipe/plan/action/... x read/query/"
               "create/update/delete), not per-ROLE toolsets. suspend/resume are "
               "recipe-lifecycle verbs, not object-CRUD ops, so they belong to no "
               "row of that table.",
    ),
    Surface(
        "docs/guides/loop-and-heartbeat.md", enumerates=False,
        reason="The cadence contract. Its 'Role scope' section enumerates the LOOP "
               "verbs (reconcile/next_action) and per-role observe kind-sets — not "
               "role toolsets. resume_recipe's rewire hand-back is documented in "
               "neuron-protocol-reference.md, which is the neuron ops surface.",
    ),
    Surface(
        "docs/guides/reactive-streams-reference.md", enumerates=False,
        reason="rx vocabulary (sources/operators/combinators) and the observe->act "
               "response table. Names no MCP tools and no role toolset.",
    ),
)

ENUMERATING = tuple(s for s in SURFACES if s.enumerates)
EXEMPT = tuple(s for s in SURFACES if not s.enumerates)

# Where each role in ROLE_TOOLSETS states its own contract. Keys are checked
# against ROLE_TOOLSETS below, so a NEW role cannot slip past this gate unmapped.
ROLE_COMMAND_FILES: dict[str, str] = {
    "neuron": NEURON_COMMAND,
    "planner": ".claude/commands/agentic-plan.md",
    "worker": ".claude/commands/worker.md",
    "reviewer": ".claude/commands/reviewer.md",
    "specialist": ".claude/commands/specialist.md",
    # ("consult" row deleted 2026-08-12 with its retired shell role + card.)
    # s25/a4: keyed by the UNDERSCORE string http_pool.py stamps as EDP_ROLE —
    # NOT by the hyphenated activator/filename. goal_keeper / pattern_observer
    # rows deleted with their DEAD roles (owner ruling 2026-08-04).
    "curiosity": ".claude/commands/curiosity.md",
}

# ── command files that are NOT keyed by ROLE_TOOLSETS (a9 review finding) ───
# Keying the corpus off ROLE_TOOLSETS covered only 6 of the 11 files actually in
# .claude/commands/. The other five are real shell briefs with no code toolset
# entry, so `set(ROLE_COMMAND_FILES) == set(ROLE_TOOLSETS)` could not see them:
# a verb leaked into curiosity.md left this suite GREEN (verified by mutation).
# That is the same enumerate-2-of-4 defect this file exists to prevent.
#
# The corpus is therefore taken from the FILESYSTEM and every file must be
# dispositioned — keyed to a role, or exempt WITH a reason. Exempt files are
# still checked for the neuron-only verbs, because "no ROLE_TOOLSETS entry"
# means `toolset_for_role` returns None and mcp_server.py fails OPEN (full
# registry, W4 fallback) — an over-grant, not a refusal. Their briefs are the
# only thing standing between those shells and a neuron-only verb.
#
# s25/a4 CLOSED the curiosity / goal-keeper / pattern-observer mismatch: all
# three now have ROLE_TOOLSETS rows (keyed by the underscore EDP_ROLE strings),
# so they moved OUT of this exempt table and INTO ROLE_COMMAND_FILES above. They
# no longer fail open, and their briefs are no longer the only thing standing
# between those shells and a neuron-only verb.
NON_ROLE_COMMAND_FILES: dict[str, str] = {
    # goal-keeper-check.md deleted with its dead role (owner ruling 2026-08-04).
    # ocak.md — the DESIGN-v5 P1 retirement tombstone — was deleted outright in
    # the 2026-08-12 dead-surface sweep (the comprehension flow it pointed at is
    # tool-forced; the run_ocak_audit / record_audit_verdict TOOLS are live).
}


def _command_files_on_disk() -> set[str]:
    return {p.name for p in (REPO_ROOT / ".claude" / "commands").glob("*.md")}


def _code_blocks(text: str) -> list[str]:
    """The fenced ``` blocks — i.e. what a reader is told to RUN or CALL.

    Prose may discuss a command in order to warn against it; a fenced block is a
    recommendation. The distinction is what lets a doc say "there is no eda.bat"
    without that sentence tripping the very gate that keeps it honest.
    """
    blocks: list[str] = []
    current: list[str] | None = None
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            if current is None:
                current = []
            else:
                blocks.append("\n".join(current))
                current = None
        elif current is not None:
            current.append(line)
    return blocks


def _sections(text: str) -> dict[str, str]:
    """`## Heading` -> body, for the role-keyed inventory doc."""
    sections: dict[str, str] = {}
    heading: str | None = None
    body: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if heading is not None:
                sections[heading] = "\n".join(body)
            heading = line[3:].strip()
            body = []
        elif heading is not None:
            body.append(line)
    if heading is not None:
        sections[heading] = "\n".join(body)
    return sections


# ── the code is the source of truth ────────────────────────────────────────
@pytest.mark.parametrize("verb", W11_VERBS)
def test_role_toolsets_grants_each_w11_verb_to_the_neuron_alone(verb: str) -> None:
    holders = {role for role, tools in ROLE_TOOLSETS.items() if verb in tools}
    assert holders == {OWNING_ROLE}, (
        f"{verb} must be neuron-only (d17); ROLE_TOOLSETS grants it to {holders}"
    )


# ── every enumerating surface agrees with the code ─────────────────────────
@pytest.mark.parametrize("surface", ENUMERATING, ids=lambda s: s.path)
@pytest.mark.parametrize("verb", W11_VERBS)
def test_every_enumerating_surface_names_both_w11_verbs(
    surface: Surface, verb: str
) -> None:
    assert verb in surface.text(), (
        f"{surface.path} enumerates the neuron's tools but never names {verb}. "
        "A shell activated off this surface would not know the verb exists."
    )


@pytest.mark.parametrize("verb", W11_VERBS)
def test_the_derived_inventory_files_each_verb_under_neuron_only(verb: str) -> None:
    """Stronger than "the token appears somewhere": it must appear under the
    NEURON heading and under no other role's."""
    sections = _sections(
        (REPO_ROOT / "docs/design/v6-audit/role-toolsets-derived.md")
        .read_text(encoding="utf-8")
    )
    assert verb in sections["NEURON"], f"{verb} missing from the NEURON inventory"
    misattributed = [
        heading for heading, body in sections.items()
        if heading != "NEURON" and verb in body
    ]
    assert not misattributed, (
        f"{verb} is neuron-only but the inventory lists it under {misattributed}"
    )


@pytest.mark.parametrize(
    "role", sorted(r for r in ROLE_COMMAND_FILES if r != OWNING_ROLE)
)
@pytest.mark.parametrize("verb", W11_VERBS)
def test_no_non_neuron_role_file_grants_the_w11_verbs(role: str, verb: str) -> None:
    text = (REPO_ROOT / ROLE_COMMAND_FILES[role]).read_text(encoding="utf-8")
    assert verb not in text, (
        f"{ROLE_COMMAND_FILES[role]} names {verb}, but ROLE_TOOLSETS[{role!r}] "
        f"does not hold it — the {role} would call a tool it cannot reach."
    )


def test_role_command_files_cover_every_role_in_role_toolsets() -> None:
    """A role added to the code must be mapped here, or it escapes the gate."""
    assert set(ROLE_COMMAND_FILES) == set(ROLE_TOOLSETS)


def test_every_command_file_on_disk_is_dispositioned() -> None:
    """The corpus comes from the FILESYSTEM, not from ROLE_TOOLSETS.

    A command file added to disk with no code toolset entry would otherwise be
    invisible to every assertion in this module. Exact equality, so a new file
    must be keyed to a role or exempted with a reason — never silently ignored.
    """
    keyed = {Path(p).name for p in ROLE_COMMAND_FILES.values()}
    assert keyed | set(NON_ROLE_COMMAND_FILES) == _command_files_on_disk()


@pytest.mark.parametrize("filename", sorted(NON_ROLE_COMMAND_FILES))
def test_non_role_command_files_carry_a_reason(filename: str) -> None:
    assert NON_ROLE_COMMAND_FILES[filename].strip(), (
        f"{filename}: exemption without a reason"
    )


@pytest.mark.parametrize(
    ("enumerates", "reason"), [(True, "a reason"), (False, "")]
)
def test_a_surface_is_enumerating_xor_reasoned(
    enumerates: bool, reason: str
) -> None:
    """The table's own invariant, pinned. `__post_init__` enforces it at import
    today — a malformed row fails collection — but nothing stops a future edit
    from softening that raise to a warning, at which point a surface could be
    both or neither and the skip list would start rotting silently.
    """
    with pytest.raises(ValueError):
        Surface("docs/guides/loop-and-heartbeat.md", enumerates, reason)


@pytest.mark.parametrize("filename", sorted(NON_ROLE_COMMAND_FILES))
@pytest.mark.parametrize("verb", W11_VERBS)
def test_no_unkeyed_command_file_grants_the_w11_verbs(
    filename: str, verb: str
) -> None:
    """These shells hold no ROLE_TOOLSETS entry, so the MCP server registers the
    FULL registry for them (fail-open, mcp_server.py:144). Nothing but this
    assertion stops their brief from instructing a neuron-only verb.
    """
    text = (REPO_ROOT / ".claude" / "commands" / filename).read_text(
        encoding="utf-8"
    )
    assert verb not in text, (
        f".claude/commands/{filename} names {verb}, which is neuron-only. That "
        f"shell has no ROLE_TOOLSETS entry, so the tool IS registered for it "
        f"(W4 fail-open) and the call would succeed."
    )


# ── the exemptions stay honest ─────────────────────────────────────────────
@pytest.mark.parametrize("surface", EXEMPT, ids=lambda s: s.path)
def test_exempt_surfaces_carry_a_reason_and_still_exist(surface: Surface) -> None:
    assert surface.reason.strip(), f"{surface.path}: exemption without a reason"
    assert (REPO_ROOT / surface.path).is_file(), (
        f"{surface.path} is exempted from the W11 doc-sync gate but no longer "
        "exists. Re-check whether its successor enumerates role toolsets — a "
        "skip pointing at a deleted file is a silent hole in this enumeration."
    )


@pytest.mark.parametrize("surface", ENUMERATING, ids=lambda s: s.path)
def test_enumerating_surfaces_exist(surface: Surface) -> None:
    assert (REPO_ROOT / surface.path).is_file()


# ── W11's two entry points, as a human meets them ──────────────────────────
def test_neuron_command_documents_the_resume_activation() -> None:
    text = (REPO_ROOT / NEURON_COMMAND).read_text(encoding="utf-8")
    assert RESUME_ACTIVATION in text, (
        f"{NEURON_COMMAND} must document `{RESUME_ACTIVATION}` — W11's first "
        "entry point, and the only one that works in a fresh shell."
    )
    assert "resume_recipe" in text


@pytest.mark.parametrize("surface", ENUMERATING, ids=lambda s: s.path)
def test_no_surface_recommends_the_bare_resume_command(surface: Surface) -> None:
    """The bare launcher reads the DEFAULT config dir, finds no transcript for a
    `claude-personal` session, and fails in a way the user cannot diagnose."""
    for block in _code_blocks(surface.text()):
        assert BARE_RESUME not in block, (
            f"{surface.path} shows `{BARE_RESUME}` as a command to run; "
            f"transcripts live under CLAUDE_CONFIG_DIR — use `{LAUNCHER_RESUME}`."
        )


def test_the_resume_command_is_documented_through_its_launcher() -> None:
    for path in (NEURON_COMMAND, "docs/guides/neuron-protocol-reference.md"):
        text = (REPO_ROOT / path).read_text(encoding="utf-8")
        assert LAUNCHER_RESUME in text, (
            f"{path} must show the session-resume command as "
            f"`{LAUNCHER_RESUME} <neuron_session_id>`."
        )


# ── the wrapper we were told not to invent ─────────────────────────────────
def test_the_absent_wrapper_is_never_presented_as_a_runnable_command() -> None:
    """`eda.bat` does not exist here. Prose may say so; no doc may tell a user to
    run it. If someone adds the wrapper, this test fails and the docs get their
    say — which is the point."""
    existing = [
        p for p in REPO_ROOT.rglob(ABSENT_WRAPPER)
        if ".backup" not in p.parts and ".reset-backups-20260530-175552" not in p.parts
    ]
    assert not existing, (
        f"{ABSENT_WRAPPER} now exists at {existing} — the docs call it absent. "
        "Update them, then teach this test the new truth."
    )
    for surface in ENUMERATING:
        for block in _code_blocks(surface.text()):
            assert ABSENT_WRAPPER not in block, (
                f"{surface.path} shows `{ABSENT_WRAPPER}` as a command, but no "
                "such wrapper exists in this repo."
            )
