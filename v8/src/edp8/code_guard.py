"""Host-allowlist guard in front of code-server (s-03c7e9168b, design-628b968271).

code-server has no hostname allowlist, so a DNS-rebinding page (``evil.example:9410`` resolving to
127.0.0.1) could read files and drive a terminal. Rebinding reaches ANY loopback TCP port, so the
guard owns the service port and code-server sits on a random inner 127.0.0.1 port with
``--auth password`` and a per-start secret (``$HASHED_PASSWORD``; code-server compares the session
cookie to it verbatim). The guard adds that cookie to every request it relays, so the owner never
sees a login, while a page that reaches the inner port directly meets the login wall. (A named pipe
was tried first: code-server hands each connection's socket to the extension host over IPC, which
Windows node cannot do for a pipe, ENOTSUP, m-9ef1667f16.) Each request is checked first:

- the request target is origin-form (``/...``), else 400;
- ``Host`` is exactly one of ``127.0.0.1:<port>`` / ``localhost:<port>``, else 421;
- a WebSocket upgrade's ``Origin`` (when sent) is one of the allowed origins (the guard's own two
  plus the board origins passed with ``--allow-origin``), else 403.

Client-sent ``X-Forwarded-*`` / ``Forwarded`` headers are dropped: code-server's origin check
prefers ``X-Forwarded-Host`` over ``Host``. Every request on a keep-alive connection is checked; a
body is delimited by ``Content-Length``, a chunked body turns the connection into ``Connection:
close`` (forwarded raw, nothing parsed after it). After an upgrade the bytes are relayed raw.

    CODE_GUARD_SESSION=<secret> python -m edp8.code_guard --port 9410 --upstream tcp:127.0.0.1:<inner> \\
        --allow-origin http://127.0.0.1:9400 [--tag <install dir>]

The secret comes only by environment and is removed from it at start; client-sent session cookies
are replaced, never forwarded.

``--tag`` is ignored; it puts the code-server install path in this process's command line, the
needle edp.ps1 uses to recognise the ``code`` service.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

MAX_HEAD = 64 * 1024
SESSION_COOKIE = "code-server-session"
SESSION_ENV = "CODE_GUARD_SESSION"
_DROP = {"x-forwarded-host", "x-forwarded-for", "x-forwarded-proto", "x-forwarded-port", "forwarded"}


class Refused(Exception):
    def __init__(self, status: int, reason: str, detail: str):
        super().__init__(detail)
        self.status, self.reason, self.detail = status, reason, detail


def allowed_hosts(port: int) -> set[str]:
    return {f"127.0.0.1:{port}", f"localhost:{port}"}


def allowed_origins(port: int, extra: list[str]) -> set[str]:
    return {f"http://{h}" for h in allowed_hosts(port)} | {o.rstrip("/").lower() for o in extra if o}


def check_head(head: bytes, port: int, origins: set[str], session: str | None = None) -> tuple[bytes, dict]:
    """Validate one request head; return the head to forward and facts about it.

    With ``session``, the forwarded head carries ``code-server-session=<session>`` in place of any
    session cookie the client sent (code-server's password login, supplied by the guard).
    Raises Refused for a request the guard must not relay.
    """
    try:
        text = head.decode("latin-1")
    except Exception:  # pragma: no cover - latin-1 decodes any byte
        raise Refused(400, "Bad Request", "undecodable head")
    lines = text.split("\r\n")
    parts = lines[0].split(" ")
    if len(parts) != 3 or not parts[2].startswith("HTTP/1."):
        raise Refused(400, "Bad Request", "malformed request line")
    target = parts[1]
    if not target.startswith("/"):
        raise Refused(400, "Bad Request", "only origin-form request targets are relayed")
    kept = [lines[0]]
    hosts, origin, upgrade, conn, length, chunked, cookies = [], None, False, "", 0, False, []
    for line in lines[1:]:
        if not line:
            continue
        if ":" not in line or line[0] in " \t":
            raise Refused(400, "Bad Request", "malformed header line")
        name, value = line.split(":", 1)
        key, value = name.strip().lower(), value.strip()
        if key in _DROP:
            continue
        if key == "host":
            hosts.append(value.lower())
        elif key == "origin":
            if origin is not None:
                raise Refused(403, "Forbidden", "more than one Origin")
            origin = value.lower()
        elif key == "upgrade":
            upgrade = value.lower() == "websocket" or upgrade
        elif key == "connection":
            conn = value.lower()
        elif key == "content-length":
            try:
                length = int(value)
            except ValueError:
                raise Refused(400, "Bad Request", "bad Content-Length")
            if length < 0:
                raise Refused(400, "Bad Request", "bad Content-Length")
        elif key == "transfer-encoding":
            chunked = True
        elif key == "cookie" and session is not None:
            cookies += [c.strip() for c in value.split(";")
                        if c.strip() and not c.strip().lower().startswith(SESSION_COOKIE)]
            continue
        kept.append(line)
    if session is not None:
        kept.append("Cookie: " + "; ".join(cookies + [f"{SESSION_COOKIE}={session}"]))
    if len(hosts) != 1 or hosts[0] not in allowed_hosts(port):
        raise Refused(421, "Misdirected Request", f"Host {hosts!r} is not 127.0.0.1:{port} or localhost:{port}")
    is_ws = upgrade and "upgrade" in conn
    if is_ws and origin is not None and origin not in origins:
        raise Refused(403, "Forbidden", f"WebSocket Origin {origin!r} is not allowed")
    if chunked and not is_ws:
        kept = [k for k in kept if not k.lower().startswith("connection:")] + ["Connection: close"]
    out = ("\r\n".join(kept) + "\r\n\r\n").encode("latin-1")
    return out, {"ws": is_ws, "length": length, "chunked": chunked}


def refusal(r: Refused) -> bytes:
    body = f"code guard: {r.detail}\n".encode()
    return (f"HTTP/1.1 {r.status} {r.reason}\r\nContent-Type: text/plain; charset=utf-8\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n").encode() + body


async def open_upstream(spec: str):
    kind, _, addr = spec.partition(":")
    if kind == "tcp":
        host, _, p = addr.rpartition(":")
        return await asyncio.open_connection(host, int(p))
    if kind == "pipe":
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader(limit=MAX_HEAD)
        proto = asyncio.StreamReaderProtocol(reader)
        tr, _ = await loop.create_pipe_connection(lambda: proto, addr)
        return reader, asyncio.StreamWriter(tr, proto, reader, loop)
    raise ValueError(f"unknown upstream {spec!r} (tcp:host:port | pipe:\\\\.\\pipe\\name)")


async def _pump(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
    try:
        while data := await src.read(65536):
            dst.write(data)
            await dst.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        try:
            dst.write_eof() if dst.can_write_eof() else dst.close()
        except (OSError, RuntimeError):
            pass


async def _read_head(reader: asyncio.StreamReader) -> bytes | None:
    try:
        return await reader.readuntil(b"\r\n\r\n")
    except asyncio.IncompleteReadError as e:
        if e.partial.strip():
            raise Refused(400, "Bad Request", "truncated request head")
        return None
    except asyncio.LimitOverrunError:
        raise Refused(431, "Request Header Fields Too Large", "request head over 64 KiB")


class Guard:
    def __init__(self, port: int, upstream: str, extra_origins: list[str], session: str | None = None):
        self.port, self.upstream, self.extra, self.session = port, upstream, extra_origins, session
        self.origins = allowed_origins(port, extra_origins)

    async def handle(self, creader: asyncio.StreamReader, cwriter: asyncio.StreamWriter) -> None:
        uwriter = None
        tasks: list[asyncio.Task] = []
        try:
            head = await _read_head(creader)
            if head is None:
                return
            fwd, facts = check_head(head, self.port, self.origins, self.session)
            ureader, uwriter = await open_upstream(self.upstream)
            # responses flow back raw; requests are checked one head at a time
            tasks.append(asyncio.create_task(_pump(ureader, cwriter)))
            while True:
                uwriter.write(fwd)
                await uwriter.drain()
                if facts["ws"] or facts["chunked"]:
                    await _pump(creader, uwriter)
                    break
                left = facts["length"]
                while left > 0:
                    data = await creader.read(min(left, 65536))
                    if not data:
                        break
                    left -= len(data)
                    uwriter.write(data)
                    await uwriter.drain()
                head = await _read_head(creader)
                if head is None:
                    break
                try:
                    fwd, facts = check_head(head, self.port, self.origins, self.session)
                except Refused as r:
                    # a browser never changes Host on a pooled connection; anything that does is
                    # cut off: the refused request is never relayed and the connection closes
                    _log(f"refused {r.status} mid-connection: {r.detail}")
                    return
            await asyncio.wait(tasks)
        except Refused as r:
            _log(f"refused {r.status}: {r.detail}")
            try:
                cwriter.write(refusal(r))
                await cwriter.drain()
            except (ConnectionError, OSError):
                pass
        except (ConnectionError, OSError) as e:
            if uwriter is None:
                try:
                    body = f"code guard: code-server unreachable ({e.__class__.__name__})\n".encode()
                    cwriter.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Type: text/plain\r\nContent-Length: "
                                  + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)
                    await cwriter.drain()
                except (ConnectionError, OSError):
                    pass
        finally:
            for t in tasks:
                t.cancel()
            for w in (uwriter, cwriter):
                if w is not None:
                    try:
                        w.close()
                    except (OSError, RuntimeError):
                        pass

    async def serve(self, host: str = "127.0.0.1", ready=None) -> None:
        server = await asyncio.start_server(self.handle, host, self.port, limit=MAX_HEAD)
        if self.port == 0:
            self.port = server.sockets[0].getsockname()[1]
            self.origins = allowed_origins(self.port, self.extra)
        _log(f"listening on {host}:{self.port} -> {self.upstream}; ws origins {sorted(self.origins)}")
        if ready is not None:
            ready.set()
        async with server:
            await server.serve_forever()


def _log(msg: str) -> None:
    print(f"code_guard: {msg}", file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="edp8.code_guard")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--upstream", required=True)
    ap.add_argument("--allow-origin", action="append", default=[])
    ap.add_argument("--tag", default="")
    a = ap.parse_args(argv)
    # the session secret comes by environment (never argv, which any local process can list) and
    # leaves it at once
    session = os.environ.pop(SESSION_ENV, None) or None
    try:
        asyncio.run(Guard(a.port, a.upstream, a.allow_origin, session).serve())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
