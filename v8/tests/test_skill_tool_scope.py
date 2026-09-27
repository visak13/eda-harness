"""No skill, role card or guide tells a role to call a tool that role's bundle does not carry.

S20 trimmed each role's tool list (bundles._S20_UNUSED) but left skill and guide lines naming the
dropped tools (qa finding m-e1eeb1d29e). A seat following such a line hits unknown-tool. This test
reads every tool CALL written in those files — `name(` or a backticked `name` — and checks it against
tools_for_role for every role the line applies to:

- `.claude/commands/<role>.md` applies to that role;
- `.claude/skills/*/SKILL.md` and `guides/*.md` apply to every seat role (any seat can invoke any
  skill or fetch any guide), unless the file carries `<!-- roles: a, b -->`.

A line narrows itself with `(role/role only)` or `(not role/role)`. The same marker on a heading
scopes every line under it, up to the next heading. A method call (`f.close()`) is not a tool call, nor is a dotted action id
(`teammate.rotate_token`).
"""
from __future__ import annotations

import re
from pathlib import Path

from edp8.bundles import ALL_TOOLS, tools_for_role

V8 = Path(__file__).resolve().parents[1]
SEAT_ROLES = ("owner", "architect", "engineer", "qa", "sme", "adversary", "doctor")
_ALT = "|".join(sorted(ALL_TOOLS, key=len, reverse=True))
_CALL = re.compile(r"`(" + _ALT + r")\b(?!\.)[^`]*`|(?<![.\w])(" + _ALT + r")\(")
_ROLE = "|".join(SEAT_ROLES)
_ROLES = r"((?:" + _ROLE + r")(?:\s*/\s*(?:" + _ROLE + r"))*)"
_ONLY = re.compile(r"\(" + _ROLES + r" only\)")
_NOT = re.compile(r"\(not " + _ROLES + r"\)")
_FILE_SCOPE = re.compile(r"<!--\s*roles:\s*([a-z ,]+?)\s*-->")


def _cards() -> list[tuple[str, Path]]:
    """(role, card) for every role card, per-flow cards included (`engineer-quick.md` is the
    engineer role's quick-flow card, owner m-b13c61ddea). The owner is a human with no card."""
    return [(p.stem.split("-")[0], p) for p in sorted((V8 / ".claude" / "commands").glob("*.md"))
            if p.stem.split("-")[0] in SEAT_ROLES]


def _card_skills() -> dict[str, set[str]]:
    """skill name -> roles whose card lists it on the **SKILLS** line."""
    out: dict[str, set[str]] = {}
    for role, card in _cards():
        text = card.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.startswith("**SKILLS**"):
                for name in re.findall(r"/([a-z-]+)", line):
                    out.setdefault(name, set()).add(role)
    return out


#: S19: the read-only Help seat reads a skill only when its card lists it, and a guide only when the guide's
#: roles comment names it; an unscoped file speaks to the working roles
_READ_ONLY = {"doctor"}


def _scoped_files() -> list[tuple[Path, set[str]]]:
    files: list[tuple[Path, set[str]]] = []
    for role, card in _cards():
        files.append((card, {role}))
    listed = _card_skills()
    for p in sorted((V8 / ".claude" / "skills").glob("*/SKILL.md")) + sorted((V8 / "guides").glob("*.md")):
        m = _FILE_SCOPE.search(p.read_text(encoding="utf-8"))
        if m:
            roles = {r.strip() for r in m.group(1).split(",")}
        else:
            roles = set(SEAT_ROLES) - _READ_ONLY
            if p.name == "SKILL.md":
                roles |= _READ_ONLY & listed.get(p.parent.name, set())
        files.append((p, roles))
    return files


def _narrow(line: str, roles: set[str]) -> set[str]:
    if m := _ONLY.search(line):
        return {r.strip() for r in m.group(1).split("/")}
    if m := _NOT.search(line):
        return roles - {r.strip() for r in m.group(1).split("/")}
    return roles


def _violations() -> list[str]:
    have = {r: {t.name for t in tools_for_role(r)} for r in SEAT_ROLES}
    out = []
    for path, roles in _scoped_files():
        section = roles
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.startswith("#"):
                section = _narrow(line, roles)
            line_roles = _narrow(line, section)
            for tool in {a or b for a, b in _CALL.findall(line)}:
                missing = sorted(r for r in line_roles if tool not in have[r])
                if missing:
                    out.append(f"{path.relative_to(V8)}:{n}: `{tool}` is not in {missing}'s tools")
    return out


def test_no_skill_card_or_guide_names_a_tool_its_role_lacks():
    assert _violations() == []


def test_the_scan_sees_calls_scopes_and_role_limits():
    # The detector finds both call forms, and a line scope overrides the file scope.
    assert {a or b for a, b in _CALL.findall("`gates(epic)` then find(q)")} == {"gates", "find"}
    assert _narrow("`gates` (owner/architect/qa only)", set(SEAT_ROLES)) == {"owner", "architect", "qa"}
    # The three cases qa named (m-e1eeb1d29e) are real gaps in the bundles, so an unscoped line
    # naming them for those roles must be caught.
    have = {r: {t.name for t in tools_for_role(r)} for r in SEAT_ROLES}
    assert "artifact_create" not in have["qa"]
    assert "find" not in have["sme"]
    assert "gates" not in have["engineer"]
    # Every skill a card lists exists, so no skill silently falls out of the scan.
    for skill in _card_skills():
        assert (V8 / ".claude" / "skills" / skill / "SKILL.md").exists(), skill
    assert _narrow("`inbox()` (not owner)", set(SEAT_ROLES)) == set(SEAT_ROLES) - {"owner"}
    assert _CALL.findall("manual `f.close()` or x.close() calls") == []
