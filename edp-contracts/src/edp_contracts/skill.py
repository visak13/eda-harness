"""The Skill contract — skills are markdown; their contract is structural.

A skill file is a Claude-Code-style markdown body with a ``---`` fenced
front-matter header. We validate the header shape and a few body rules so a
skill cannot ship that (a) lacks a declared contract, (b) calls a record_*
tool it did not declare, or (c) forgets its self-unload discipline.

Dependency note (flagged in base-contracts-REFACTOR.md): skill headers use
YAML front-matter to stay Claude-Code-readable, but edp-contracts is
pydantic+stdlib only (no PyYAML). We therefore parse a *strict, documented
subset* of YAML sufficient for :class:`SkillHeader` — flat scalars, inline
``[a, b]`` lists, and exactly one level of nested mapping (``inputs`` /
``outputs``). Anything outside that subset is a parse violation, by design.
"""

import re
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

ALLOWED_HOSTS: frozenset[str] = frozenset({"neuron", "planner", "worker", "fsm"})

#: Sentinels that satisfy R3 (an explicit self-unload instruction in body).
_UNLOAD_SENTINELS: tuple[str, ...] = ("unload", "end skill")


class SkillRule(StrEnum):
    """The structural rules validate_skill enforces (S3b refactor: these
    were scattered "R1".."R5" string literals — an enum earns its keep for
    type-safe references in Violation.rule and tests)."""

    R1 = "R1"  # front-matter present and parses as SkillHeader
    R2 = "R2"  # every record_* in body declared in outputs.via
    R3 = "R3"  # body carries a literal unload instruction
    R4 = "R4"  # hosts subset of ALLOWED_HOSTS
    R5 = "R5"  # no spawn_* in a worker-hosted skill

_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)
_RECORD_CALL_RE = re.compile(r"\b(record_[a-z_]+)\s*\(")
_SPAWN_CALL_RE = re.compile(r"\b(pool\.spawn_[a-z_]+|spawn_[a-z_]+)\s*\(")
_INLINE_LIST_RE = re.compile(r"^\[(.*)\]$")


class SkillIO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    writes: list[str] = Field(default_factory=list)  # artifact dot-paths
    via: list[str] = Field(default_factory=list)  # record_* tools allowed


class SkillHeader(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill: str = Field(min_length=1)
    hosts: list[str] = Field(min_length=1)
    inputs: dict[str, str] = Field(default_factory=dict)
    outputs: SkillIO
    unload: str = Field(min_length=1)


class Violation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    rule: SkillRule
    detail: str


def _strip_scalar(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] in "\"'" and raw[-1] == raw[0]:
        return raw[1:-1]
    return raw


def _parse_inline_list(raw: str) -> list[str]:
    m = _INLINE_LIST_RE.match(raw.strip())
    if not m:
        return []
    inner = m.group(1).strip()
    if not inner:
        return []
    return [_strip_scalar(p) for p in inner.split(",")]


def parse_skill_header(md_text: str) -> tuple[SkillHeader | None, str, str]:
    """Split front-matter from body and parse the supported YAML subset.

    Returns ``(header | None, body, parse_error)``. ``header`` is None when
    the subset parser or schema validation fails; ``parse_error`` then holds
    a human-readable reason (empty when ok).
    """
    m = _FRONT_MATTER_RE.match(md_text)
    if not m:
        return None, md_text, "no '---' fenced front-matter at top of file"
    raw_header, body = m.group(1), m.group(2)

    data: dict = {}
    current_key: str | None = None  # active nested mapping (inputs/outputs)
    for lineno, line in enumerate(raw_header.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indented = line[0] in (" ", "\t")
        key_part, sep, val_part = line.strip().partition(":")
        if not sep:
            return None, body, f"line {lineno}: expected 'key: value'"
        key = key_part.strip()
        val = val_part.strip()

        if not indented:
            current_key = None
            if val == "":
                # opens a nested mapping (inputs:/outputs:)
                data[key] = {}
                current_key = key
            elif val.startswith("["):
                data[key] = _parse_inline_list(val)
            else:
                data[key] = _strip_scalar(val)
        else:
            if current_key is None or not isinstance(
                data.get(current_key), dict
            ):
                return None, body, (
                    f"line {lineno}: indented entry with no open mapping"
                )
            if val.startswith("["):
                data[current_key][key] = _parse_inline_list(val)
            else:
                data[current_key][key] = _strip_scalar(val)

    try:
        header = SkillHeader.model_validate(data)
    except ValidationError as exc:
        return None, body, _fmt_validation(exc)
    return header, body, ""


def _fmt_validation(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
        for e in exc.errors()
    )


def validate_skill(path: str) -> list[Violation]:
    """Validate a skill file. Returns ``[]`` when clean.

    Rules:
      R1  front-matter present and parses as SkillHeader
      R2  every record_* token in the body is declared in outputs.via
      R3  the body contains a literal unload instruction
      R4  hosts is a subset of ALLOWED_HOSTS
      R5  no spawn_* call in a skill whose host set includes 'worker'
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    header, body, parse_err = parse_skill_header(text)

    if header is None:
        return [Violation(path=path, rule=SkillRule.R1, detail=parse_err)]

    out: list[Violation] = []

    # R4 — host allow-list
    bad_hosts = sorted(set(header.hosts) - ALLOWED_HOSTS)
    if bad_hosts:
        out.append(
            Violation(
                path=path,
                rule=SkillRule.R4,
                detail=f"hosts not allowed: {bad_hosts}; "
                f"allowed={sorted(ALLOWED_HOSTS)}",
            )
        )

    # R2 — record_* calls must be declared in outputs.via
    declared = set(header.outputs.via)
    used = set(_RECORD_CALL_RE.findall(body))
    undeclared = sorted(used - declared)
    if undeclared:
        out.append(
            Violation(
                path=path,
                rule=SkillRule.R2,
                detail=f"body calls undeclared record tools: {undeclared}; "
                f"declared via={sorted(declared)}",
            )
        )

    # R3 — body must carry an explicit unload instruction
    body_lower = body.lower()
    if not any(s in body_lower for s in _UNLOAD_SENTINELS):
        out.append(
            Violation(
                path=path,
                rule=SkillRule.R3,
                detail="body has no literal unload instruction "
                f"(one of {list(_UNLOAD_SENTINELS)})",
            )
        )

    # R5 — worker-hosted skills must not spawn
    if "worker" in header.hosts and _SPAWN_CALL_RE.search(body):
        out.append(
            Violation(
                path=path,
                rule=SkillRule.R5,
                detail="worker-hosted skill calls a spawn_* tool; "
                "workers do not spawn",
            )
        )

    return out
