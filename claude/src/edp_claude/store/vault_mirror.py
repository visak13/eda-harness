"""Obsidian VAULT projection of the recipe/plan stores (sol harness, 2026-07-19).

USER RULING: in the sol harness "only the opencode harness and obsidian
changed, where claude code tui and json file was memory layer" — the vault
is the human/memory-facing layer, exactly the role the lean harness's vault
played. This module is a pure PROJECTION, not a store: the JSON stores stay
the single source of truth and every engine formula (digests, tiering,
injection, ack ledger) is untouched. On every store save() the object is
re-rendered as a Markdown note under the vault, so recipes and plans appear
in Obsidian automatically — created, updated, and terminal-stamped with ZERO
manual steps, mirroring how recipe.json always behaved.

Layout (wikilinked for the Obsidian graph):
    <vault>/recipes/<recipe_id>.md     — goal, outcomes, step checklist
                                          with [[<plan note>]] links,
                                          decisions/questions
    <vault>/plans/<plan_id>.md         — goal, shape, action checklist with
                                          spec ids + statuses, verdicts,
                                          [[<recipe note>]] backlink

Config: EDP_VAULT_DIR names the vault root; unset → `<agent_home>/../vault`
(eda-base3/vault beside the claude agent home); the literal value "0"
disables mirroring. Writes are BEST-EFFORT by construction: a vault write
failure must never fail the durable store save it mirrors.
"""

from __future__ import annotations

import os
from pathlib import Path

_BOX = {"done": "x", "skipped": "x"}


def vault_root(store_root: Path) -> Path | None:
    """The vault directory, or None when mirroring is disabled.
    `store_root` is the store's own root (…/claude/.recipes or …/claude/
    .plans); the default vault sits beside the agent home: eda-base3/vault."""
    raw = os.environ.get("EDP_VAULT_DIR", "").strip()
    if raw == "0":
        return None
    if raw:
        return Path(raw)
    return store_root.parent.parent / "vault"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


def _check(status: str) -> str:
    return _BOX.get(status, " ")


def mirror_recipe(recipe, store_root: Path) -> None:
    """Render one recipe as its vault note. Best-effort: never raises."""
    try:
        root = vault_root(store_root)
        if root is None:
            return
        r = recipe
        lines = [
            "---",
            f"recipe_id: {r.recipe_id}",
            f"state: {r.state}",
            f"domain: {r.domain}",
            f"version: {r.version}",
            f"updated: {r.updated_at}",
            "---",
            "",
            f"# {r.recipe_id}",
            "",
            "## Goal",
            r.user_goal_distilled or r.user_goal_verbatim or "",
            "",
            "## Expected outcomes",
        ]
        for o in getattr(r.comprehension, "expected_outcomes", []) or []:
            desc = getattr(o, "description", None) or str(o)
            met = getattr(o, "met", None)
            mark = "x" if met else " "
            lines.append(f"- [{mark}] {desc}")
        lines += ["", "## Steps"]
        for s in r.steps:
            plan_note = f"{r.recipe_id}-{s.step_id}"
            lines.append(
                f"- [{_check(s.status)}] **{s.step_id}** ({s.status}) "
                f"[[{plan_note}]] — {s.description[:160]}")
        ctx = r.context
        if getattr(ctx, "decisions", None):
            lines += ["", "## Decisions"]
            for d in ctx.decisions:
                title = getattr(d, "title", None) or getattr(
                    d, "text", None) or str(d)
                lines.append(f"- {str(title)[:200]}")
        if getattr(ctx, "open_questions", None):
            lines += ["", "## Open questions"]
            for q in ctx.open_questions:
                lines.append(f"- {str(q)[:200]}")
        if r.final_outcome:
            lines += ["", "## Final outcome", "", f"{r.final_outcome}"]
        _write(root / "recipes" / f"{r.recipe_id}.md",
               "\n".join(lines) + "\n")
    except Exception:  # noqa: BLE001 — a mirror must never fail the save
        pass


def mirror_plan(plan, store_root: Path) -> None:
    """Render one plan as its vault note. Best-effort: never raises."""
    try:
        root = vault_root(store_root)
        if root is None:
            return
        p = plan
        lines = [
            "---",
            f"plan_id: {p.plan_id}",
            f"recipe: {p.recipe_id}",
            f"state: {p.state}",
            f"terminal_status: {p.terminal_status or ''}",
            f"version: {p.version}",
            "---",
            "",
            f"# {p.plan_id}",
            "",
            f"Recipe: [[{p.recipe_id}]] · step `{p.recipe_step_id}` · "
            f"shape `{p.shape}`",
            "",
            "## Goal",
            p.goal or "",
            "",
            "## Actions",
        ]
        for a in p.actions:
            spec = f" `{a.spec_id}`" if getattr(a, "spec_id", None) else ""
            deps = (f" (after {', '.join(a.depends_on)})"
                    if a.depends_on else "")
            lines.append(
                f"- [{_check(a.status)}] **{a.action_id}** "
                f"({a.status}){spec}{deps} — {a.description[:160]}")
            rv = getattr(a, "review_verdict", None) or {}
            if rv:
                passed = "PASS" if rv.get("passed") else "FAIL"
                fixed = " +fixed_inline" if rv.get("fixed_inline") else ""
                lines.append(f"    - review: {passed}{fixed}")
        _write(root / "plans" / f"{p.plan_id}.md", "\n".join(lines) + "\n")
    except Exception:  # noqa: BLE001
        pass
