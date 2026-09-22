"""A scripted stand-in for `codex app-server` (stdio NDJSON JSON-RPC) for the codex seat tests.

Every turn's text is a tiny script, one directive per line:
    CALL <tool> <json-args>   the "model" calls a seat dynamic tool (server request item/tool/call)
    RUN <seconds>             a native commandExecution item runs for that long
    SAY <text>                an agentMessage item
Anything else is treated as a notification / cron prompt the "model" just reads. Steered input is
recorded as a userMessage item right after the native item in flight (as codex 0.156.0 does).
Every request/notification it receives is appended to $FAKE_APPSERVER_LOG as JSON lines, so a
test can read back exactly what the seat sent (turn/start inputs, steers, tool results).
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid

LOG = os.environ.get("FAKE_APPSERVER_LOG")
_w = threading.Lock()
_pending: dict[int, threading.Event] = {}
_results: dict[int, dict] = {}
_steers: list[str] = []
_next = [1000]
_turn = {"id": None}


def log(obj):
    if LOG:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj) + "\n")


def send(obj):
    with _w:
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()


def note(method, params):
    send({"jsonrpc": "2.0", "method": method, "params": params})


def server_request(method, params, timeout=30):
    _next[0] += 1
    rid = _next[0]
    ev = threading.Event()
    _pending[rid] = ev
    send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
    ev.wait(timeout)
    return _results.pop(rid, None)


def item(kind, **kw):
    return {"type": kind, "id": uuid.uuid4().hex, **kw}


def flush_steers(tid):
    while _steers:
        text = _steers.pop(0)
        it = item("userMessage", clientId=None, content=[{"type": "text", "text": text, "text_elements": []}])
        note("item/started", {"threadId": tid, "item": it})
        note("item/completed", {"threadId": tid, "item": it})


def run_turn(tid, turn_id, text):
    note("turn/started", {"threadId": tid, "turn": {"id": turn_id, "status": "inProgress", "items": []}})
    um = item("userMessage", clientId=None, content=[{"type": "text", "text": text, "text_elements": []}])
    note("item/completed", {"threadId": tid, "item": um})
    for line in text.splitlines():
        if line.startswith("CALL "):
            _, name, args = line.split(" ", 2)
            it = item("dynamicToolCall", namespace=None, tool=name, arguments=json.loads(args), status="inProgress")
            note("item/started", {"threadId": tid, "item": it})
            res = server_request("item/tool/call", {"threadId": tid, "turnId": turn_id, "callId": it["id"],
                                                    "namespace": None, "tool": name, "arguments": json.loads(args)})
            done = {**it, "status": "completed", "contentItems": (res or {}).get("contentItems"), "success": (res or {}).get("success")}
            note("item/completed", {"threadId": tid, "item": done})
            flush_steers(tid)
        elif line.startswith("RUN "):
            it = item("commandExecution", command=f"sleep {line[4:]}", status="inProgress")
            note("item/started", {"threadId": tid, "item": it})
            time.sleep(float(line[4:]))
            note("item/completed", {"threadId": tid, "item": {**it, "status": "completed"}})
            flush_steers(tid)
        elif line.startswith("SAY "):
            it = item("agentMessage", text=line[4:])
            note("item/completed", {"threadId": tid, "item": it})
    flush_steers(tid)
    _turn["id"] = None
    note("turn/completed", {"threadId": tid, "turn": {"id": turn_id, "status": "completed", "items": [], "error": None}})


def main():
    tid = None
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        msg = json.loads(raw)
        log(msg)
        if "method" not in msg:  # response to one of our server requests
            rid = msg.get("id")
            _results[rid] = msg.get("result") or {"error": msg.get("error")}
            ev = _pending.pop(rid, None)
            if ev:
                ev.set()
            continue
        m, p, rid = msg["method"], msg.get("params") or {}, msg.get("id")
        if rid is None:
            continue
        if m == "initialize":
            send({"jsonrpc": "2.0", "id": rid, "result": {"userAgent": "fake/0.156.0"}})
        elif m in ("thread/start", "thread/resume"):
            tid = p.get("threadId") or "thr-" + uuid.uuid4().hex[:8]
            send({"jsonrpc": "2.0", "id": rid, "result": {"thread": {"id": tid}}})
        elif m == "turn/start":
            if _turn["id"]:
                send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32600, "message": "turn already active"}})
                continue
            turn_id = "turn-" + uuid.uuid4().hex[:8]
            _turn["id"] = turn_id
            send({"jsonrpc": "2.0", "id": rid, "result": {"turn": {"id": turn_id, "status": "inProgress", "items": []}}})
            text = "\n".join(i.get("text", "") for i in p.get("input", []))
            threading.Thread(target=run_turn, args=(tid, turn_id, text), daemon=True).start()
        elif m == "turn/steer":
            if not _turn["id"] or p.get("expectedTurnId") != _turn["id"]:
                send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32600, "message": "no active turn"}})
                continue
            _steers.append("\n".join(i.get("text", "") for i in p.get("input", [])))
            send({"jsonrpc": "2.0", "id": rid, "result": {"turnId": _turn["id"]}})
        elif m == "mcpServerStatus/list":
            send({"jsonrpc": "2.0", "id": rid, "result": {"data": [
                {"name": "edp8", "runtimeStatus": "ready", "tools": {"whoami": {}}},
                {"name": "chrome-devtools", "runtimeStatus": None, "tools": {}},
            ]}})
        else:
            send({"jsonrpc": "2.0", "id": rid, "result": {}})


if __name__ == "__main__":
    main()
