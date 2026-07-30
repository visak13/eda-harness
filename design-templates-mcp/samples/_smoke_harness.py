r"""Executed MCP smoke harness for fetch_behavior (recipe action a2).

Imports the a1 resolver IN-PROCESS (same code path the registered
``fetch_behavior`` MCP tool calls) and writes the ACTUAL returned dicts
to samples/*.json. No mocks: every payload below is the real tool output.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../design-templates-mcp/samples
ROOT = HERE.parent                               # .../design-templates-mcp
sys.path.insert(0, str(ROOT))                    # make behavior_resolver importable

import behavior_resolver as br                    # noqa: E402


def dump(payload: dict, fname: str) -> None:
    out = HERE / fname
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    ok = payload.get("ok")
    print(f"  wrote {fname:32s} ok={ok} bytes={out.stat().st_size}")


def main() -> int:
    print(f"resolver root = {br.designs_root()}")
    print("executing fetch_behavior(dialog, ...):")

    core = br.resolve_behavior("dialog", framework="react", layer="core")
    dump(core, "dialog.core.react.json")

    composed = br.resolve_behavior("dialog", framework="react", layer="composed")
    dump(composed, "dialog.composed.react.json")

    company = br.resolve_behavior("dialog", framework="react", layer="company")
    dump(company, "dialog.company.react.json")

    composed_vanilla = br.resolve_behavior("dialog", framework="vanilla", layer="composed")
    dump(composed_vanilla, "dialog.composed.vanilla.json")

    # ---- assertions on the REAL output (proves monotonic additive merge) ----
    assert core.get("ok"), f"core fetch failed: {core}"
    assert composed.get("ok"), f"composed fetch failed: {composed}"
    mc = composed["merge_check"]
    core_parts = set(core["contract"]["part"])
    composed_parts = set(composed["contract"]["part"])
    assert core_parts <= composed_parts, "core parts lost in composition!"
    assert mc["core_states_present"], "core states lost in composition!"
    assert mc["additive_only"], "composition was not additive!"

    print("\nSMOKE ASSERTIONS PASSED:")
    print(f"  core   config={core['config']}")
    print(f"  core   parts ={core['contract']['part']}")
    print(f"  comp   config={composed['config']}")
    print(f"  comp   parts ={composed['contract']['part']}")
    print(f"  merge_check.core_states_present = {mc['core_states_present']}")
    print(f"  merge_check.added_states        = {mc['added_states']}")
    print(f"  merge_check.added_context_keys  = {mc['added_context_keys']}")
    print(f"  merge_check.additive_only       = {mc['additive_only']}")
    print(f"  core files   = {core['files']}")
    print(f"  composed files = {composed['files']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
