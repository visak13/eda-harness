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
import secrets
import socket
import subprocess
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path
from queue import Queue

#: the loopback websocket's capability token (monitor mode): the TUI reads it by env NAME
WS_TOKEN_ENV = "EDP_CODEX_WS_TOKEN"
SECRET_KEYS = ("EDP8_TOKEN", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CODEX_API_KEY", WS_TOKEN_ENV)


def private_dir(path: Path) -> Path:
    """A directory only this user can open (codex refuses a non-private socket/token dir, measured)."""
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        user = os.environ.get("USERNAME") or ""
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:(OI)(CI)F"],
                       capture_output=True, check=True)
    else:
        os.chmod(path, 0o700)
    return path


def free_loopback_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


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


class ListenerNotOurs(RpcError):
    """The ws port is held by a process that is not this seat's app-server (fail-closed, never retried)."""


class AppServer:
    def __init__(self, argv: list[str], *, cwd: str, env: dict[str, str], log_path: str | os.PathLike[str],
                 on_notification: Callable[[str, dict], None] | None = None,
                 on_request: Callable[[str, dict], dict | None] | None = None,
                 creationflags: int = 0, ws: bool = False):
        self.argv = argv
        self.ws = ws  # monitor mode: listen on an authenticated loopback websocket the TUI also joins
        self.ws_url: str | None = None
        self.ws_token: str | None = None
        self._ws = None
        self._token_file: Path | None = None
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
        argv = self.argv
        if self.ws:
            argv = [*argv, *self._ws_listen_args()]
        # the ws token is for the TUI (and redaction); the app-server and the model's shell never hold it
        child_env = {k: v for k, v in self.env.items() if k != WS_TOKEN_ENV}
        self.proc = subprocess.Popen(
            argv, cwd=self.cwd, env=child_env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT if self.ws else subprocess.PIPE, text=True, encoding="utf-8",
            errors="replace", bufsize=1, creationflags=self.creationflags)
        if self.ws:  # stdout is the server's banner/log: redacted to the stderr sink like stderr
            threading.Thread(target=self._pump_stderr, args=(self.proc.stdout,), name="codex-rpc-log", daemon=True).start()
            self._ws_connect()
        else:
            threading.Thread(target=self._pump_stderr, name="codex-rpc-stderr", daemon=True).start()
        threading.Thread(target=self._read, name="codex-rpc-reader", daemon=True).start()
        threading.Thread(target=self._dispatch, name="codex-rpc-dispatch", daemon=True).start()

    def _ws_listen_args(self) -> list[str]:
        """`--listen ws://127.0.0.1:<free port>` behind a capability token: the token lives in a file in
        an owner-only dir (path on argv, value never) and in env under WS_TOKEN_ENV for the TUI."""
        port = free_loopback_port()
        self.ws_token = secrets.token_urlsafe(32)
        self.env = {**self.env, WS_TOKEN_ENV: self.ws_token}
        self._redact = redactor(self.env)
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "edp8-codex-seat"
        d = private_dir(base / f"{os.getpid()}-{time.time_ns() % 10**9}")
        self._token_file = d / "ws.token"
        self._token_file.write_text(self.ws_token, encoding="utf-8")
        self.ws_url = f"ws://127.0.0.1:{port}"
        return ["--listen", self.ws_url, "--ws-auth", "capability-token", "--ws-token-file", str(self._token_file)]

    def _ws_connect(self, timeout: float = 60.0) -> None:
        from .ws import WsClient
        assert self.proc and self.ws_url
        host, port = self.ws_url[len("ws://"):].rsplit(":", 1)
        end = time.time() + timeout
        last: Exception | None = None
        while time.time() < end and self.proc.poll() is None:
            try:
                self._ws = WsClient(host, int(port), self.ws_token, verify_peer=self._verify_listener)
                return
            except ListenerNotOurs:
                raise
            except ConnectionRefusedError as e:
                if "upgrade refused" in str(e):
                    raise  # a live listener that refuses our token is not a start-up race
                last = e
            except OSError as e:
                last = e
            time.sleep(0.2)
        raise RpcError("connect", {"message": f"app-server websocket {self.ws_url} unreachable: {last!r} "
                                              f"(exit {self.proc.poll()})"})

    def _verify_listener(self, sock: socket.socket) -> None:
        """The listener at the other end of `sock` must be our app-server (its pid or a descendant), or the
        token is never sent: the port was free when chosen, not reserved until the child bound it."""
        import psutil
        assert self.proc
        mine = sock.getsockname()[:2]
        peer = sock.getpeername()[:2]
        owner = None
        for c in psutil.net_connections(kind="tcp"):
            if c.laddr and c.raddr and tuple(c.laddr)[:2] == tuple(peer) and tuple(c.raddr)[:2] == tuple(mine):
                owner = c.pid
                break
        try:
            ours = {self.proc.pid, *(p.pid for p in psutil.Process(self.proc.pid).children(recursive=True))}
        except psutil.Error:
            ours = {self.proc.pid}
        if owner is None or owner not in ours:
            raise ListenerNotOurs("connect", {"message": f"{self.ws_url} is served by pid {owner}, not this seat's "
                                                        f"app-server {self.proc.pid}: the token was not sent"})

    def _cleanup_token(self) -> None:
        if self._token_file:
            try:
                self._token_file.unlink(missing_ok=True)
                self._token_file.parent.rmdir()
            except OSError:
                pass

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    @property
    def pid(self) -> int | None:
        return self.proc.pid if self.proc else None

    def stop(self, grace: float = 5.0) -> None:
        if not self.alive():
            return
        assert self.proc
        if self._ws is not None:
            self._ws.close()
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
        # a streamed delta is a fragment: a secret split across two of them survives per-line redaction,
        # so its text is persisted as a length only (the item/completed row carries the whole, redacted)
        p = msg.get("params")
        if str(msg.get("method", "")).lower().endswith("delta") and isinstance(p, dict) and isinstance(p.get("delta"), str):
            msg = {**msg, "params": {**p, "delta": f"<delta: {len(p['delta'])} chars, see item/completed>"}}
        with self._llock:
            line = json.dumps({"ts": time.time(), "dir": direction, "msg": msg}, ensure_ascii=False)
            self._log_f.write(self._redact(line).encode("utf-8", "replace").decode("utf-8") + "\n")
            self._log_f.flush()

    def _write(self, msg: dict) -> None:
        assert self.proc and self.proc.stdin
        line = json.dumps(msg)  # ASCII-escaped: a lone surrogate from a JS-style UTF-16 slice travels escaped, as JSON.stringify does
        with self._wlock:
            if self._ws is not None:
                self._ws.send_text(line)
            else:
                self.proc.stdin.write(line + "\n")
                self.proc.stdin.flush()
        self._mirror("out", msg)

    def _messages(self):
        """Raw JSON-RPC texts from the transport: stdout lines (stdio) or websocket text messages."""
        assert self.proc and self.proc.stdout
        if self._ws is None:
            yield from self.proc.stdout
            return
        while (text := self._ws.recv_text()) is not None:
            yield text

    def _read(self) -> None:
        assert self.proc and self.proc.stdout
        for raw in self._messages():
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
        if self._ws is not None and self.proc.poll() is None:
            try:  # the socket dropped under a live server: this seat has lost its thread, end it
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.stop(grace=0)
        self.exit_code = self.proc.wait()
        self._cleanup_token()
        for method, fut in list(self._futures.values()):
            if not fut.done():
                fut.set_exception(RpcError(method, {"message": f"app-server exited {self.exit_code}"}))
        self._notes.put(None)
        self.exited.set()

    def _pump_stderr(self, stream=None) -> None:
        """app-server stderr → `<mirror>.stderr.log`, line by line THROUGH the redactor (qa adversary #2:
        a raw file redirect let a secret the server logs reach disk)."""
        assert self.proc and (stream or self.proc.stderr)
        with open(self.log_path.with_suffix(".stderr.log"), "a", encoding="utf-8") as f:
            for line in stream or self.proc.stderr:
                f.write(self._redact(line))
                f.flush()

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
            reply = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32603, "message": repr(e)}}
        else:
            reply = ({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": f"unsupported {msg['method']}"}}
                     if result is None else {"jsonrpc": "2.0", "id": msg["id"], "result": result})
        try:
            self._write(reply)
        except (OSError, ValueError) as e:  # the app-server closed while a seat tool ran: nobody to answer
            self._mirror("err", {"reply_dropped": msg["id"], "error": repr(e)})

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
