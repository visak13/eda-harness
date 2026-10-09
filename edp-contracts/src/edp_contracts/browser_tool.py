"""The fleet's browser tool (t-732cf1dd92, owner m-7075155b20 / m-abc28b19b2 / m-3acae839e6): ONE shared Playwright
MCP service that the edp8 MCP server proxies (edp8.browser_proxy), so every seat on every harness (Claude, codex,
pi) gets the `browser_*` tools through its existing edp8 connection, with no per-harness config.

The package is installed ONCE, at the pinned version, under `<data>/tools/browser-mcp` (never `npx` at every spawn,
never the harness's plugin store, never ~/.claude or ~/.codex), by the first browser call, under a lock so
two callers cannot race. Its browser is the system Chrome when there is one, else a one-time chromium download.
Every failure raises :class:`BrowserToolError` naming the step, and the browser call fails with it: never a
silent skip.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from . import settings
from .toolpath import ToolMissing, require_tool, tool_argv

PACKAGE = "@playwright/mcp"
#: tools the proxy never serves: they act on the HOST (run arbitrary code in the server's node, read host files
#: for an upload), not on the page (architect m-b61ec43737: dropped, no flag)
DROPPED = frozenset({"browser_run_code_unsafe", "browser_file_upload"})
#: the service's own last-resort browser close (ms without a completed call); the proxy reaps an idle seat's
#: session at 30 min, so this only fires when the proxy is gone
IDLE_TIMEOUT_MS = 60 * 60 * 1000
_LOCK_STALE_S = 900


class BrowserToolError(RuntimeError):
    """The browser tool could not be made ready; `step` names what failed."""

    def __init__(self, step: str, detail: str):
        self.step = step
        super().__init__(f"browser tool: {step} failed: {detail}")


def enabled() -> bool:
    return bool(settings.get("EDP_BROWSER_MCP"))


def version() -> str:
    return str(settings.get("EDP_BROWSER_MCP_VERSION"))


def install_dir() -> Path:
    return settings.data_dir() / "tools" / "browser-mcp"


def _cli(d: Path) -> Path:
    return d / "node_modules" / "@playwright" / "mcp" / "cli.js"


def _stamp(d: Path) -> Path:
    return d / "ready.json"


def system_chrome() -> str | None:
    """Google Chrome's stable install, if any (the package's default browser channel)."""
    if sys.platform == "win32":
        roots = [settings.env_raw(v) for v in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]  # the declared os.* names
        cands = [Path(r) / "Google" / "Chrome" / "Application" / "chrome.exe" for r in roots if r]
    elif sys.platform == "darwin":
        cands = [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")]
    else:
        cands = [Path("/opt/google/chrome/chrome")]
    return next((str(c) for c in cands if c.is_file()), None)


def status() -> dict:
    """What the doctor shows; no side effects."""
    d = install_dir()
    try:
        stamp = json.loads(_stamp(d).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stamp = {}
    ready = stamp.get("version") == version() and _cli(d).is_file()
    return {"enabled": enabled(), "version": version(), "dir": str(d), "ready": ready,
            "browser": stamp.get("browser") if ready else None}


def _npm(node: str) -> list[str]:
    """npm ships next to node (Windows: npm.cmd); else npm on PATH."""
    near = Path(node).parent / ("npm.cmd" if sys.platform == "win32" else "npm")
    if near.is_file():
        return tool_argv(str(near))
    return tool_argv(require_tool("npm", key="EDP_NPM_BIN"))


def _run(step: str, argv: list[str], cwd: Path, timeout: int) -> None:
    from .proc import run_bounded
    try:
        r = run_bounded(argv, timeout, cwd=str(cwd))
    except OSError as e:
        raise BrowserToolError(step, str(e)) from e
    if r.timed_out:
        raise BrowserToolError(step, f"timed out after {timeout}s")
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "").strip().splitlines()[-6:]
        raise BrowserToolError(step, f"exit {r.returncode}: " + " | ".join(tail))


class _Lock:
    """A cross-process lock file (O_EXCL); one older than _LOCK_STALE_S is a crashed holder's and is taken over."""

    def __init__(self, path: Path, wait_s: float):
        self.path, self.wait_s = path, wait_s

    def __enter__(self) -> "_Lock":
        end = time.monotonic() + self.wait_s
        while True:
            try:
                os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > _LOCK_STALE_S:
                        self.path.unlink(missing_ok=True)
                        continue
                except OSError:
                    continue
                if time.monotonic() > end:
                    raise BrowserToolError("waiting for another caller's install",
                                           f"{self.path} held for over {int(self.wait_s)}s") from None
                time.sleep(0.5)

    def __exit__(self, *_a: object) -> None:
        self.path.unlink(missing_ok=True)


def ensure_installed(*, timeout: int = 900) -> dict:
    """Install the pinned package (and, with no system Chrome, its chromium) once; return the ready stamp."""
    d = install_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise BrowserToolError(f"creating {d}", str(e)) from e
    with _Lock(d / "install.lock", wait_s=timeout):
        st = status()
        if st["ready"]:
            return {"version": st["version"], "browser": st["browser"]}
        try:
            node = require_tool("node")
        except ToolMissing as e:
            raise BrowserToolError("finding node", str(e)) from e
        _run(f"npm install {PACKAGE}@{version()}",
             [*_npm(node), "install", "--prefix", str(d), "--no-audit", "--no-fund", "--save-exact",
              f"{PACKAGE}@{version()}"], d, timeout)
        if not _cli(d).is_file():
            raise BrowserToolError(f"npm install {PACKAGE}@{version()}", f"{_cli(d)} is missing after the install")
        browser = "chrome" if system_chrome() else "chromium"
        if browser == "chromium":
            pw = d / "node_modules" / "playwright" / "cli.js"
            _run("downloading chromium (no system Chrome)", [node, str(pw), "install", "chromium"], d, timeout)
        stamp = {"version": version(), "browser": browser}
        _stamp(d).write_text(json.dumps(stamp), encoding="utf-8")
        return stamp


def service_argv(port: int, out_dir: str | Path) -> list[str]:
    """The ONE shared Playwright MCP service (m-bb6902256d): streamable HTTP on a loopback port, headless, every
    client session in its own in-memory browser context (`--isolated`; contexts are never shared between HTTP
    sessions unless --shared-browser-context). The host check compares the whole Host header (host:port); its
    default is `localhost:<port>` only, which refused `127.0.0.1:<port>` (measured), so both are named. `--idle-timeout` is the last-resort close behind the
    proxy's own reaper (edp8.browser_proxy). Installs on first use."""
    stamp = ensure_installed()
    node = require_tool("node")
    return [node, str(_cli(install_dir())), "--port", str(int(port)), "--host", "127.0.0.1",
            "--allowed-hosts", f"127.0.0.1:{int(port)},localhost:{int(port)}", "--headless", "--isolated",
            "--browser", "chrome" if stamp.get("browser") == "chrome" else "chromium",
            "--idle-timeout", str(IDLE_TIMEOUT_MS), "--output-dir", str(out_dir)]
