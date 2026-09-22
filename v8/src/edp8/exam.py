"""edp8 exam harness — make every curation or retrieval change MEASURED (steer m-3f96079aa8 item 1).

An exam is a JSON list of questions (or {"questions": [...]}), each
    {"n": 1, "epic": "epic-…", "question": "…", "expected": "…", "expected_ids": ["dec-…"]}
`expected_ids` is optional; when given, the harness checks automatically whether the pack holds
those records (as a ranked/always record or inside a replaces chain).

    python -m edp8.exam packs --exam exam4.json --out runs/exam4-c9f635f
        one lookup per question through the TOOL LAYER (bundles.invoke → the board's /v1/lookup, so
        the pack is exactly what a seat sees); writes packs/<n>.md (the reader's only input),
        packs/<n>.json (records + receipt), reader_prompt.md, grading.json (verdicts to fill:
        right | half | miss | invented) and manifest.json (board rev, time, per-question signals).
    python -m edp8.exam score --graded runs/exam4-c9f635f/grading.json [--baseline <older grading.json>]
        totals per epic and overall (right=1, half=0.5), and per-question changes against a baseline.

Read-only against the board: it never writes records and never loads an embedding model.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERDICTS = {"right": 1.0, "half": 0.5, "miss": 0.0, "invented": 0.0}
# the architect's grade files (v8/.data/exams/r4) use CORRECT | PARTIAL | WRONG | NOT-IN-PACK
VERDICT_ALIASES = {"correct": "right", "partial": "half", "wrong": "invented", "not-in-pack": "miss",
                   "not_in_pack": "miss", "not in pack": "miss"}


def _verdict(v: Any) -> str:
    v = (v or "").strip().lower()
    return VERDICT_ALIASES.get(v, v)


_STOP = set("a an the of to in on for and or is are was were be by with as at from that this it its "
            "which what why how when who not no do does did into than then so".split())

READER_PROMPT = """You are a fresh reader. For each question, answer ONLY from the pack file named for it
(packs/<n>.md). Do not use any other knowledge, file or tool. If the pack does not contain the answer,
say "not in the pack" — never guess. Quote the record id(s) you relied on.

Output one JSON object per line: {"n": <n>, "answer": "...", "ids": ["dec-…"]}
"""


def load_exam(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    qs = data.get("questions") if isinstance(data, dict) else data
    if not isinstance(qs, list) or not qs:
        raise ValueError(f"{path}: expected a non-empty list of questions (or {{'questions': [...]}})")
    out = []
    for i, q in enumerate(qs, start=1):
        if not q.get("epic") or not q.get("question"):
            raise ValueError(f"{path}: question #{i} needs 'epic' and 'question'")
        # the architect's exam files carry `answer` + `proof_ids` (source message/doc ids)
        out.append({"n": q.get("n", i), "epic": q["epic"], "question": q["question"],
                    "expected": q.get("expected") or q.get("answer", ""),
                    "expected_ids": list(q.get("expected_ids") or []),
                    "proof_ids": list(q.get("proof_ids") or [])})
    ns = [q["n"] for q in out]
    if len(set(ns)) != len(ns):
        raise ValueError(f"{path}: duplicate question numbers")
    return out


def _content_terms(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9][a-z0-9\-]{2,}", (text or "").lower()) if t not in _STOP}


def pack_signals(q: dict[str, Any], value: dict[str, Any]) -> dict[str, Any]:
    """Automatic, grader-independent signals for one pack: which expected ids it holds, and what share
    of the expected answer's content words appear in the rendered body (a crude recall proxy)."""
    body = value.get("body", "") or ""
    recs = value.get("records", []) or []
    present = {r.get("id") for r in recs}
    for r in recs:
        present.update(h.get("id") for h in r.get("history", []) or [])
    exp_ids = q.get("expected_ids") or []
    # proof_ids are SOURCE ids (m-…/doc ids): a pack covers one when a record in it came from it
    sources = {r.get("source") for r in recs if r.get("source")}
    sources.update(h.get("source") for r in recs for h in r.get("history", []) or [] if h.get("source"))
    proofs = q.get("proof_ids") or []
    proof_hit = [p for p in proofs if p in sources or p in body]
    hit = [i for i in exp_ids if i in present]
    terms = _content_terms(q.get("expected", ""))
    body_terms = _content_terms(body)
    rc = value.get("receipt", {}) or {}
    return {
        "expected_ids_found": hit,
        "expected_ids_missing": [i for i in exp_ids if i not in present],
        "id_recall": (len(hit) / len(exp_ids)) if exp_ids else None,
        "proof_ids_found": proof_hit,
        "proof_recall": round(len(proof_hit) / len(proofs), 3) if proofs else None,
        "term_coverage": round(len(terms & body_terms) / len(terms), 3) if terms else None,
        "records": len(recs), "bytes": rc.get("bytes"), "seed_kind": rc.get("seed_kind"),
        "source_excerpts": rc.get("source_excerpts"),
    }


def _lookup_via_tools(scope: str, question: str) -> dict[str, Any]:
    from . import bundles
    tool = next(t for t in bundles.KNOWLEDGE_TOOLS if t.name == "lookup")
    return bundles.invoke(tool, {"scope": scope, "question": question}, seat="exam")


def _board_rev(client: Any) -> str:
    try:
        r = client._request("GET", "/v1/health")
        v = r.get("value", r) if isinstance(r, dict) else {}
        return str(v.get("git_rev") or v.get("version") or "?")
    except Exception:
        return "?"


def run_packs(exam: list[dict[str, Any]], out: Path, *, lookup: Any = None, rev: str = "?") -> dict[str, Any]:
    """Generate one pack per question. `lookup(scope, question) -> envelope` is injectable for tests."""
    lookup = lookup or _lookup_via_tools
    (out / "packs").mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                "board_rev": rev, "questions": []}
    grading = []
    for q in exam:
        env = lookup(q["epic"], q["question"])
        ok = bool(env.get("ok"))
        value = (env.get("value") or {}) if ok else {}
        n = q["n"]
        (out / "packs" / f"{n}.md").write_text(
            f"# Question {n}\n\n{q['question']}\n\n## Pack (lookup scope={q['epic']})\n\n"
            + (value.get("body", "") if ok else f"(lookup failed: {env.get('error')})") + "\n",
            encoding="utf-8")
        (out / "packs" / f"{n}.json").write_text(json.dumps(value if ok else env, indent=1), encoding="utf-8")
        sig = pack_signals(q, value) if ok else {"error": env.get("error")}
        manifest["questions"].append({"n": n, "epic": q["epic"], **sig})
        grading.append({"n": n, "epic": q["epic"], "question": q["question"], "expected": q["expected"],
                        "signals": sig, "verdict": "", "note": ""})
    (out / "grading.json").write_text(json.dumps(grading, indent=1), encoding="utf-8")
    (out / "reader_prompt.md").write_text(READER_PROMPT, encoding="utf-8")

    def _mean(key: str) -> float | None:
        vals = [m[key] for m in manifest["questions"] if m.get(key) is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    manifest["summary"] = {"questions": len(exam), "failed_lookups": sum(1 for m in manifest["questions"] if "error" in m),
                           "mean_id_recall": _mean("id_recall"), "mean_proof_recall": _mean("proof_recall"),
                           "mean_term_coverage": _mean("term_coverage")}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def score(graded: list[dict[str, Any]], baseline: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    by_epic: dict[str, dict[str, float]] = {}
    ungraded = []
    graded = [g for g in graded if "n" in g]  # skip summary rows the grade files carry
    for g in graded:
        v = _verdict(g.get("verdict"))
        if v not in VERDICTS:
            ungraded.append(g["n"])
            continue
        e = by_epic.setdefault(g["epic"], {"n": 0, "points": 0.0, "right": 0, "half": 0, "miss": 0, "invented": 0})
        e["n"] += 1
        e["points"] += VERDICTS[v]
        e[v] += 1
    tot_n = sum(e["n"] for e in by_epic.values())
    tot_p = sum(e["points"] for e in by_epic.values())
    res: dict[str, Any] = {
        "overall": {"graded": tot_n, "points": tot_p, "pct": round(100 * tot_p / tot_n, 1) if tot_n else None,
                    **{k: sum(int(e[k]) for e in by_epic.values()) for k in VERDICTS}},
        "by_epic": {k: {**v, "pct": round(100 * v["points"] / v["n"], 1)} for k, v in sorted(by_epic.items())},
        "ungraded": ungraded,
    }
    if baseline is not None:
        old = {b["n"]: _verdict(b.get("verdict")) for b in baseline if "n" in b}
        res["changes"] = [{"n": g["n"], "was": old.get(g["n"]), "now": _verdict(g.get("verdict"))}
                          for g in graded if g["n"] in old and old[g["n"]] != _verdict(g.get("verdict"))]
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m edp8.exam", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("packs", help="generate lookup packs + grading template for an exam")
    p.add_argument("--exam", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--board", default=None, help="board URL (default EDP8_BOARD_URL or :9400)")
    s = sub.add_parser("score", help="score a filled grading.json")
    s.add_argument("--graded", required=True, type=Path)
    s.add_argument("--baseline", type=Path, default=None)
    a = ap.parse_args(argv)
    if a.cmd == "packs":
        from . import bundles
        from .client import BoardClient
        client = BoardClient(base_url=a.board)
        bundles.set_client(client)
        m = run_packs(load_exam(a.exam), a.out, rev=_board_rev(client))
        print(json.dumps(m["summary"]))
        return 1 if m["summary"]["failed_lookups"] else 0
    graded = json.loads(a.graded.read_text(encoding="utf-8"))
    base = json.loads(a.baseline.read_text(encoding="utf-8")) if a.baseline else None
    print(json.dumps(score(graded, base), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
