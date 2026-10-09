"""The fleet's browser tool through edp8 (t-732cf1dd92, design m-bb6902256d, rulings m-b61ec43737).

ONE shared Playwright MCP service (edp_contracts.browser_tool.service_argv: streamable HTTP on a loopback port,
`--headless --isolated`) runs as a child of this MCP server process, started lazily by the first browser call, so
it is stopped and reaped with the mcp service (same process tree and Windows job). The edp8 MCP server lists its
`browser_*` tools (the pinned snapshot in browser_tools.json, minus browser_tool.DROPPED) to every agent role and
forwards each call here; Claude, codex and pi seats all reach them through their existing edp8 connection.

Isolation: each seat session (X-Session, the pool session id) gets its OWN upstream MCP session, and the service
gives each upstream session its own browser context, so two seats never share cookies or storage. An upstream
session ends when the seat's session ends (the board, on the dead transition, POSTs /browser/release/<session>),
or after IDLE_S without a call (the reaper), or, last of all, by the service's own --idle-timeout.

Sign-in (ruling 2a): on a `browser_navigate` whose URL origin EXACTLY equals the board UI's own origin (scheme,
host and port), the proxy puts the CALLING seat's own token into that page's sessionStorage with a
`browser_evaluate` it builds itself (the script re-checks location.origin, so a redirect elsewhere gets nothing),
discards that call's result, and reloads. The token is never logged, and every result is scrubbed of it.
"""
from __future__ import annotations

import json
import logging
import socket
import itertools
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import urlsplit

import httpx
from edp_contracts import browser_tool
from edp_contracts.proc import kill_popen, popen_service

from . import settings

log = logging.getLogger("edp8.browser_proxy")

#: an upstream session with no call for this long is closed (ruling 1b)
IDLE_S = 30 * 60
_REAP_EVERY_S = 60
_START_WAIT_S = 30
_CALL_TIMEOUT_S = 120
_SNAPSHOT = Path(__file__).with_name("browser_tools.json")
REDACTED = "<redacted>"


def _load_tools() -> list[dict[str, Any]]:
    data = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))
    return [t for t in data["tools"] if t["name"] not in browser_tool.DROPPED]


#: the proxied tools (name, description, inputSchema, annotations), in the service's own order
TOOLS: list[dict[str, Any]] = _load_tools()
TOOL_NAMES: frozenset[str] = frozenset(t["name"] for t in TOOLS)


def enabled() -> bool:
    """`tools.browser_mcp` (EDP_BROWSER_MCP) is the one off switch."""
    return browser_tool.enabled()


def admin_token() -> str | None:
    """The board's admin token as the board itself resolves it (settings.admin_token: env, config.toml, then the
    secrets file an install keeps it in), so the board's release notice and the MCP's release route agree; None
    when there is none, and the route then refuses every caller."""
    try:
        return settings.admin_token() or None
    except settings.SettingsError:
        return None


class BrowserError(RuntimeError):
    pass


class _Gone(Exception):
    """The service no longer knows this upstream session (it restarted, or closed it idle)."""


# ------------------------------------------------------------------------------------------ origins

_DEFAULT_PORT = {"http": 80, "https": 443}


def origin_of(url: str | None) -> str | None:
    """`scheme://host[:port]` as a browser's location.origin spells it (default port dropped), or None for a URL
    that is not plain http(s) (file:, data:, javascript:, one with user info, a bad port)."""
    try:
        u = urlsplit(str(url or "").strip())
        port = u.port
    except ValueError:
        return None
    if u.scheme.lower() not in _DEFAULT_PORT or not u.hostname or "@" in u.netloc:
        return None
    scheme, host = u.scheme.lower(), u.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    return f"{scheme}://{host}" if port in (None, _DEFAULT_PORT[scheme]) else f"{scheme}://{host}:{port}"


def board_origins() -> frozenset[str]:
    """The board UI's own origins: the board URL and, when set, its public URL (the same board, owner-facing)."""
    return frozenset(o for o in (origin_of(settings.get("EDP8_BOARD_URL")),
                                 origin_of(settings.get("EDP8_PUBLIC_URL") or None)) if o)


def session_key(participant: str | None, session: str | None) -> str:
    """The upstream session's key: the board-verified participant, then the seat's pool session id."""
    return f"{participant or '-'}|{session or '-'}"


def signin_function(origin: str, handle: str, token: str) -> str:
    """The `browser_evaluate` function the proxy builds: sets the UI's session keys only when the page is still on
    `origin` (a redirect elsewhere gets nothing); answers "set", "had" (already this seat) or "elsewhere"."""
    o, h, t = json.dumps(origin), json.dumps(handle), json.dumps(token)
    return ("() => { if (location.origin !== %s) return 'elsewhere'; "
            "if (sessionStorage.getItem('edp8.as') === %s && sessionStorage.getItem('edp8.token') === %s) "
            "return 'had'; sessionStorage.setItem('edp8.token', %s); sessionStorage.setItem('edp8.as', %s); "
            "return 'set'; }" % (o, h, t, t, h))


def bad_filename(args: dict[str, Any]) -> str | None:
    """A `filename` argument that could leave the service's output folder (absolute, a drive, `..`): the reason, or
    None. The service resolves a relative name against its working directory, which is that folder."""
    name = args.get("filename")
    if name is None:
        return None
    s = str(name)
    win, posix = PureWindowsPath(s), PurePosixPath(s.replace("\\", "/"))
    if not s.strip():
        return "filename is empty"
    if win.is_absolute() or win.drive or win.root or posix.is_absolute():
        return f"filename {s!r} is absolute: give a plain name; files land in the browser output folder"
    if ".." in posix.parts:
        return f"filename {s!r} climbs out with '..': give a plain name inside the browser output folder"
    return None


def scrub(result: dict[str, Any], secret: str | None) -> dict[str, Any]:
    """`result` with every occurrence of `secret` in its text replaced (a page, a console line or a network
    request listing could echo the seat's token)."""
    if not secret:
        return result
    out = []
    for c in result.get("content") or []:
        if c.get("type") == "text" and secret in (c.get("text") or ""):
            c = {**c, "text": c["text"].replace(secret, REDACTED)}
        out.append(c)
    res = {**result, "content": out}
    if "structuredContent" in res and secret in json.dumps(res["structuredContent"]):
        res["structuredContent"] = json.loads(json.dumps(res["structuredContent"]).replace(secret, REDACTED))
    return res


# ------------------------------------------------------------------------------------------ the service

class Service:
    """The shared Playwright MCP process: started on first use, restarted if it died, stopped with this one."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._port = 0
        self.generation = 0  # bumps on every (re)start: older upstream sessions are gone

    def _alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def url(self) -> str:
        with self._lock:
            if not self._alive():
                self._start()
            return f"http://127.0.0.1:{self._port}/mcp"

    def _start(self) -> None:
        port = int(settings.get("EDP_BROWSER_MCP_PORT") or 0) or _free_port()
        out = browser_tool.install_dir() / "out"
        argv = browser_tool.service_argv(port, out)  # installs on first use; BrowserToolError names the step
        out.mkdir(parents=True, exist_ok=True)
        logp = settings.logs_dir() / "browser-mcp.log"
        logp.parent.mkdir(parents=True, exist_ok=True)
        # cwd = the output folder: the service resolves an explicit filename (and confines file access) against its
        # working directory when no workspace roots are configured, so a screenshot never lands in the data root
        with open(logp, "ab") as fh:
            proc = popen_service(argv, cwd=str(out), stdout=fh, stderr=subprocess.STDOUT)
        end = time.monotonic() + _START_WAIT_S
        while time.monotonic() < end:
            if proc.poll() is not None:
                raise browser_tool.BrowserToolError(
                    "starting the browser service", f"exit {proc.returncode}; see {logp}")
            try:
                socket.create_connection(("127.0.0.1", port), 0.5).close()
                break
            except OSError:
                time.sleep(0.25)
        else:
            kill_popen(proc)
            raise browser_tool.BrowserToolError("starting the browser service",
                                                f"nothing listened on 127.0.0.1:{port} in {_START_WAIT_S}s")
        self._proc, self._port = proc, port
        self.generation += 1
        log.info("browser service up on 127.0.0.1:%s (pid %s)", port, proc.pid)

    def status(self) -> dict[str, Any]:
        return {"running": self._alive(), "port": self._port or None,
                "pid": self._proc.pid if self._alive() else None}

    def stop(self) -> None:
        with self._lock:
            if self._proc is not None:
                kill_popen(self._proc)
            self._proc = None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ------------------------------------------------------------------------------------------ the proxy

@dataclass
class _Upstream:
    sid: str
    generation: int
    last: float = field(default_factory=time.monotonic)
    lock: threading.Lock = field(default_factory=threading.Lock)


class BrowserProxy:
    """Seat session key → its own upstream MCP session on the shared service."""

    def __init__(self, service: Service | None = None, *, idle_s: float = IDLE_S,
                 origins: frozenset[str] | None = None, http: httpx.Client | None = None) -> None:
        self.service = service or Service()
        self.idle_s = idle_s
        self._origins = origins
        self._http = http or httpx.Client(timeout=_CALL_TIMEOUT_S)
        self._lock = threading.Lock()
        self._sessions: dict[str, _Upstream] = {}
        self._ids = itertools.count(1)
        self._reaper: threading.Thread | None = None
        self._stop = threading.Event()

    # -- wire
    def _rpc(self, method: str, params: dict | None, sid: str | None, *, notify: bool = False) -> dict | None:
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        if not notify:
            body["id"] = next(self._ids)
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if sid:
            headers["mcp-session-id"] = sid
        r = self._http.post(self.service.url(), headers=headers, json=body)
        if sid and r.status_code == 404:
            raise _Gone()
        if r.status_code >= 400:
            raise BrowserError(f"browser service {method}: HTTP {r.status_code} {r.text[:200]}")
        if notify or r.status_code == 202:
            return None
        msg = _parse(r)
        if msg.get("error"):
            raise BrowserError(f"browser service {method}: {msg['error'].get('message', msg['error'])}")
        msg["_sid"] = r.headers.get("mcp-session-id")
        return msg

    def _open(self) -> _Upstream:
        init = self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                        "clientInfo": {"name": "edp8-browser-proxy", "version": "1"}}, None)
        sid = (init or {}).get("_sid")
        if not sid:
            raise BrowserError("browser service initialize: no mcp-session-id (is it in stateless mode?)")
        self._rpc("notifications/initialized", None, sid, notify=True)
        return _Upstream(sid=sid, generation=self.service.generation)

    def _session(self, key: str) -> _Upstream:
        with self._lock:
            up = self._sessions.get(key)
        if up is not None and up.generation == self.service.generation:
            return up
        fresh = self._open()
        with self._lock:
            self._sessions[key] = fresh
        return fresh

    def _call(self, up: _Upstream, name: str, args: dict) -> dict:
        msg = self._rpc("tools/call", {"name": name, "arguments": args}, up.sid)
        return (msg or {}).get("result") or {"content": [], "isError": True}

    # -- API
    def call(self, key: str, name: str, args: dict | None, *, handle: str | None = None,
             token: str | None = None) -> dict:
        """One proxied tool call for the seat session `key`; an MCP CallToolResult dict, scrubbed of `token`."""
        if name not in TOOL_NAMES:
            return {"content": [{"type": "text", "text": f"{name} is not a browser tool here"}], "isError": True}
        args = dict(args or {})
        bad = bad_filename(args)
        if bad:
            return {"content": [{"type": "text", "text": bad}], "isError": True}
        for attempt in (0, 1):
            up = self._session(key)
            try:
                with up.lock:
                    up.last = time.monotonic()
                    result = self._call(up, name, args)
                    if name == "browser_navigate" and handle and token:
                        result = self._sign_in(up, args, result, handle, token)
                    up.last = time.monotonic()
                return scrub(result, token)
            except _Gone:
                with self._lock:
                    if self._sessions.get(key) is up:
                        del self._sessions[key]
                if attempt:
                    raise BrowserError("browser service lost the session twice")
        raise AssertionError("unreachable")

    def _sign_in(self, up: _Upstream, args: dict, result: dict, handle: str, token: str) -> dict:
        """Ruling 2a: only an exact board-UI origin, the seat's own token, the evaluate's result discarded."""
        origin = origin_of(args.get("url"))
        origins = self._origins if self._origins is not None else board_origins()
        if result.get("isError") or origin is None or origin not in origins:
            return result
        ev = self._call(up, "browser_evaluate", {"function": signin_function(origin, handle, token)})
        texts = " ".join(c.get("text") or "" for c in ev.get("content") or [] if c.get("type") == "text")
        del ev  # never returned, never logged: it echoes the script
        if '"set"' not in texts:
            return result  # already this seat, or the page left the board's origin
        return self._call(up, "browser_navigate", {"url": args["url"]})

    def release(self, key: str) -> bool:
        """Close `key`'s upstream session (its browser context goes with it)."""
        with self._lock:
            up = self._sessions.pop(key, None)
        if up is None:
            return False
        if up.generation == self.service.generation and self.service.status()["running"]:
            try:
                self._http.delete(self.service.url(), headers={"mcp-session-id": up.sid}, timeout=10)
            except httpx.HTTPError as e:
                log.warning("browser release of a session failed: %s", e)
        return True

    def release_session(self, session_id: str) -> int:
        """The board's session end (ruling 1a): close every upstream session of that pool session id."""
        with self._lock:
            keys = [k for k in self._sessions if k.partition("|")[2] == session_id]
        return sum(1 for k in keys if self.release(k))

    def reap(self, now: float | None = None) -> list[str]:
        """Release every session idle for idle_s or more; the keys released."""
        now = time.monotonic() if now is None else now
        with self._lock:
            idle = [k for k, up in self._sessions.items() if now - up.last >= self.idle_s and not up.lock.locked()]
        return [k for k in idle if self.release(k)]

    def sessions(self) -> list[str]:
        with self._lock:
            return list(self._sessions)

    def start_reaper(self, every_s: float = _REAP_EVERY_S) -> None:
        if self._reaper is not None:
            return

        def loop() -> None:
            while not self._stop.wait(every_s):
                try:
                    self.reap()
                except Exception as e:  # noqa: BLE001 - the reaper outlives one bad pass
                    log.warning("browser reaper pass failed: %s", e)

        self._reaper = threading.Thread(target=loop, name="browser-reaper", daemon=True)
        self._reaper.start()

    def close(self) -> None:
        self._stop.set()
        for k in self.sessions():
            self.release(k)
        self.service.stop()


def _parse(r: httpx.Response) -> dict:
    if "text/event-stream" in r.headers.get("content-type", ""):
        data = [ln[5:].strip() for ln in r.text.splitlines() if ln.startswith("data:")]
        if not data:
            raise BrowserError("browser service: empty event stream")
        return json.loads(data[-1])
    return r.json()


_proxy: BrowserProxy | None = None
_proxy_lock = threading.Lock()


def proxy() -> BrowserProxy:
    """This MCP server process's one proxy."""
    global _proxy
    with _proxy_lock:
        if _proxy is None:
            _proxy = BrowserProxy()
        return _proxy


def shutdown() -> None:
    global _proxy
    with _proxy_lock:
        p, _proxy = _proxy, None
    if p is not None:
        p.close()


def notify_session_end(session_id: str) -> None:
    """The board's half of ruling 1a: tell the MCP server a seat session ended, in the background (a slow or
    down MCP server never holds the board's session upsert)."""
    if not enabled() or not session_id:
        return
    url = f"{str(settings.get('EDP8_MCP_URL')).rstrip('/')}/browser/release/{session_id}"
    headers = {"X-Admin": admin_token() or ""}

    def post() -> None:
        try:
            httpx.post(url, headers=headers, timeout=5)
        except httpx.HTTPError as e:
            log.info("browser release for an ended session not delivered (%s); the idle reaper covers it", e)

    threading.Thread(target=post, name="browser-release", daemon=True).start()
