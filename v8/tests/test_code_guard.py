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
    fwd, _ = check_head(head("Host: 127.0.0.1:9410", "X-Forwarded-Host: evil.invalid:9410", "Forwarded: host=evil"), 9410, ORIGINS)
    assert b"evil" not in fwd


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
