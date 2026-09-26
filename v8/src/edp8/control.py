"""The supervisor's loopback control port (strategyll-3b8f4033e0 §5; S3 builds it, S5's service-control
API and the `heronry` CLI call it).

Server rules (enforced):
* binds the literal ``127.0.0.1`` (never ``localhost``, never ``0.0.0.0``: public mode must not expose it);
* refuses a peer that is not loopback, a ``Host`` outside ``127.0.0.1:<port>``/``localhost:<port>`` (DNS
  rebinding), any request carrying ``Origin`` (no browser caller, the board's own SPA included), and an
  ``X-EDP-Control`` header that does not match the secret (``hmac.compare_digest``) — each with 403;
* answers only POST; any other method is 405.

The secret is rotated on every supervisor start into ``<run dir>/control.secret`` (private file, S1
``write_secret``) and never logged, put in config.toml or the settings API. The port is the setting
``EDP_CONTROL_PORT`` (0 = a free port); the one in use is recorded as ``control_port`` in the
supervisor's run record, which is where clients find it.
"""

from __future__ import annotations

import hmac
import json
import secrets
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from edp_contracts.settings.secrets import write_secret

from . import run_state, settings

HEADER = "X-EDP-Control"
SECRET_FILE = "control.secret"

#: (path, body) -> (status, json body). The supervisor supplies it.
Dispatch = Callable[[str, dict[str, Any]], tuple[int, dict[str, Any]]]


def secret_path() -> Path:
    return settings.run_dir() / SECRET_FILE


def rotate_secret() -> str:
    """A fresh secret for this supervisor start, in a file only this user can read."""
    tok = secrets.token_urlsafe(32)
    p = secret_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.unlink(missing_ok=True)
    write_secret(p, tok)
    return tok


def read_secret() -> str | None:
    try:
        return secret_path().read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def make_handler(token: str, port_ref: list[int], dispatch: Dispatch) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "heronry-control"

        def log_message(self, *_a: Any) -> None:  # never log requests (the header carries the secret)
            pass

        def _authorised(self) -> bool:
            if self.client_address[0] not in ("127.0.0.1", "::1"):
                return False
            host = self.headers.get("Host", "")
            if host not in {f"127.0.0.1:{port_ref[0]}", f"localhost:{port_ref[0]}"}:
                return False
            if "Origin" in self.headers:
                return False
            return hmac.compare_digest(self.headers.get(HEADER, "").encode(), token.encode())

        def _send(self, code: int, body: dict[str, Any]) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:  # noqa: N802
            if not self._authorised():
                self._send(403, {"ok": False, "error": "forbidden"})
                return
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}") if n else {}
                if not isinstance(body, dict):
                    raise ValueError("body is not an object")
            except ValueError as e:
                self._send(400, {"ok": False, "error": f"bad json: {e}"})
                return
            try:
                code, out = dispatch(self.path, body)
            except Exception as e:  # noqa: BLE001 — one line back to the caller, the server keeps serving
                code, out = 500, {"ok": False, "error": f"{type(e).__name__}: {e}"}
            self._send(code, out)

        def _405(self) -> None:
            self.send_response(405)
            self.send_header("Allow", "POST")
            self.send_header("Content-Length", "0")
            self.end_headers()

        do_GET = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _405  # noqa: N815

    return Handler


def serve(dispatch: Dispatch, *, port: int | None = None, token: str | None = None) -> tuple[ThreadingHTTPServer, int]:
    """Bind the control server (not yet serving: the caller runs ``serve_forever`` on a thread)."""
    tok = token or rotate_secret()
    want = settings.get("EDP_CONTROL_PORT") if port is None else port
    ref = [0]
    srv = ThreadingHTTPServer(("127.0.0.1", int(want or 0)), make_handler(tok, ref, dispatch))
    ref[0] = srv.server_address[1]
    srv.daemon_threads = True
    return srv, ref[0]


# ------------------------------------------------------------------------------------------ client

class ControlUnavailable(RuntimeError):
    """No supervisor control port for this home (not running, or no secret)."""


def endpoint() -> tuple[int, str]:
    rec = run_state.read("supervisor") or {}
    cport = rec.get("control_port")
    tok = read_secret()
    if not cport or not tok:
        raise ControlUnavailable("the supervisor's control port is not running for this home")
    return int(cport), tok


def call(path: str, body: dict[str, Any] | None = None, *, timeout: float = 180.0) -> dict[str, Any]:
    """POST to the supervisor's control port with its secret; returns the JSON answer (raises on 4xx/5xx
    with the server's error text)."""
    import httpx

    cport, tok = endpoint()
    try:
        r = httpx.post(f"http://127.0.0.1:{cport}{path}", json=body or {}, headers={HEADER: tok}, timeout=timeout)
    except httpx.HTTPError as e:
        raise ControlUnavailable(f"control port :{cport} unreachable: {e}") from e
    try:
        out = r.json()
    except ValueError:
        out = {"ok": False, "error": r.text}
    if r.status_code >= 400:
        raise RuntimeError(f"control {path} -> {r.status_code}: {out.get('error')}")
    return out
