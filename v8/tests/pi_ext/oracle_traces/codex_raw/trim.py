"""Trim a live codex-seat mirror to what capture_codex reads (no rate-limit/reasoning noise), for the fixture.

    python tests/pi_ext/oracle_traces/codex_raw/trim.py <codex-seat.cases.jsonl> > codex-seat.cases.jsonl
"""
import json
import sys

KEEP = ("item/tool/call", "item/started", "turn/start", "turn/steer")
NATIVE = ("commandExecution", "fileChange", "mcpToolCall", "webSearch", "imageView", "dynamicToolCall")

rows = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8") if line.strip()]
wanted = {r["msg"].get("id") for r in rows if r["dir"] == "out" and r["msg"].get("method") in ("turn/start", "turn/steer")}
for r in rows:
    m, meth = r["msg"], r["msg"].get("method")
    if meth in ("item/started", "item/completed"):
        it = m["params"].get("item", {})
        if it.get("type") == "userMessage" and meth == "item/started":  # the steer's receiving witness
            m = {"method": meth, "params": {"item": {"type": "userMessage", "clientId": it.get("clientId")}}}
        elif it.get("type") in NATIVE:
            m = {"method": meth, "params": {"item": {"type": it.get("type"), "server": it.get("server"), "tool": it.get("tool")}}}
        else:
            continue
    elif meth in KEEP:
        pass
    elif r["dir"] == "out" and meth is None and isinstance(m.get("result"), dict) and "contentItems" in m["result"]:
        pass  # our dynamic-tool results
    elif r["dir"] == "in" and meth is None and m.get("id") in wanted:
        m = {"id": m["id"], **({"result": {}} if "result" in m else {"error": m.get("error")})}  # accepted / refused
    else:
        continue
    print(json.dumps({"ts": r["ts"], "dir": r["dir"], "msg": m}, ensure_ascii=False))
