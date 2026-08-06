"""WS2 — delegation-viability + adversary-calibration benchmark (v7 §WS2).

WHAT IT ANSWERS (user's core question): can a cheap/subscription model
execute work authored by a frontier model, at acceptable quality, inside
this harness — and which task classes should DELEGATION_ROUTES actually
route? Plus: which adversarial lenses have a real hit rate?

HOW IT RUNS (operator-supervised — it bills the ChatGPT plan quota):
    cd claude && .venv/Scripts/python.exe tests/bench/run_ws2.py [--limit N]
                 [--adversary-only] [--dry-run]

It is deliberately a SCRIPT, not a pytest: each sol turn can take minutes
and costs quota; you watch it, and you can stop between cases. Results
append to tests/bench/ws2_results.jsonl (one row per case) — re-runs skip
completed case ids, so it is resumable.

MATRIX (sol-only, per user ruling 2026-08-05 — no http keys configured):
  * delegate-executes: sol drafts the artifact from a self-contained work
    order (the delegate_generate path exactly as a worker would call it).
  * adversary: sol challenges a target with a KNOWN defect through a named
    lens; a hit = the planted defect appears in the findings.
The Claude-alone baselines are NOT run by this script (they would bill
Anthropic quota from inside a live session instead); baseline numbers come
from the WS6 proof run's audit sidecars — this script measures the
delegate side and the lens hit-rates, which is what calibrates the routes.

JUDGING: deterministic checks per case (does the artifact satisfy the
acceptance probes — substring/structure checks, no LLM judge), so the
verdicts are reproducible. The REAL acceptance gate (build+tests+reviewer)
happens in WS6; this is the cheap calibration pass in front of it.
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

RESULTS = Path(__file__).resolve().parent / "ws2_results.jsonl"

# ── generation cases: representative task classes, self-contained orders ────
GEN_CASES = [
    {
        "id": "gen-codegen-1",
        "task_class": "codegen",
        "task": ("Write a complete Python module `slugify.py` with one "
                 "function slugify(text: str, max_len: int = 40) -> str: "
                 "lowercase, non-alphanumerics collapse to single hyphens, "
                 "trimmed of hyphens, truncated to max_len without cutting "
                 "mid-hyphen-run. Include full type hints and a docstring."),
        "acceptance": "def slugify(text: str, max_len: int = 40) -> str; "
                      "handles empty string; no regex catastrophic patterns",
        "probes": ["def slugify(", "max_len", "lower"],
    },
    {
        "id": "gen-tests-1",
        "task_class": "tests",
        "task": ("Write pytest tests for this function (include the exact "
                 "function under test in a fixture-free import-less style — "
                 "define it inline at the top of the test file):\n\n"
                 "def clamp(v, lo, hi):\n"
                 "    if lo > hi: raise ValueError('lo>hi')\n"
                 "    return max(lo, min(hi, v))\n\n"
                 "Cover: normal, at-bounds, out-of-bounds, lo>hi error, "
                 "float/int mix. One behavior per test, named for it."),
        "acceptance": "each test asserts exactly one behavior; the error "
                      "case uses pytest.raises",
        "probes": ["def test_", "pytest.raises", "clamp("],
    },
    {
        "id": "gen-docs-1",
        "task_class": "docs",
        "task": ("Write a README section (markdown, <=40 lines) documenting "
                 "this CLI: `bench run [--limit N] [--dry-run]` appends "
                 "JSONL rows to results; re-runs skip completed ids. "
                 "Audience: a developer seeing the repo first time."),
        "acceptance": "states resumability; documents both flags; no fluff",
        "probes": ["--limit", "--dry-run", "resum"],
    },
    {
        "id": "gen-refactor-1",
        "task_class": "refactor",
        "task": ("Refactor for clarity WITHOUT changing behavior (return "
                 "the full new version):\n\n"
                 "def f(x):\n"
                 "    r=[]\n"
                 "    for i in range(len(x)):\n"
                 "        if x[i] is not None:\n"
                 "            if x[i] not in r:\n"
                 "                r.append(x[i])\n"
                 "    return r\n\n"
                 "Preserve order and de-dup semantics exactly."),
        "acceptance": "order-preserving dedup of non-None survives; "
                      "no behavior change",
        "probes": ["def f(", "None"],
    },
]

# ── adversary cases: targets with PLANTED defects; a hit names the plant ────
ADV_CASES = [
    {
        "id": "adv-acceptance-1",
        "lens": "break-the-acceptance",
        "target_kind": "plan",
        "target_id": "bench-plan-1",
        "content": ("Plan: build a login endpoint. Actions: a1 implement "
                    "POST /login returning a JWT on success, acceptance: "
                    "'unit tests pass'. a2 write unit tests for the happy "
                    "path, acceptance: 'tests exist'."),
        "planted": ["failure", "invalid", "wrong password", "negative",
                    "rate", "brute"],
        "planted_doc": "acceptance never tests a FAILED login",
    },
    {
        "id": "adv-wrong-option-1",
        "lens": "wrong-option-chosen",
        "target_kind": "spec_decision",
        "target_id": "bench-dec-1",
        "content": ("Spec decision: chosen='parse the model tool-calls by "
                    "regex from raw completion text'. alternatives=['native "
                    "structured tool-call API']. revisit_when='regex misses "
                    "a call'. Context: the provider HAS a native tool-call "
                    "API with typed arguments."),
        "planted": ["native", "structured", "api"],
        "planted_doc": "regex parsing chosen over the native structured API",
    },
    {
        "id": "adv-missing-concern-1",
        "lens": "missing-concern",
        "target_kind": "plan",
        "target_id": "bench-plan-2",
        "content": ("Plan: multi-user task board SPA (admins manage all "
                    "boards, members edit their own). Actions cover: board "
                    "CRUD UI, drag-drop, REST client, styling, e2e happy "
                    "path. Concerns tagged: state, a11y."),
        "planted": ["auth", "role", "permission", "server-side"],
        "planted_doc": "no authz/roles concern despite two user kinds",
    },
]


def _done_ids() -> set:
    if not RESULTS.is_file():
        return set()
    out = set()
    for line in RESULTS.read_text("utf-8").splitlines():
        try:
            out.add(json.loads(line)["id"])
        except (ValueError, KeyError):
            continue
    return out


def _append(row: dict) -> None:
    with RESULTS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def run(limit: int | None, adversary_only: bool, dry: bool) -> int:
    from edp_claude.tools import bridge
    done = _done_ids()
    ran = 0
    cases = ([] if adversary_only else
             [("generate", c) for c in GEN_CASES]) + \
            [("challenge", c) for c in ADV_CASES]
    for kind, c in cases:
        if c["id"] in done:
            print(f"skip {c['id']} (done)")
            continue
        if limit is not None and ran >= limit:
            break
        print(f"RUN {c['id']} [{kind}] …", flush=True)
        if dry:
            ran += 1
            continue
        t0 = time.time()
        try:
            if kind == "generate":
                r = bridge.delegate_call(
                    kind="generate", delegate_name="sol", task=c["task"],
                    acceptance=c["acceptance"], caller=f"ws2:{c['id']}")
                low = r.content.lower()
                probes_hit = [p for p in c["probes"] if p.lower() in low]
                verdict = {"probes_hit": probes_hit,
                           "probes_total": len(c["probes"]),
                           "pass": len(probes_hit) == len(c["probes"])}
            else:
                r = bridge.delegate_call(
                    kind="challenge", delegate_name="sol",
                    task=(f"Attack this {c['target_kind']} "
                          f"({c['target_id']}) through the lens: "
                          f"{c['lens']}. Find what is WRONG."),
                    context=c["content"], caller=f"ws2:{c['id']}")
                text = json.dumps(r.findings).lower() + r.content.lower()
                hits = [p for p in c["planted"] if p in text]
                verdict = {"planted": c["planted_doc"],
                           "hit_terms": hits,
                           "hit": bool(hits),
                           "findings": len(r.findings)}
            _append({"id": c["id"], "kind": kind,
                     "lens": c.get("lens"),
                     "task_class": c.get("task_class"),
                     "ok": r.ok, "error": r.error,
                     "secs": round(time.time() - t0, 1),
                     "tokens_in": r.tokens_in, "tokens_out": r.tokens_out,
                     "verdict": verdict,
                     "content_head": r.content[:400]})
            print(f"  -> ok={r.ok} verdict={verdict} "
                  f"({time.time()-t0:.0f}s)")
        except Exception as e:  # noqa: BLE001 — record, continue, never grind
            _append({"id": c["id"], "kind": kind, "ok": False,
                     "error": f"harness: {e!r}",
                     "secs": round(time.time() - t0, 1)})
            print(f"  -> ERROR {e!r}")
        ran += 1
    print(f"\n{ran} case(s) run; results: {RESULTS}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--adversary-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    sys.exit(run(a.limit, a.adversary_only, a.dry_run))
