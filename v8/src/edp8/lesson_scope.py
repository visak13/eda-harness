"""Lesson scope (e0cec S6, design-b6a55eed13 §4.C): which epic a lesson may reach, the backfill that
classifies lessons recorded before scope existed, and the retired-tool rule.

An epic's project is its `project:<key>` tag; no tag means a framework epic (every epic that predates the tag
is Heronry's own work). A framework lesson reaches framework epics only; a project lesson reaches epics of the
same project. `visible` is the ONE gate: knowledge.py calls it on every lesson path (seed leg, dense pool,
domain extras, graph walk), so recall in context() and lookup's "Lessons from elsewhere" cannot disagree.
"""

from __future__ import annotations

import re
from typing import Any

from edp_contracts.roles import RETIRED_ROLES

from .schemas import LessonScope, LessonStatus

FRAMEWORK = "framework"
PROJECT_TAG = "project:"

# A lesson whose subject is a deleted tool (the consult lane, a removed role's seat) can only mislead a seat.
RETIRED_TOOL = re.compile(
    r"\bconsult(?:_status|\.py)\b"
    r"|\b(?:a|the|codex|qa|raw)\s+consult\b"
    r"|\bconsult\s+(?:run|runs|lane|boundary|fence|note|answer|with|running|shell|receipt)\b"
    r"|\b(?:" + "|".join(sorted(RETIRED_ROLES)) + r")\s+(?:seat|role|card|bundle)\b",
    re.I)
RETIRED_DOMAINS = {"consult"}

# domain -> project key, the fallback when a lesson's creating epic carries no project tag.
DOMAIN_PROJECTS = {"blender": "blender", "blender-craft": "blender", "geometry": "blender",
                   "career-search": "career-search", "creative-concepts": "creative-concepts",
                   "video": "creative-concepts", "visualization": "atlas"}
_FRAMEWORK_REPOS = {"eda-base3", "learning", "heronry"}
_PROJECT_PATH = re.compile(r"[A-Za-z]:[\\/]+Projects[\\/]+([\w.\-]+)")
_CREATOR_ID = re.compile(r"((?:epic|s|t)-[0-9a-f]{6,})$")


def project_key(value: str) -> str:
    return re.sub(r"[^a-z0-9._\-]+", "-", (value or "").strip().lower()).strip("-")


def epic_project(store: Any, scope_id: str | None) -> str:
    """The project of the epic a scope (epic|ticket id) belongs to: its `project:<key>` tag, else framework."""
    from . import knowledge  # local: knowledge imports this module
    epic_id = knowledge._epic_id_of(store, scope_id) if scope_id else None
    epic = store.get("ticket", epic_id) if epic_id else None
    for tag in (getattr(epic, "tags", None) or []):
        if tag.startswith(PROJECT_TAG) and project_key(tag[len(PROJECT_TAG):]):
            return project_key(tag[len(PROJECT_TAG):])
    return FRAMEWORK


def is_framework(project: str) -> bool:
    return not project or project == FRAMEWORK


def visible(store: Any, lesson: Any, epic_id: str | None) -> bool:
    """May this lesson reach this epic? An unresolved epic (None) is treated as a framework epic."""
    project = epic_project(store, epic_id) if epic_id else FRAMEWORK
    if getattr(lesson, "scope_kind", LessonScope.framework) == LessonScope.project:
        return bool(lesson.project) and lesson.project == project
    return is_framework(project)


def targets(store: Any, epic_id: str | None) -> tuple[str, Any]:
    """(the epic's project, a predicate for lessons it may see), resolved once for a loop over lessons."""
    project = epic_project(store, epic_id) if epic_id else FRAMEWORK

    def ok(lesson: Any) -> bool:
        if getattr(lesson, "scope_kind", LessonScope.framework) == LessonScope.project:
            return bool(lesson.project) and lesson.project == project
        return is_framework(project)
    return project, ok


def default_scope(store: Any, *, ticket_id: str | None = None, evidence: list[str] | None = None) -> tuple[str, str]:
    """(scope_kind, project) for a lesson recorded without one: from its ticket's epic, else from the first
    evidence id that names a ticket, else framework."""
    for sid in [ticket_id, *(evidence or [])]:
        if sid and store.get("ticket", sid) is not None:
            proj = epic_project(store, sid)
            return (LessonScope.framework.value, "") if is_framework(proj) else (LessonScope.project.value, proj)
    return LessonScope.framework.value, ""


def cites_retired_tool(lesson: Any) -> bool:
    if (lesson.domain or "").strip().lower() in RETIRED_DOMAINS:
        return True
    return bool(RETIRED_TOOL.search(f"{lesson.topic}\n{lesson.text}"))


def _creator_scope(lesson: Any) -> str | None:
    m = _CREATOR_ID.search(lesson.created_by or "")
    return m.group(1) if m else None


def classify(store: Any, lesson: Any) -> dict[str, str]:
    """One lesson -> {action: retire|scope, scope_kind, project, why}. Rules, first match wins:
    retired tool; board-authored (pain-derived) is framework; the creating seat's epic or an evidence ticket's
    epic with a project tag; a `\\Projects\\<repo>` path in the evidence; a project-domain hint; else framework."""
    if cites_retired_tool(lesson):
        return {"action": "retire", "scope_kind": lesson.scope_kind.value, "project": lesson.project,
                "why": "cites a retired tool (consult or a removed role's seat)"}
    fw = {"action": "scope", "scope_kind": LessonScope.framework.value, "project": ""}
    if lesson.created_by == "board":
        return {**fw, "why": "pain-derived"}
    for sid in [_creator_scope(lesson), *(lesson.evidence or [])]:
        if sid and store.get("ticket", sid) is not None:
            proj = epic_project(store, sid)
            if not is_framework(proj):
                return {"action": "scope", "scope_kind": LessonScope.project.value, "project": proj,
                        "why": f"epic of {sid} carries project:{proj}"}
    for ev in lesson.evidence or []:
        m = _PROJECT_PATH.search(ev or "")
        if m and m.group(1).lower() not in _FRAMEWORK_REPOS:
            return {"action": "scope", "scope_kind": LessonScope.project.value, "project": project_key(m.group(1)),
                    "why": f"evidence path under Projects\\{m.group(1)}"}
    hint = DOMAIN_PROJECTS.get((lesson.domain or "").strip().lower())
    if hint:
        return {"action": "scope", "scope_kind": LessonScope.project.value, "project": hint,
                "why": f"domain {lesson.domain!r} belongs to project {hint!r}"}
    return {**fw, "why": "no project signal"}


def backfill(board: Any, actor: Any, *, dry_run: bool = False) -> dict[str, Any]:
    """Classify and retire every live lesson. Idempotent: a lesson already carrying its classified scope, or
    already retired, is left alone. dry_run=True only reports. Returns counts plus one row per change."""
    changes: list[dict[str, Any]] = []
    counts = {"framework": 0, "project": 0, "retired": 0, "unchanged": 0}
    for le in board.store.query("lesson", {}, limit=-1):
        if le.status != LessonStatus.live:
            continue
        got = classify(board.store, le)
        if got["action"] == "retire":
            changes.append({"id": le.id, "action": "retire", "why": got["why"]})
            counts["retired"] += 1
            if not dry_run:
                board.retire_lesson(actor, lesson_id=le.id, reason=got["why"])
            continue
        if (le.scope_kind.value, le.project) == (got["scope_kind"], got["project"]):
            counts["unchanged"] += 1
            continue
        counts[got["scope_kind"]] += 1
        changes.append({"id": le.id, "action": "scope", "scope_kind": got["scope_kind"],
                        "project": got["project"], "why": got["why"]})
        if not dry_run:
            board.scope_lesson(actor, lesson_id=le.id, scope_kind=got["scope_kind"], project=got["project"])
    return {"dry_run": dry_run, "counts": counts, "changes": changes}
