"""Executable OpenCode-only review routing and closure policy."""
from __future__ import annotations
from dataclasses import dataclass

TERRA = "openai/gpt-5.6-terra"
SOL = "openai/gpt-5.6-sol"
ROLE_MODELS = {
    "worker": TERRA,
    "reviewer": SOL,
    "agentic-plan": SOL,
    "neuron": SOL,
    "specialist": SOL,
    "pattern-observer": SOL,
    "goal-keeper": SOL,
    "curiosity": SOL,
    "consult": SOL,
}
POLICY_PATH = ".opencode/OPENCODE-BEHAVIOR-POLICY.md"

@dataclass(frozen=True)
class RemediationBrief:
    finding: str
    scope: str
    safety: str
    route: str = "terra"
    requires_fresh_sol_review: bool = True

@dataclass(frozen=True)
class ReviewRoute:
    inline_fix: bool
    verification_required: bool
    remediation_brief: RemediationBrief | None = None

def route_finding(
    *,
    finding: str,
    scope: str,
    safety: str,
    in_scope: bool = True,
    regex_only: bool = False,
) -> ReviewRoute:
    """Choose inline Sol repair or a Terra remediation without regex escalation."""
    # Regex is intentionally not part of the routing condition. It neither
    # escalates safe work nor makes unsafe/out-of-scope work safe to patch.
    del regex_only
    if safety == "safe" and in_scope:
        return ReviewRoute(inline_fix=True, verification_required=True)
    return ReviewRoute(False, False, RemediationBrief(finding, scope, safety))

def closure_allowed(*, review_failed: bool, terra_remediated: bool, fresh_sol_passed: bool) -> bool:
    """Return whether succeeded closure is allowed for a reviewed action."""
    return not review_failed or (terra_remediated and fresh_sol_passed)
