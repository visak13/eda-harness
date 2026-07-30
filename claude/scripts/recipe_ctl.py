"""recipe_ctl — headless suspend/resume of a recipe via the REAL tool layer.

The pool panel's "Suspend recipe" / "Resume recipe" buttons need the durable
W11 verbs (`suspend_recipe` / `resume_recipe`), which live in the edp_claude
tool layer — a different service/venv from the pool. This CLI is the bridge:
the pool shells out to it, and it drives the SAME tool code a neuron would
(planners steered to close, workers reaped, manifest written / read back),
against the live broker+pool via the http backend.

    uv run python scripts/recipe_ctl.py suspend <recipe_id> [--reason ...]
    uv run python scripts/recipe_ctl.py resume  <recipe_id>

Prints ONE JSON object to stdout (the tool's own envelope) and exits 0 on
ok, 1 on refusal/error — the pool endpoint relays it verbatim, so the panel
shows the tool's real message, never a paraphrase.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

CLAUDE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLAUDE / "src"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("verb", choices=["suspend", "resume"])
    ap.add_argument("recipe_id")
    ap.add_argument("--reason", default="operator request via control panel")
    args = ap.parse_args()

    os.environ.setdefault("EDP_MCP_BACKEND", "http")
    os.environ.setdefault("EDP_AGENT_HOME", str(CLAUDE))
    os.environ.setdefault("EDP_TIER_WRITE", "1")

    from edp_claude.mcp_server import _build_context
    from edp_claude.tools._tools import (ResumeRecipe, SuspendRecipe,
                                         _ResumeRecipeIn, _SuspendRecipeIn)

    ctx = _build_context(CLAUDE)
    if args.verb == "suspend":
        res = asyncio.run(SuspendRecipe(ctx)._run(_SuspendRecipeIn(
            recipe_id=args.recipe_id, reason=args.reason)))
    else:
        res = asyncio.run(ResumeRecipe(ctx)._run(_ResumeRecipeIn(
            recipe_id=args.recipe_id)))

    ok = getattr(res, "ok", False)
    data = getattr(res, "data", None)
    if hasattr(data, "model_dump"):
        data = data.model_dump(mode="json")
    payload = {"ok": bool(ok),
               "data": data if ok else None,
               "error": None if ok else str(
                   getattr(res, "message", res))[:800]}
    print(json.dumps(payload, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
