"""Usage: python after_table.py > after_table.json

Before/after per-unit table from wake_costs + token_split (c-8e33e18581). Read-only over the transcripts."""
import json, os, statistics, sys
from pathlib import Path
from collections import defaultdict
# wake_costs.py and token_split.py live in the eda-context checkout beside this repo (the BEFORE run used them too)
sys.path.insert(0, os.environ.get("EDA_CONTEXT_SCRIPTS", str(Path(__file__).resolve().parents[6] / "eda-context" / "scripts")))
import wake_costs as wc, token_split as ts

D = wc.DEFAULT_DIR
WIN = {"before": ("2026-09-02", "2026-10-01"), "after": ("2026-10-05", "2026-10-08")}
def win(day):
    for k, (a, b) in WIN.items():
        if day and a <= day <= b:
            return k
PFX = chr(92) * 2 + "?" + chr(92)
paths = [Path(PFX + str(q)) for q in sorted(D.glob("*/*.jsonl"))]  # long paths
turns = defaultdict(list)
seen = set()  # a pool transcript can be a copy of another seat's file: count each turn once
for p in paths:
    for tr in wc.parse_session(p):
        w = win((tr["ts"] or "")[:10])
        key = (tr["ts"], tr["trigger"], round(tr["cost"], 6))
        if w and key not in seen:
            seen.add(key)
            turns[w].append(tr)
def first_day(p):
    with p.open(encoding="utf-8") as f:
        for raw in f:
            try: o = json.loads(raw)
            except ValueError: continue
            if o.get("timestamp"): return o["timestamp"][:10]
acc = {}
for k in WIN:
    acc[k] = {"calls": 0, "compactions": 0, "boot_ctx": [], "tok": defaultdict(float), "cost": defaultdict(float),
              "ctx_tok": defaultdict(float), "ctx_cost": defaultdict(float),
              "ctx_cost_by_trigger": defaultdict(float), "out_by_trigger": defaultdict(float),
              "tool_cost": defaultdict(float), "rebuild": defaultdict(lambda: [0, 0.0])}
for p in paths:
    w = win(first_day(p))
    if w:
        try: ts.parse(p, acc[w])
        except Exception as e: print("skip", p.name, e, file=sys.stderr)
out = {}
for k, T in turns.items():
    days = sorted({t["ts"][:10] for t in T})
    n = len(T); cost = sum(t["cost"] for t in T); tok = sum(t["tokens"] for t in T)
    mon = [t for t in T if t["trigger"] == "monitor event"]
    hb = [t for t in T if "heartbeat" in t["trigger"]]
    na = [t for t in T if not t["acted"]]
    acted = n - len(na)
    a = acc[k]
    out[k] = {
        "window": f"{days[0]}..{days[-1]} ({len(days)} days)", "sessions": len({t['session'] for t in T}), "turns": n,
        "cost_per_turn_usd": round(cost / n, 3), "tokens_per_turn": round(tok / n),
        "cost_per_acted_turn_usd": round(cost / max(acted, 1), 3),
        "no_action_turn_share": round(len(na) / n, 3), "no_action_cost_share": round(sum(t["cost"] for t in na) / cost, 3),
        "monitor_turns_per_day": round(len(mon) / len(days), 1),
        "monitor_no_action_share": round(sum(1 for t in mon if not t["acted"]) / max(len(mon), 1), 3),
        "heartbeat_turns_per_day": round(len(hb) / len(days), 1),
        "boot_ctx_median": statistics.median(a["boot_ctx"]) if a["boot_ctx"] else None,
        "boot_ctx_p90": sorted(a["boot_ctx"])[int(len(a["boot_ctx"]) * .9)] if a["boot_ctx"] else None,
        "boot_sessions": len(a["boot_ctx"]),
        "cache_read_share_of_cost": round(a["cost"]["cache read"] / max(sum(a["cost"].values()), 1e-9), 3),
        "input_cost_share_by_content": {c: round(v / max(sum(a["ctx_cost"].values()), 1e-9), 3) for c, v in a["ctx_cost"].items()},
        "turns_per_active_day": round(n / len(days), 1),
        "days": {d: sum(1 for t in T if t["ts"][:10] == d) for d in days} if k == "after" else None,
        "triggers": {tr: sum(1 for t in T if t["trigger"] == tr) for tr in sorted({t["trigger"] for t in T})},
    }
print(json.dumps(out, indent=1))
