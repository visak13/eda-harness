"""SPECIALIZATION-LAYERED-RULESETS.md (2026-06-01), Stage 4.

The briefs + add_action are wired to the layered ruleset: the coder uses
the constructive view + snippet bindings, the reviewer enforces the
enforced view by adherence, the specialist authors enriched entries, and
the planner tags an action's cross-cutting concerns.
"""

from pathlib import Path

from edp_contracts import ToolOk

_CMD = Path(__file__).resolve().parents[1] / ".claude" / "commands"
_GUIDES = Path(__file__).resolve().parents[1] / "docs" / "guides"


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def test_worker_loads_compiled_doc_for_specialist_work():
    # SPECIALIST-COMPILED-DOCS.md (2026-06-02): a specialist worker loads
    # the COMPILED per-stack doc (clean context), not assemble_ruleset / a
    # session fork / links.
    b = (_CMD / "worker.md").read_text(encoding="utf-8").lower()
    assert "get_specialist_doc" in b
    assert "spec_id" in b
    # the coder is NOT straitjacketed by the enforced rules
    assert "straitjacket" in b or "free to think" in b
    # no fork, no JSON, no link-chasing on the worker path
    assert "do not fork" in b or "you do not fork" in b
    # generic worker (no spec_id) falls back to the universal standards
    assert "coding-standards" in b
    # the old fetch-from-MCP guidance is gone
    assert "mcp_binding" not in b and "eda-designs" not in b


def test_reviewer_checks_cleanup_completeness_no_blind_delete():
    # 2026-06-03: incomplete cleanup (dangling references to a removed
    # thing) is a top bug class — the reviewer must check it, and flag
    # needed deletions for the user to approve, never blind-delete.
    b = (_CMD / "reviewer.md").read_text(encoding="utf-8").lower()
    assert "cleanup completeness" in b
    assert "dangling references" in b
    assert "blind-delete" in b or "do not delete anything yourself" in b
    assert "surface it to the neuron" in b or "user to approve" in b


def test_reviewer_enforces_compiled_doc_by_adherence():
    # 2026-06-02: the reviewer enforces the SAME compiled doc the coder
    # built against (one artifact, both roles), by [adherence] tag.
    b = (_CMD / "reviewer.md").read_text(encoding="utf-8").lower()
    assert "get_specialist_doc" in b
    assert "adherence" in b
    # adherence drives verdict severity
    assert "required" in b and "expected" in b and "preferred" in b
    assert "escalate" in b           # no-regex-without-approval
    # the old JSON-assemble path is gone from the reviewer
    assert "assemble_ruleset" not in b


def test_specialist_authors_enriched_entries():
    b = (_CMD / "specialist.md").read_text(encoding="utf-8").lower()
    assert "adherence" in b and "link_role" in b
    # don't restate universal standards — extends spec-universal
    assert "extends" in b and "universal" in b
    # 2026-06-02: the MCP/eda-designs "fetch don't generate" guidance was
    # removed (it just hands over code Claude still has to understand).
    assert "mcp_binding" not in b
    assert "eda-designs" not in b


def test_specialist_compiles_a_self_contained_doc():
    # SPECIALIST-COMPILED-DOCS.md (2026-06-02): the SME assembles + distills
    # a self-contained per-stack doc BEFORE pending_review (the review
    # artifact); workers load THAT, not the JSON/fork.
    b = (_CMD / "specialist.md").read_text(encoding="utf-8").lower()
    assert "assemble_ruleset" in b and "write_specialist_doc" in b
    assert "distill" in b and "self-contained" in b
    assert "keep/cut" in b or "shortest doc" in b      # the anti-100-rules rule
    assert "the user reviews" in b and "stable" in b   # doc gates stable


def test_specialist_guards_project_leakage_and_trustability():
    # 2026-06-03: a specialist is per-STACK — project artifacts in context
    # must be excluded; and the doc must be trustworthy by FORM (sourced +
    # falsifiable) so an approver who lacks the domain can still review it.
    b = (_CMD / "specialist.md").read_text(encoding="utf-8").lower()
    # project-agnostic guard (the React Flow leak)
    assert "project-agnostic" in b
    assert "every project on this stack" in b
    # the trust-by-form bar + the sources footer
    assert "grounded in" in b
    assert "falsifiable" in b and "sourced" in b
    assert "may not know the domain" in b or "can't judge the domain" in b


def test_planner_author_guide_tags_concerns():
    g = (_GUIDES / "planner-phase-author.md").read_text(encoding="utf-8").lower()
    assert "concerns" in g
    assert "security" in g
    # the verify step forks the matching reviewer
    assert "reviewer" in g


async def test_add_action_persists_concerns(env):
    rid = _ok(await env.call("start_recipe", goal="build an api", domain="api"))
    recipe_id = rid["recipe_id"]
    sid = _ok(await env.call("add_step", recipe_id=recipe_id,
                             description="build it", execution="spawn_planner", estimate={"hours": 1}))
    step_id = sid["step_id"]
    pid = _ok(await env.call("create_plan", recipe_id=recipe_id,
                             step_id=step_id, shape="linear-build",
                             goal="build the login endpoint"))
    plan_id = pid["plan_id"]
    _ok(await env.call("add_action", plan_id=plan_id, action_id="a1",
                       description="implement POST /login",
                       specialization="Java Spring Boot REST API",
                       concerns=["security"]))
    plan = env.ctx.plans.load(plan_id)
    a = next(a for a in plan.actions if a.action_id == "a1")
    assert a.concerns == ["security"]
