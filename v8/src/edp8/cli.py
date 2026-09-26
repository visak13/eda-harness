"""The product CLI (`heronry`, alias `edp8`) — read-only operator view over the launcher's run-state
(design §22 rule 4). User-facing names come from `brand.py` (design-e963c656f5 §4.12).

`edp8 status` prints one row per shared service: pid, port, git rev, uptime, last probe and
last restart reason, read from `v8/.run/`. Seats read this to see infrastructure state without
touching a shared service; the launcher (`start.*`) and its supervisor own the services.
"""

from __future__ import annotations

import sys

from . import run_state
from .brand import CLI_NAME, PRODUCT_NAME, TAGLINE

_COLS = ["service", "state", "pid", "port", "git_rev", "uptime", "last_probe", "last_restart_reason"]
_HEAD = {"git_rev": "rev", "last_probe": "last probe", "last_restart_reason": "last restart"}


def _fmt(v: object) -> str:
    return "-" if v is None else str(v)


def status(_argv: list[str]) -> int:
    rows = run_state.snapshot()
    table = [[_HEAD.get(c, c) for c in _COLS]]
    table += [[_fmt(r.get(c)) for c in _COLS] for r in rows]
    widths = [max(len(row[i]) for row in table) for i in range(len(_COLS))]
    for n, row in enumerate(table):
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))
        if n == 0:
            print("  ".join("-" * widths[i] for i in range(len(_COLS))))
    down = [r["service"] for r in rows if r.get("state") == "down"]
    if down:
        print()  # the gap goes to stdout: an empty stderr line reads as a bare RemoteException in PowerShell 5.1
        print(f"down: {', '.join(down)} — the launcher's supervisor restarts these; "
              f"`start.* --restart <service>` to force one. Seats never start shared services (design §22).",
              file=sys.stderr)
    return 0


def _version_string() -> str:
    try:
        from importlib.metadata import version
        ver = version("edp8")  # the internal distribution name stays (R8b)
    except Exception:  # noqa: BLE001 — a source checkout without an install still answers
        ver = "unknown"
    return f"{PRODUCT_NAME} {ver}"


def version_cmd(_argv: list[str]) -> int:
    print(_version_string())
    return 0


def help_cmd(_argv: list[str]) -> int:
    print(f"{PRODUCT_NAME}: {TAGLINE}\n")
    print(f"usage: {CLI_NAME} <command>\n")
    print("commands:")
    print("  status     one row per service: pid, port, rev, uptime, last probe, last restart")
    print("  version    print the product name and version (also --version)")
    print("  help       this text (also --help, -h)")
    return 0


_COMMANDS = {"status": status, "version": version_cmd, "help": help_cmd}
_ALIASES = {"--version": "version", "-V": "version", "--help": "help", "-h": "help"}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "status"
    cmd = _ALIASES.get(cmd, cmd)
    fn = _COMMANDS.get(cmd)
    if fn is None:
        print(f"{CLI_NAME}: unknown command {cmd!r}. commands: {', '.join(_COMMANDS)}", file=sys.stderr)
        return 2
    return fn(argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
