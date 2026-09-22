"""AppServer — `codex app-server` over stdio, newline-delimited JSON-RPC (codex-cli 0.156.0, pinned by
`codex app-server generate-ts --experimental`).

Threads: the READER parses stdout and resolves request futures itself (never blocks on seat state,
so a caller may wait for a response while holding a seat lock); notifications go to one DISPATCHER
thread in arrival order; server requests (`item/tool/call`, approvals) run on short worker threads
because a seat tool may take a while (Monitor holds its result for the start grace).

Every record in and out is mirrored to `<log_dir>/codex-seat.<handle>.jsonl` as
`{"ts", "dir": "in"|"out", "msg"}` — the parity oracle's capture source (`capture_codex`).
Rules: EDP8_TOKEN travels in env only (the edp8 MCP server reads it through `env_http_headers`);
`start()` asserts no secret value appears on argv.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path
from queue import Queue

SECRET_KEYS = ("EDP8_TOKEN", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CODEX_API_KEY")


def redactor(env: dict[str, str] | None) -> Callable[[str], str]:
    """A str → str that replaces every SECRET_KEYS value found in `env` with `<redacted:KEY>`: applied to
    everything this seat PERSISTS (RPC mirror, events log, extension log). The model still sees what a
    Claude seat would (a Monitor that echoes the token delivers it); only the files never hold it."""
    pairs = [(v, f"<redacted:{k}>") for k in SECRET_KEYS if (v := (env or {}).get(k)) and len(v) >= 6]

    def redact(s: str) -> str:
        for v, tag in pairs:
            if v in s:
                s = s.replace(v, tag)
        return s
    return redact


class RpcError(RuntimeError):
    def __init__(self, method: str, error: dict):
        super().__init__(f"{method}: {error.get('message', error)}")
        self.error = error


class AppServer:
    def __init__(self, argv: list[str], *, cwd: str, env: dict[str, str], log_path: str | os.PathLike[str],
                 on_notification: Callable[[str, dict], None] | None = None,
                 on_request: Callable[[str, dict], dict | None] | None = None,
                 creationflags: int = 0):
        self.argv = argv
        self.cwd = cwd
        self.env = env
        self.log_path = Path(log_path)
        self.on_notification = on_notification or (lambda _m, _p: None)
        self.on_request = on_request or (lambda _m, _p: None)
        self.creationflags = creationflags
        self.proc: subprocess.Popen[str] | None = None
        self._wlock = threading.Lock()
        self._llock = threading.Lock()
        self._next = 0
        self._futures: dict[int, tuple[str, Future]] = {}
        self._notes: Queue = Queue()
        self.last_output_ts = 0.0
        self.exit_code: int | None = None
        self.exited = threading.Event()
        self._redact = redactor(env)

    # ------------------------------------------------------------------ process
    def start(self) -> None:
        for k in SECRET_KEYS:
            v = self.env.get(k)
            assert not (v and any(v in a for a in self.argv)), f"{k} leaked into argv"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_f = open(self.log_path, "a", encoding="utf-8")
        self.proc = subprocess.Popen(
            self.argv, cwd=self.cwd, env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=open(self.log_path.with_suffix(".stderr.log"), "ab"), text=True, encoding="utf-8",
            errors="replace", bufsize=1, creationflags=self.creationflags)
        threading.Thread(target=self._read, name="codex-rpc-reader", daemon=True).start()
        threading.Thread(target=self._dispatch, name="codex-rpc-dispatch", daemon=True).start()

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    @property
    def pid(self) -> int | None:
        return self.proc.pid if self.proc else None

    def stop(self, grace: float = 5.0) -> None:
        if not self.alive():
            return
        assert self.proc
        try:
            self.proc.stdin.close()  # type: ignore[union-attr]
            self.proc.wait(timeout=grace)
        except Exception:  # noqa: BLE001
            pass
        if self.alive():
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True)
            else:
                self.proc.kill()

    # ------------------------------------------------------------------ io
    def _mirror(self, direction: str, msg: dict) -> None:
        with self._llock:
            line = json.dumps({"ts": time.time(), "dir": direction, "msg": msg}, ensure_ascii=False)
            self._log_f.write(self._redact(line).encode("utf-8", "replace").decode("utf-8") + "\n")
            self._log_f.flush()

    def _write(self, msg: dict) -> None:
        assert self.proc and self.proc.stdin
        line = json.dumps(msg)  # ASCII-escaped: a lone surrogate from a JS-style UTF-16 slice travels escaped, as JSON.stringify does
        with self._wlock:
            self.proc.stdin.write(line + "\n")
            self.proc.stdin.flush()
        self._mirror("out", msg)

    def _read(self) -> None:
        assert self.proc and self.proc.stdout
        for raw in self.proc.stdout:
            raw = raw.strip()
            if not raw:
                continue
            self.last_output_ts = time.time()
            try:
                msg = json.loads(raw)
            except ValueError:
                self._mirror("in", {"raw": raw})
                continue
            self._mirror("in", msg)
            if "method" in msg and "id" in msg:
                threading.Thread(target=self._serve, args=(msg,), daemon=True).start()
            elif "method" in msg:
                self._notes.put(msg)
            elif "id" in msg:
                ent = self._futures.pop(msg["id"], None)
                if ent:
                    method, fut = ent
                    if "error" in msg:
                        fut.set_exception(RpcError(method, msg["error"]))
                    else:
                        fut.set_result(msg.get("result"))
        self.exit_code = self.proc.wait()
        for method, fut in list(self._futures.values()):
            if not fut.done():
                fut.set_exception(RpcError(method, {"message": f"app-server exited {self.exit_code}"}))
        self._notes.put(None)
        self.exited.set()

    def _dispatch(self) -> None:
        while True:
            msg = self._notes.get()
            if msg is None:
                return
            try:
                self.on_notification(msg["method"], msg.get("params") or {})
            except Exception as e:  # noqa: BLE001 — a handler fault must not stop the dispatcher
                self._mirror("err", {"handler": msg["method"], "error": repr(e)})

    def _serve(self, msg: dict) -> None:
        try:
            result = self.on_request(msg["method"], msg.get("params") or {})
        except Exception as e:  # noqa: BLE001
            self._write({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32603, "message": repr(e)}})
            return
        if result is None:
            self._write({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": f"unsupported {msg['method']}"}})
        else:
            self._write({"jsonrpc": "2.0", "id": msg["id"], "result": result})

    # ------------------------------------------------------------------ calls
    def request_async(self, method: str, params: dict) -> Future:
        with self._wlock:
            self._next += 1
            rid = self._next
        fut: Future = Future()
        self._futures[rid] = (method, fut)
        self._write({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        return fut

    def request(self, method: str, params: dict, timeout: float = 60) -> dict:
        return self.request_async(method, params).result(timeout=timeout)

    def notify(self, method: str, params: dict | None = None) -> None:
        msg: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self._write(msg)
