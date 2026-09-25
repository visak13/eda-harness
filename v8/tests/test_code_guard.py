"""s-03c7e9168b: the host-allowlist guard in front of code-server (edp8.code_guard)."""
import asyncio

import pytest

from edp8.code_guard import Guard, Refused, check_head

ORIGINS = {"http://127.0.0.1:9410", "http://localhost:9410", "http://127.0.0.1:9400"}


def head(*lines, target="/"):
    return (f"GET {target} HTTP/1.1\r\n" + "".join(l + "\r\n" for l in lines) + "\r\n").encode()


WS = ("Upgrade: websocket", "Connection: Upgrade", "Sec-WebSocket-Version: 13", "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==")


@pytest.mark.parametrize("host", ["127.0.0.1:9410", "localhost:9410", "LOCALHOST:9410"])
def test_loopback_host_passes(host):
    fwd, facts = check_head(head(f"Host: {host}"), 9410, ORIGINS)
    assert fwd.startswith(b"GET / HTTP/1.1") and not facts["ws"]


@pytest.mark.parametrize("hosts", [["evil.invalid:9410"], ["127.0.0.1"], ["127.0.0.1:9400"], ["[::1]:9410"], [],
                                   ["127.0.0.1:9410", "evil.invalid:9410"]])
def test_other_hosts_refused_421(hosts):
    with pytest.raises(Refused) as e:
        check_head(head(*[f"Host: {h}" for h in hosts]), 9410, ORIGINS)
    assert e.value.status == 421


def test_absolute_form_target_refused():
    with pytest.raises(Refused) as e:
        check_head(head("Host: 127.0.0.1:9410", target="http://evil.invalid:9410/"), 9410, ORIGINS)
    assert e.value.status == 400


@pytest.mark.parametrize("origin", ["http://127.0.0.1:9410", "http://localhost:9410", "http://127.0.0.1:9400"])
def test_ws_allowed_origins(origin):
    _, facts = check_head(head("Host: 127.0.0.1:9410", f"Origin: {origin}", *WS), 9410, ORIGINS)
    assert facts["ws"]


@pytest.mark.parametrize("origin", ["http://evil.invalid:9410", "null", "http://127.0.0.1:9411", "https://127.0.0.1:9410"])
def test_ws_hostile_origin_refused_403(origin):
    with pytest.raises(Refused) as e:
        check_head(head("Host: 127.0.0.1:9410", f"Origin: {origin}", *WS), 9410, ORIGINS)
    assert e.value.status == 403


def test_forwarded_headers_dropped():
    fwd, _ = check_head(head("Host: 127.0.0.1:9410", "X-Forwarded-Host: evil.invalid:9410", "Forwarded: host=evil",
                             "X-Forwarded-Prefix: /evil"), 9410, ORIGINS)
    assert b"evil" not in fwd


# second opinion 20260925T174116Z-b3066925: anything node could read differently is refused
@pytest.mark.parametrize("lines", [
    ("Upgrade: websocket", "Connection: xupgrade"),         # guard saw an upgrade, node plain HTTP
    ("Upgrade: websocket",),                                # Upgrade without the Connection token
    ("Connection: Upgrade",),                               # the token without Upgrade
    ("Upgrade: websocket", "Upgrade: h2c", "Connection: Upgrade"),
    ("Upgrade: h2c", "Connection: Upgrade"),
    ("Content-Length: 1", "Content-Length: 2"),
    ("Content-Length: 5", "Transfer-Encoding: chunked"),
    ("Transfer-Encoding: gzip, chunked",),
    ("Content-Length: +5",),
    ("Host : evil.invalid:9410",),                          # whitespace before the colon
    ("X-A: 1\nHost: evil.invalid:9410",),                  # a bare LF
    ("Upgrade: websocket", "Connection: Upgrade", "Content-Length: 3"),
])
def test_ambiguous_heads_refused_400(lines):
    with pytest.raises(Refused) as e:
        check_head(head("Host: 127.0.0.1:9410", *lines), 9410, ORIGINS)
    assert e.value.status == 400


def test_connection_tokens_read_across_headers():
    # "Connection: Upgrade" then "Connection: keep-alive" is still an upgrade: the Origin is checked
    with pytest.raises(Refused) as e:
        check_head(head("Host: 127.0.0.1:9410", "Origin: http://evil.invalid:1", "Upgrade: websocket",
                        "Connection: Upgrade", "Connection: keep-alive"), 9410, ORIGINS)
    assert e.value.status == 403
    _, facts = check_head(head("Host: 127.0.0.1:9410", "Upgrade: websocket", "Connection: keep-alive, Upgrade"), 9410, ORIGINS)
    assert facts["ws"]


def test_chunked_body_forces_close():
    fwd, facts = check_head(head("Host: 127.0.0.1:9410", "Transfer-Encoding: chunked", "Connection: keep-alive"), 9410, ORIGINS)
    assert facts["chunked"] and b"Connection: close" in fwd and b"keep-alive" not in fwd


def test_session_cookie_injected_and_client_session_replaced():
    fwd, _ = check_head(head("Host: 127.0.0.1:9410", "Cookie: a=1; code-server-session=forged; b=2"), 9410, ORIGINS, "s3cret")
    text = fwd.decode()
    assert "Cookie: a=1; b=2; code-server-session=s3cret" in text and "forged" not in text
    assert text.count("Cookie:") == 1
    fwd, _ = check_head(head("Host: 127.0.0.1:9410"), 9410, ORIGINS, "s3cret")
    assert b"Cookie: code-server-session=s3cret" in fwd


def test_no_session_leaves_cookies_alone():
    fwd, _ = check_head(head("Host: 127.0.0.1:9410", "Cookie: a=1"), 9410, ORIGINS)
    assert b"Cookie: a=1" in fwd and b"code-server-session" not in fwd


def test_refused_request_never_carries_the_secret():
    with pytest.raises(Refused) as e:
        check_head(head("Host: evil.invalid:9410"), 9410, ORIGINS, "s3cret")
    assert "s3cret" not in str(e.value.detail) and b"s3cret" not in __import__("edp8.code_guard", fromlist=["refusal"]).refusal(e.value)


# -- end to end through a live guard and a fake upstream ------------------------------------------

async def _fake_upstream(seen):
    async def serve(r, w):
        while True:
            try:
                h = await r.readuntil(b"\r\n\r\n")
            except asyncio.IncompleteReadError:
                break
            seen.append(h)
            for line in h.split(b"\r\n"):
                if line.lower().startswith(b"content-length:"):
                    await r.readexactly(int(line.split(b":")[1]))
            if h.startswith(b"GET /deny"):  # code-server refusing an upgrade, connection left open
                w.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
                await w.drain()
                continue
            if b"Upgrade: websocket" in h:
                w.write(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
                await w.drain()
                while data := await r.read(100):
                    w.write(data)  # echo after the upgrade
                    await w.drain()
                break
            w.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
            await w.drain()
        w.close()
    return await asyncio.start_server(serve, "127.0.0.1", 0)


async def _guarded(seen):
    up = await _fake_upstream(seen)
    uport = up.sockets[0].getsockname()[1]
    g = Guard(0, f"tcp:127.0.0.1:{uport}", ["http://127.0.0.1:9400"])
    ready = asyncio.Event()
    task = asyncio.create_task(g.serve(ready=ready))
    await ready.wait()
    return up, task, g.port


async def _roundtrip(port, raw, read_until=b"\r\n\r\n"):
    r, w = await asyncio.open_connection("127.0.0.1", port)
    w.write(raw)
    await w.drain()
    out = await asyncio.wait_for(r.read(4096), 5)
    return r, w, out


def test_e2e_hostile_http_and_ws_refused_allowed_relayed():
    async def run():
        seen = []
        up, task, port = await _guarded(seen)
        try:
            _, w, out = await _roundtrip(port, head("Host: evil.invalid:%d" % port))
            assert out.startswith(b"HTTP/1.1 421"); w.close()
            _, w, out = await _roundtrip(port, head(f"Host: evil.invalid:{port}", f"Origin: http://evil.invalid:{port}", *WS))
            assert out.startswith(b"HTTP/1.1 421"); w.close()
            _, w, out = await _roundtrip(port, head(f"Host: 127.0.0.1:{port}", "Origin: http://evil.invalid:1", *WS))
            assert out.startswith(b"HTTP/1.1 403"); w.close()
            assert seen == []  # nothing hostile reached code-server
            _, w, out = await _roundtrip(port, head(f"Host: 127.0.0.1:{port}"))
            assert out.startswith(b"HTTP/1.1 200"); w.close()
            r, w, out = await _roundtrip(port, head(f"Host: localhost:{port}", "Origin: http://127.0.0.1:9400", *WS))
            assert out.startswith(b"HTTP/1.1 101")
            w.write(b"frame"); await w.drain()
            assert await asyncio.wait_for(r.read(100), 5) == b"frame"
            w.close()
        finally:
            task.cancel(); up.close()
    asyncio.run(run())


def test_e2e_keepalive_second_request_is_checked():
    async def run():
        seen = []
        up, task, port = await _guarded(seen)
        try:
            r, w, out = await _roundtrip(port, head(f"Host: 127.0.0.1:{port}"))
            assert out.endswith(b"ok")
            w.write(head(f"Host: 127.0.0.1:{port}"))  # a good second request on the same connection
            await w.drain()
            assert (await asyncio.wait_for(r.read(4096), 5)).startswith(b"HTTP/1.1 200")
            w.write(head("Host: evil.invalid:1"))  # a hostile third one is cut off, never relayed
            await w.drain()
            assert await asyncio.wait_for(r.read(4096), 5) == b""
            assert len(seen) == 2
        finally:
            task.cancel(); up.close()
    asyncio.run(run())


def test_e2e_body_is_delimited_by_content_length():
    async def run():
        seen = []
        up, task, port = await _guarded(seen)
        try:
            body = b"GET / HTTP/1.1\r\nHost: evil.invalid:1\r\n\r\n"  # a body that looks like a request
            raw = (f"POST /x HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nContent-Length: {len(body)}\r\n\r\n").encode() + body
            r, w, out = await _roundtrip(port, raw)
            assert out.startswith(b"HTTP/1.1 200")
            assert len(seen) == 1  # the body was relayed as a body, not parsed as a second head
        finally:
            task.cancel(); up.close()
    asyncio.run(run())


def test_e2e_refused_upgrade_is_not_tunnelled():
    async def run():
        seen = []
        up, task, port = await _guarded(seen)
        try:
            r, w, out = await _roundtrip(port, head(f"Host: 127.0.0.1:{port}", *WS, target="/deny"))
            assert out.startswith(b"HTTP/1.1 403")
            w.write(head("Host: evil.invalid:1"))  # would reach code-server if the guard tunnelled
            await w.drain()
            await asyncio.sleep(0.5)
            assert len(seen) == 1
            w.close()
        finally:
            task.cancel(); up.close()
    asyncio.run(run())


def test_e2e_upgrade_mid_connection_cut_off():
    async def run():
        seen = []
        up, task, port = await _guarded(seen)
        try:
            r, w, out = await _roundtrip(port, head(f"Host: 127.0.0.1:{port}"))
            assert out.endswith(b"ok")
            w.write(head(f"Host: 127.0.0.1:{port}", *WS))
            await w.drain()
            assert await asyncio.wait_for(r.read(4096), 5) == b""
            assert len(seen) == 1
        finally:
            task.cancel(); up.close()
    asyncio.run(run())


def test_e2e_upstream_down_answers_502():
    async def run():
        g = Guard(0, r"pipe:\\.\pipe\edp-code-guard-test-absent", [])
        ready = asyncio.Event()
        task = asyncio.create_task(g.serve(ready=ready))
        await ready.wait()
        try:
            _, w, out = await _roundtrip(g.port, head(f"Host: 127.0.0.1:{g.port}"))
            assert out.startswith(b"HTTP/1.1 502")
        finally:
            task.cancel()
    asyncio.run(run())


# -- s-17c13096e5: the guard cookie, minted only through the board ---------------------------------

from edp8.code_guard import GUARD_COOKIE, mint_token, refusal, safe_next, verify_token  # noqa: E402

KEY = "k" * 64
GATE = "g" * 43


def test_token_single_use_expiry_and_signature():
    seen = {}
    tok, exp = mint_token(KEY, now=1000)
    assert exp == 1060
    assert verify_token(KEY, tok, seen, now=1001) is None
    assert verify_token(KEY, tok, seen, now=1002) == "token already used"
    tok2, _ = mint_token(KEY, now=1000)
    assert verify_token(KEY, tok2, seen, now=1061) == "expired token"
    assert verify_token("other" * 8, mint_token(KEY, now=1000)[0], seen, now=1001) == "bad token signature"
    long_lived, _ = mint_token(KEY, now=1000, ttl=3600)
    assert verify_token(KEY, long_lived, seen, now=1001) == "token lifetime too long"
    for bad in ["", "x", "1060.abc.def", tok.upper()]:
        assert verify_token(KEY, bad, seen, now=1001) == "malformed token"


@pytest.mark.parametrize("raw,ok", [(None, "/"), ("/", "/"), ("/?folder=/c:/x&payload=%5B%5D", "/?folder=/c:/x&payload=%5B%5D"),
                                    ("//evil.invalid/", None), ("/\\evil.invalid", None), ("http://evil.invalid/", None),
                                    ("/a b", None), ("/a\r\nSet-Cookie: x=1", None), ("evil", None)])
def test_safe_next(raw, ok):
    assert safe_next(raw) == ok


@pytest.mark.parametrize("extra", [(), ("Cookie: edp-code-guard=wrong",), ("Cookie: other=1",)])
def test_gate_refuses_without_the_cookie_even_with_forged_host_and_origin(extra):
    for lines in [("Host: 127.0.0.1:9410", "Origin: http://127.0.0.1:9410", *extra),
                  ("Host: 127.0.0.1:9410", "Origin: http://127.0.0.1:9410", *extra, *WS)]:
        with pytest.raises(Refused) as e:
            check_head(head(*lines), 9410, ORIGINS, "s3cret", GATE)
        assert e.value.status == 401 and b"s3cret" not in refusal(e.value)


def test_gate_passes_with_the_cookie_and_strips_it():
    fwd, facts = check_head(head("Host: 127.0.0.1:9410", f"Cookie: a=1; {GUARD_COOKIE}={GATE}; b=2"), 9410, ORIGINS, "s3cret", GATE)
    text = fwd.decode()
    assert "Cookie: a=1; b=2; code-server-session=s3cret" in text and GATE not in text and GUARD_COOKIE not in text
    _, facts = check_head(head("Host: 127.0.0.1:9410", f"Cookie: {GUARD_COOKIE}={GATE}", "Origin: http://127.0.0.1:9400", *WS),
                          9410, ORIGINS, "s3cret", GATE)
    assert facts["ws"]


def test_gate_healthz_passes_without_session():
    fwd, _ = check_head(head("Host: 127.0.0.1:9410", target="/healthz"), 9410, ORIGINS, "s3cret", GATE)
    assert b"s3cret" not in fwd
    for target in ["/healthz?x=1", "/healthz/../", "/healthzz"]:
        with pytest.raises(Refused) as e:
            check_head(head("Host: 127.0.0.1:9410", target=target), 9410, ORIGINS, "s3cret", GATE)
        assert e.value.status == 401


def test_gate_login_route_host_checked_and_plain_get():
    _, facts = check_head(head("Host: 127.0.0.1:9410", target="/__edp/login?t=x&next=/"), 9410, ORIGINS, "s3cret", GATE)
    assert facts["login"] == "t=x&next=/"
    with pytest.raises(Refused) as e:
        check_head(head("Host: evil.invalid:9410", target="/__edp/login?t=x"), 9410, ORIGINS, "s3cret", GATE)
    assert e.value.status == 421
    with pytest.raises(Refused) as e:
        check_head(head("Host: 127.0.0.1:9410", *WS, target="/__edp/login?t=x"), 9410, ORIGINS, "s3cret", GATE)
    assert e.value.status == 400


async def _gated(seen):
    up = await _fake_upstream(seen)
    uport = up.sockets[0].getsockname()[1]
    g = Guard(0, f"tcp:127.0.0.1:{uport}", ["http://127.0.0.1:9400"], "s3cret", KEY)
    ready = asyncio.Event()
    task = asyncio.create_task(g.serve(ready=ready))
    await ready.wait()
    return up, task, g


def _set_cookie(resp: bytes) -> str:
    line = next(l for l in resp.split(b"\r\n") if l.lower().startswith(b"set-cookie:"))
    return line.split(b":", 1)[1].strip().decode()


def test_e2e_gate_login_sets_cookie_then_relays_and_refuses_replay():
    async def run():
        seen = []
        up, task, g = await _gated(seen)
        port = g.port
        try:
            # no cookie: HTTP and WS refused 401 even with the guard's own Host/Origin; nothing relayed
            _, w, out = await _roundtrip(port, head(f"Host: 127.0.0.1:{port}", f"Origin: http://127.0.0.1:{port}"))
            assert out.startswith(b"HTTP/1.1 401"); w.close()
            _, w, out = await _roundtrip(port, head(f"Host: 127.0.0.1:{port}", f"Origin: http://127.0.0.1:{port}", *WS))
            assert out.startswith(b"HTTP/1.1 401"); w.close()
            assert seen == []
            # /healthz passes, without the session
            _, w, out = await _roundtrip(port, head(f"Host: 127.0.0.1:{port}", target="/healthz"))
            assert out.startswith(b"HTTP/1.1 200") and b"s3cret" not in seen[-1]; w.close()
            # login with a board-minted token: 302 to next + the cookie
            tok, _ = mint_token(KEY)
            _, w, out = await _roundtrip(port, head(f"Host: 127.0.0.1:{port}", target=f"/__edp/login?t={tok}&next=%2F%3Ffolder%3D%2Fc%3A%2Fx"))
            assert out.startswith(b"HTTP/1.1 302") and b"Location: /?folder=/c:/x\r\n" in out
            assert _set_cookie(out) == f"{GUARD_COOKIE}={g.gate}; Path=/; HttpOnly; SameSite=Strict"
            w.close()
            # replayed: 401, no cookie
            _, w, out = await _roundtrip(port, head(f"Host: 127.0.0.1:{port}", target=f"/__edp/login?t={tok}&next=/"))
            assert out.startswith(b"HTTP/1.1 401") and b"Set-Cookie" not in out; w.close()
            # with the cookie: relayed, session injected, guard cookie stripped
            n = len(seen)
            _, w, out = await _roundtrip(port, head(f"Host: 127.0.0.1:{port}", f"Cookie: {GUARD_COOKIE}={g.gate}"))
            assert out.startswith(b"HTTP/1.1 200") and len(seen) == n + 1
            assert b"code-server-session=s3cret" in seen[-1] and g.gate.encode() not in seen[-1]; w.close()
            _, w, out = await _roundtrip(port, head(f"Host: 127.0.0.1:{port}", f"Cookie: {GUARD_COOKIE}={g.gate}",
                                                    f"Origin: http://127.0.0.1:{port}", *WS))
            assert out.startswith(b"HTTP/1.1 101"); w.close()
        finally:
            task.cancel(); up.close()
    asyncio.run(run())


def test_e2e_gate_mid_connection_no_cookie_401_and_login_answered():
    async def run():
        seen = []
        up, task, g = await _gated(seen)
        port = g.port
        try:
            r, w, out = await _roundtrip(port, head(f"Host: 127.0.0.1:{port}", f"Cookie: {GUARD_COOKIE}={g.gate}"))
            assert out.endswith(b"ok")
            w.write(head(f"Host: 127.0.0.1:{port}"))  # the cookie dropped on a pooled connection
            await w.drain()
            assert (await asyncio.wait_for(r.read(4096), 5)).startswith(b"HTTP/1.1 401")
            assert len(seen) == 1
            r, w, out = await _roundtrip(port, head(f"Host: 127.0.0.1:{port}", f"Cookie: {GUARD_COOKIE}={g.gate}"))
            tok, _ = mint_token(KEY)
            w.write(head(f"Host: 127.0.0.1:{port}", target=f"/__edp/login?t={tok}"))
            await w.drain()
            out = await asyncio.wait_for(r.read(4096), 5)
            assert out.startswith(b"HTTP/1.1 302") and b"Location: /\r\n" in out
        finally:
            task.cancel(); up.close()
    asyncio.run(run())


def test_main_refuses_without_mint_key(monkeypatch):  # fail closed: no key, no guard
    from edp8 import code_guard
    monkeypatch.delenv("CODE_GUARD_MINT_KEY", raising=False)
    assert code_guard.main(["--port", "0", "--upstream", "tcp:127.0.0.1:1"]) == 2
