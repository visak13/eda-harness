"""A loopback capture proxy: forwards Claude Code's /v1/messages calls to the API and writes each request body's
size breakdown (system, tool definitions, messages) to a JSONL file. Used only to explain a first-call token
delta (S8); it never stores credentials (the Authorization header is dropped from the log) and runs on a spare
loopback port for the length of one measurement.

Usage: python capture_proxy.py --port 18999 --log <file.jsonl>      (stop with the PID that started it)
"""

from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

UPSTREAM = "https://api.anthropic.com"
LOG = {"path": "", "lock": threading.Lock()}


def breakdown(body: dict) -> dict:
    system = body.get("system")
    sys_chars = len(json.dumps(system)) if system is not None else 0
    tools = body.get("tools") or []
    msgs = body.get("messages") or []
    return {"model": body.get("model"), "system_chars": sys_chars, "n_tools": len(tools),
            "tools_chars": len(json.dumps(tools)),
            "tool_chars": {t.get("name", "?"): len(json.dumps(t)) for t in tools},
            "messages_chars": len(json.dumps(msgs)), "n_messages": len(msgs),
            "system_head": (json.dumps(system)[:200] if system is not None else "")}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if "/v1/messages" in self.path and "count_tokens" not in self.path:
            try:
                row = breakdown(json.loads(raw))
                with LOG["lock"]:
                    with open(LOG["path"], "a", encoding="utf-8") as f:
                        f.write(json.dumps(row) + "\n")
            except Exception as e:  # noqa: BLE001
                with LOG["lock"], open(LOG["path"], "a", encoding="utf-8") as f:
                    f.write(json.dumps({"error": str(e)}) + "\n")
        headers = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "content-length", "connection")}
        with httpx.Client(timeout=300) as c:
            r = c.post(UPSTREAM + self.path, content=raw, headers=headers)
        self.send_response(r.status_code)
        for k, v in r.headers.items():
            if k.lower() not in ("content-length", "transfer-encoding", "content-encoding", "connection"):
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(r.content)))
        self.end_headers()
        self.wfile.write(r.content)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--log", required=True)
    a = ap.parse_args()
    LOG["path"] = a.log
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
