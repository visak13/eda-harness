"""`edp8` CLI — read-only operator view over the launcher's run-state (design §22 rule 4).

`edp8 status` prints one row per shared service: pid, port, git rev, uptime, last probe and
last restart reason, read from `v8/.run/`. Seats read this to see infrastructure state without
touching a shared service; the launcher (`start.*`) and its supervisor own the services.
"""

from __future__ import annotations

import sys

from . import run_state

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


_COMMANDS = {"status": status}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "status"
    fn = _COMMANDS.get(cmd)
    if fn is None:
        print(f"edp8: unknown command {cmd!r}. commands: {', '.join(_COMMANDS)}", file=sys.stderr)
        return 2
    return fn(argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
