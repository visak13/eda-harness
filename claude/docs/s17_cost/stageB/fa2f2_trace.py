"""FA2-F2 (s17 RC2) reproducible trace — observe() idempotency + stale-artifact GC.

Drives the REAL observe() MCP-tool code path in-process against a throwaway
temp root (no live broker/pool/MCP touched; no subprocess spawned). Proves:

  1. Two observe() calls with the SAME subscription_id + identical spec yield
     reused=True on the second call, the SAME monitor_cmd, and exactly ONE
     .spec artifact (one logical subscription = one live driver).
  2. A differing spec under the same id is a re-spec (reused=False, overwritten).
  3. A generated (no-id) subscription is never reused.
  4. observe() garbage-collects abandoned sub-*.spec triplets older than the
     TTL on each arm, never the one being armed, never the registry/ +
     effect_audit/ durable subdirs.

Run: .venv/Scripts/python.exe docs/s17_cost/stageB/fa2f2_trace.py
"""
import asyncio
import json
import os
import tempfile
from pathlib import Path

from edp_claude.server import make_context
from edp_claude.tools import build_registry, _tools


async def main() -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="fa2f2-trace-"))
    ctx = make_context(tmp)
    tools = {t.name: t for t in build_registry(ctx)}
    observe = tools["observe"]
    root = ctx.recipes.root.parent / ".reactive"

    async def call(**inp):
        res = await observe.run(inp)
        return res.data

    out: dict = {}

    # 1. idempotent reuse → one driver
    first = await call(spec="rx.broker(me)", bindings={"me": "x"},
                       subscription_id="sub-idem")
    second = await call(spec="rx.broker(me)", bindings={"me": "x"},
                        subscription_id="sub-idem")
    out["first_reused"] = first["reused"]
    out["second_reused"] = second["reused"]
    out["monitor_cmd_identical"] = first["monitor_cmd"] == second["monitor_cmd"]
    out["spec_artifact_count_for_sid"] = len(list(root.glob("sub-idem.spec")))

    # 2. re-spec (different spec, same id)
    respec = await call(spec="rx.worklog(plan_id)", bindings={"plan_id": "p1"},
                        subscription_id="sub-idem")
    out["respec_reused"] = respec["reused"]
    out["respec_spec_on_disk"] = (root / "sub-idem.spec").read_text(
        encoding="utf-8")

    # 3. generated id never reused
    a = await call(spec="rx.broker(me)", bindings={"me": "x"})
    b = await call(spec="rx.broker(me)", bindings={"me": "x"})
    out["generated_distinct"] = a["subscription_id"] != b["subscription_id"]
    out["generated_reused"] = a["reused"] or b["reused"]

    # 4. GC: seed an ancient triplet + durable subdirs, then arm a fresh sub
    for suffix in (".spec", ".bindings.json", ".effect.json"):
        (root / f"sub-stale{suffix}").write_text("old", encoding="utf-8")
        os.utime(root / f"sub-stale{suffix}", (1.0, 1.0))   # epoch 1 = ancient
    (root / "registry").mkdir(exist_ok=True)
    (root / "registry" / "rule.json").write_text("{}", encoding="utf-8")
    (root / "effect_audit").mkdir(exist_ok=True)
    (root / "effect_audit" / "log.jsonl").write_text("{}", encoding="utf-8")

    _tools._REACTIVE_SPEC_TTL_SECS = 60   # shrink TTL for the trace
    before = len(list(root.glob("sub-*.spec")))
    await call(spec="rx.broker(me)", bindings={"me": "y"},
               subscription_id="sub-fresh")
    after = len(list(root.glob("sub-*.spec")))
    out["gc_stale_triplet_removed"] = not (root / "sub-stale.spec").exists() \
        and not (root / "sub-stale.bindings.json").exists() \
        and not (root / "sub-stale.effect.json").exists()
    out["gc_fresh_sub_kept"] = (root / "sub-fresh.spec").exists()
    out["gc_registry_subdir_kept"] = (root / "registry" / "rule.json").exists()
    out["gc_effect_audit_subdir_kept"] = (
        root / "effect_audit" / "log.jsonl").exists()
    out["spec_count_before_after"] = [before, after]

    return out


if __name__ == "__main__":
    result = asyncio.run(main())
    print(json.dumps(result, indent=2))
