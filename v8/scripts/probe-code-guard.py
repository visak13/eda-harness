"""Probe the live `code` service's DNS-rebinding guard (s-03c7e9168b, criterion c-440655c23b).

    .venv\\Scripts\\python.exe scripts\\probe-code-guard.py [--port 9410] [--out <file.json>]

Sends, to 127.0.0.1:<port>, each of GET /, GET /vscode-remote-resource?path=<v8 FAQ> and a WebSocket
upgrade, once with a rebinding Host (evil.invalid:<port>, matching Origin) and once with the loopback
Host (and the port's own Origin for the WS). Also sends a board-Origin (:9400) WS upgrade, which the
guard allows and code-server itself refuses (ruling m-fc4a1fb6f8), and hits code-server's inner port
(from .run/code.json) directly with no cookie: that must meet the login page, not the workbench. Then
lists every TCP listener owned by a process running from the code-server install or by the guard.
Exit 0 when every hostile request is refused by the guard, every loopback one succeeds, only the
guard listens on the service port, and the inner port is behind code-server's login.
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
WS_TARGET = "/?reconnectionToken=probe&reconnection=false&skipWebSocketFrames=false"


def send(port: int, host: str, target: str, extra: list[str]) -> dict:
    raw = f"GET {target} HTTP/1.1\r\nHost: {host}\r\n" + "".join(h + "\r\n" for h in extra) + "\r\n"
    data = b""
    with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
        s.sendall(raw.encode())
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
    lines = head.split(b"\r\n")
    status = lines[0].decode("latin-1")
    loc = next((l.split(b":", 1)[1].strip().decode("latin-1") for l in lines if l.lower().startswith(b"location:")), "")
    return {"port": port, "host": host, "target": target[:80], "origin": next((h for h in extra if h.startswith("Origin")), ""),
            "status": status, "code": int(status.split(" ")[1]) if status.startswith("HTTP/") else 0, "location": loc,
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
        "elseif ($p.CommandLine -match '--bind-addr') {'code-server (inner, auth password)'} else {'other code-server child'}; "
        "'{0}:{1} pid {2} {3} {4}' -f $_.LocalAddress,$_.LocalPort,$_.OwningProcess,$p.Name,$kind }"
    )
    return subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=120).stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9410)
    ap.add_argument("--board-port", type=int, default=9400)
    ap.add_argument("--run-dir", default=str(V8 / ".run"))
    ap.add_argument("--out")
    a = ap.parse_args()
    p = a.port
    res = "/vscode-remote-resource?path=" + quote(FAQ.as_posix(), safe="/:")
    evil, good = f"evil.invalid:{p}", f"127.0.0.1:{p}"
    rows = {
        "hostile GET /": send(p, evil, "/", []),
        "hostile GET resource": send(p, evil, res, []),
        "hostile WS": send(p, evil, WS_TARGET, ws_headers(f"http://{evil}")),
        "hostile Origin WS (loopback Host)": send(p, good, WS_TARGET, ws_headers("http://evil.invalid:1")),
        "loopback GET /": send(p, good, "/", []),
        "loopback GET resource": send(p, good, res, []),
        "loopback WS (own Origin)": send(p, good, WS_TARGET, ws_headers(f"http://{good}")),
        "board-Origin WS": send(p, good, WS_TARGET, ws_headers(f"http://127.0.0.1:{a.board_port}")),
    }
    inner = json.loads((Path(a.run_dir) / "code.json").read_text(encoding="utf-8")).get("inner_port")
    if inner:
        rows["direct inner GET / (no cookie)"] = send(inner, f"127.0.0.1:{inner}", "/", [])
        rows["direct inner GET resource (no cookie)"] = send(inner, f"127.0.0.1:{inner}", res, [])
        rows["direct inner WS (no cookie)"] = send(inner, f"127.0.0.1:{inner}", WS_TARGET, ws_headers(f"http://127.0.0.1:{inner}"))
    lst = listeners()
    lines = lst.splitlines()
    checks = {
        "hostile refused by the guard": all(rows[k]["by_guard"] and rows[k]["code"] in (421, 403) for k in rows if k.startswith("hostile")),
        # / answers 302 to the last opened folder once one was opened, 200 before
        "loopback succeeds": rows["loopback GET /"]["code"] in (200, 302) and "login" not in rows["loopback GET /"]["location"]
                             and rows["loopback GET resource"]["code"] == 200 and rows["loopback WS (own Origin)"]["code"] == 101,
        "board-Origin WS passes the guard (code-server answers)": not rows["board-Origin WS"]["by_guard"],
        "only the guard listens on the service port": any(f":{p} " in l for l in lines) and all("guard" in l for l in lines if f":{p} " in l),
        "inner port meets the login wall": bool(inner) and rows["direct inner GET / (no cookie)"]["code"] == 302
                                           and "login" in rows["direct inner GET / (no cookie)"]["location"]
                                           and rows["direct inner GET resource (no cookie)"]["code"] != 200
                                           and rows["direct inner WS (no cookie)"]["code"] != 101,
    }
    for k, r in rows.items():
        print(f"{k:40} {r['status']:32} {'guard' if r['by_guard'] else 'code-server':12} {r['location'][:40]}")
    print(f"\ninner port (from code.json): {inner}\nTCP listeners of code-server processes and the guard:\n{lst}\n")
    for k, v in checks.items():
        print(f"{'PASS' if v else 'FAIL'}  {k}")
    if a.out:
        Path(a.out).write_text(json.dumps({"requests": rows, "inner_port": inner, "listeners": lines, "checks": checks}, indent=2), encoding="utf-8")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
