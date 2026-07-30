"""edp-claude — orchestration skeleton (component #2).

Public surface: schemas, the deterministic FSM, the tool registry factory,
and the DI context. Microservice seams are stubbed (DESIGN-v4 / LLD §3).
"""

from .fsm import plan_next_action, recipe_next_action
from .schemas import (
    Instruction,
    InstructionKind,
    Plan,
    PlanState,
    Recipe,
    RecipeState,
)
from .server import make_context, make_registry
from .tools import Ctx, build_registry

__version__ = "0.1.0"

__all__ = [
    "Recipe",
    "Plan",
    "Instruction",
    "InstructionKind",
    "RecipeState",
    "PlanState",
    "recipe_next_action",
    "plan_next_action",
    "make_context",
    "make_registry",
    "build_registry",
    "Ctx",
]
