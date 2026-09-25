"""Probe the live `code` service's DNS-rebinding guard (s-03c7e9168b, criterion c-440655c23b).

    .venv\\Scripts\\python.exe scripts\\probe-code-guard.py [--port 9410] [--out <file.json>]

Sends, to 127.0.0.1:<port>, each of GET /, GET /vscode-remote-resource?path=<v8 FAQ> and a WebSocket
upgrade, once with a rebinding Host (evil.invalid:<port>, matching Origin) and once with the loopback
Host (and the port's own Origin for the WS). Also sends a board-Origin (:9400) WS upgrade, which the
guard allows and code-server itself refuses (ruling m-fc4a1fb6f8). Then lists every TCP listener owned
by a process running from .tools\\code-server\\ or by the guard (Get-NetTCPConnection).
Exit 0 when every hostile request is refused by the guard, every loopback one succeeds, and no
code-server process listens on the service port.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

V8 = Path(__file__).resolve().parents[1]
FAQ = V8 / "guides" / "code-tab-faq.md"


def send(port: int, host: str, target: str, extra: list[str]) -> dict:
    raw = f"GET {target} HTTP/1.1\r\nHost: {host}\r\n" + "".join(h + "\r\n" for h in extra) + "\r\n"
    with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
        s.sendall(raw.encode())
        data = b""
        try:
            while b"\r\n\r\n" not in data or len(data) < 4096:
                chunk = s.recv(65536)
                if not chunk:
                    break
                data += chunk
                if data.startswith(b"HTTP/1.1 101") and b"\r\n\r\n" in data:
                    break
        except socket.timeout:
            pass
    head, _, body = data.partition(b"\r\n\r\n")
    status = head.split(b"\r\n", 1)[0].decode("latin-1")
    return {"host": host, "target": target[:80], "extra": [h for h in extra if h.startswith("Origin")],
            "status": status, "code": int(status.split(" ")[1]) if status.startswith("HTTP/") else 0,
            "by_guard": body.startswith(b"code guard:"), "body": body[:120].decode("utf-8", "replace")}


def ws_headers(origin: str) -> list[str]:
    key = base64.b64encode(os.urandom(16)).decode()
    return [f"Origin: {origin}", "Upgrade: websocket", "Connection: Upgrade",
            "Sec-WebSocket-Version: 13", f"Sec-WebSocket-Key: {key}"]


def listeners() -> str:
    ps = (
        "$procs=@{}; Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -like '*\\.tools\\code-server\\*' -or $_.CommandLine -match 'edp8\\.code_guard' } | "
        "ForEach-Object { $procs[[int]$_.ProcessId]=$_ }; "
        "Get-NetTCPConnection -State Listen | Where-Object { $procs.ContainsKey([int]$_.OwningProcess) } | ForEach-Object { "
        "$p=$procs[[int]$_.OwningProcess]; $kind = if ($p.CommandLine -match 'edp8\\.code_guard') {'guard'} "
        "elseif ($p.CommandLine -match 'type=extensionHost') {'extension host'} elseif ($p.CommandLine -match 'test-server') {'extension child (playwright test-server)'} "
        "elseif ($p.CommandLine -match '--socket') {'code-server'} else {'other code-server child'}; "
        "'{0}:{1} pid {2} {3} {4}' -f $_.LocalAddress,$_.LocalPort,$_.OwningProcess,$p.Name,$kind }"
    )
    return subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=120).stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9410)
    ap.add_argument("--board-port", type=int, default=9400)
    ap.add_argument("--out")
    a = ap.parse_args()
    p = a.port
    res = "/vscode-remote-resource?path=" + quote(FAQ.as_posix(), safe="/:")
    evil, good = f"evil.invalid:{p}", f"127.0.0.1:{p}"
    rows = {
        "hostile GET /": send(p, evil, "/", []),
        "hostile GET resource": send(p, evil, res, []),
        "hostile WS": send(p, evil, "/?reconnectionToken=probe&reconnection=false&skipWebSocketFrames=false", ws_headers(f"http://{evil}")),
        "hostile Origin WS (loopback Host)": send(p, good, "/?reconnectionToken=probe&reconnection=false&skipWebSocketFrames=false", ws_headers("http://evil.invalid:1")),
        "loopback GET /": send(p, good, "/", []),
        "loopback GET resource": send(p, good, res, []),
        "loopback WS (own Origin)": send(p, good, "/?reconnectionToken=probe&reconnection=false&skipWebSocketFrames=false", ws_headers(f"http://{good}")),
        "board-Origin WS": send(p, good, "/?reconnectionToken=probe&reconnection=false&skipWebSocketFrames=false", ws_headers(f"http://127.0.0.1:{a.board_port}")),
    }
    lst = listeners()
    checks = {
        "hostile refused by the guard": all(rows[k]["by_guard"] and rows[k]["code"] in (421, 403)
                                            for k in rows if k.startswith("hostile")),
        # / answers 302 to the last opened folder once one was opened, 200 before
        "loopback succeeds": rows["loopback GET /"]["code"] in (200, 302) and rows["loopback GET resource"]["code"] == 200
                             and rows["loopback WS (own Origin)"]["code"] == 101,
        "board-Origin WS passes the guard (code-server answers)": not rows["board-Origin WS"]["by_guard"],
        "only the guard listens on the port": all(("guard" in line) for line in lst.splitlines() if f":{p} " in line)
                                               and any(f":{p} " in line for line in lst.splitlines()),
        "no code-server HTTP listener on TCP": not any(line.endswith(" code-server") for line in lst.splitlines()),
    }
    for k, r in rows.items():
        print(f"{k:38} {r['status']:32} {'guard' if r['by_guard'] else 'code-server'}")
    print("\nTCP listeners of code-server processes and the guard:\n" + lst + "\n")
    for k, v in checks.items():
        print(f"{'PASS' if v else 'FAIL'}  {k}")
    if a.out:
        Path(a.out).write_text(json.dumps({"requests": rows, "listeners": lst.splitlines(), "checks": checks}, indent=2), encoding="utf-8")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
