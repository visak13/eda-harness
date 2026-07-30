"""Validate that the local OpenCode startup path selects a known role and policy."""
from __future__ import annotations
import argparse
from pathlib import Path
from opencode_policy import POLICY_PATH, ROLE_MODELS

def configured_model(wrapper: Path) -> str:
    """Read the model OpenCode will select from an agent wrapper's frontmatter."""
    for line in wrapper.read_text(encoding="utf-8").splitlines():
        if line.startswith("model:"):
            return line.partition(":")[2].strip()
    raise ValueError(f"missing model in role wrapper: {wrapper.name}")

#: POOL role name -> FLEET agent name. The pool spawns us with its own role
#: vocabulary (see ROLE_AGENTS in edp-pool/src/edp_pool/opencode_launcher.py,
#: which maps the same set to "edp-<agent>"); ROLE_MODELS and the wrapper
#: filenames use the agent vocabulary. Underscore->hyphen covers goal_keeper
#: and pattern_observer; planner->agentic-plan is a genuine rename. Missing
#: this translation made every planner/goal_keeper/pattern_observer console
#: die at the gate - masked until 2026-07-21 because a bad interpreter had
#: been failing the gate identically for ALL roles.
_POOL_ROLE_ALIASES = {"planner": "agentic-plan"}

def fleet_agent(role: str) -> str:
    """Translate a pool role name into the fleet agent name."""
    return _POOL_ROLE_ALIASES.get(role, role.replace("_", "-"))

def select_role(role: str, root: Path) -> str:
    role = fleet_agent(role)
    if role not in ROLE_MODELS:
        raise ValueError(f"unsupported OpenCode fleet role: {role}")
    if not (root / POLICY_PATH).is_file():
        raise FileNotFoundError(f"missing local behavior policy: {POLICY_PATH}")
    wrapper = root / ".opencode" / "agents" / f"edp-{role}.md"
    if not wrapper.is_file():
        raise FileNotFoundError(f"missing role wrapper: {role}")
    actual_model = configured_model(wrapper)
    expected_model = ROLE_MODELS[role]
    if actual_model != expected_model:
        raise ValueError(
            f"role wrapper model mismatch for {role}: "
            f"expected {expected_model}, found {actual_model}"
        )
    return actual_model

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", required=True)
    parser.add_argument("--handle", required=True)
    args = parser.parse_args()
    print(f"role={args.role} model={select_role(args.role, Path(__file__).resolve().parent)} policy={POLICY_PATH} handle={args.handle}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
