"""A stand-in for code-server (S21 tests): no node, no download, the same contract the code service relies on.

    code_server_stub.py --bind-addr 127.0.0.1:<port> --auth password ... [--user-data-dir D --extensions-dir E]

* Serves ``GET /healthz`` 200 and ``/`` as the workbench only for the ``code-server-session`` cookie equal to
  ``$HASHED_PASSWORD`` (else 302 to ./login), like code-server's password auth.
* Deletes ``$HASHED_PASSWORD`` from its environment after reading it (code-server does), then starts a
  grandchild (a sleeper) so a stop must reach the whole tree.
* ``STUB_CODE_REPORT=<file>``: writes its argv, environment keys and the grandchild's pid there (JSON).
* CLI mode (``--install-extension`` / ``--list-extensions``): prints nothing and exits 0.
"""

from __future__ import annotations

import http.server
import json
import os
import subprocess
import sys


def main(argv: list[str]) -> int:
    if any(a in argv for a in ("--install-extension", "--list-extensions", "--uninstall-extension")):
        return 0
    bind = argv[argv.index("--bind-addr") + 1]
    host, port = bind.rsplit(":", 1)
    secret = os.environ.pop("HASHED_PASSWORD", "")
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3600)"], stdin=subprocess.DEVNULL)
    report = os.environ.get("STUB_CODE_REPORT")
    if report:
        with open(report, "w", encoding="utf-8") as f:
            json.dump({"argv": argv, "env": sorted(os.environ), "had_secret": bool(secret),
                       "proxy_uri": os.environ.get("VSCODE_PROXY_URI"), "grandchild": child.pid}, f)

    class H(http.server.BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes = b"", headers: dict[str, str] | None = None) -> None:
            self.send_response(code)
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path.startswith("/healthz"):
                self._send(200, b'{"status":"alive"}', {"Content-Type": "application/json"})
                return
            cookies = dict(c.strip().split("=", 1) for c in (self.headers.get("Cookie") or "").split(";") if "=" in c)
            if secret and cookies.get("code-server-session") == secret:
                self._send(200, b"<html>workbench</html>", {"Content-Type": "text/html"})
            else:
                self._send(302, b"", {"Location": "./login"})

        def log_message(self, *_a) -> None:
            pass

    http.server.ThreadingHTTPServer((host, int(port)), H).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
