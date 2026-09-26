"""The product CLI, `heronry` (alias `edp8`): the cmd layer over the one launcher (design-e963c656f5 §4.4,
S3 s-870e401942). User-facing names come from `brand.py` (§4.12).

    heronry init      dirs, config.toml, tokens, agent home, harness choice, claude folder trust
    heronry start|stop|restart [svc|all]    services through `edp8.launcher` (+ the supervisor)
    heronry status    one row per service: state, pid, port, url, rev, uptime, last probe, last restart
    heronry doctor    prerequisites, harnesses (with install links), ports, secrets, trust
    heronry update    check GitHub Releases; apply = compat check, DB backup, stop, reinstall, start
    heronry import --from <v8 dir>   copy an existing v8 state (dry run first; the source is never written)
    heronry gui       the desktop app (S8)
    heronry version

`--heronry-service <svc>` is the frozen bundle's service re-entry (strategyhl-5af811e7bd §3): it runs that
service's module and nothing else, before anything GUI-related is imported.
"""

from __future__ import annotations

import sys

#: frozen-bundle re-entry: service name -> module run as __main__
_SERVICE_MODULES = {"board": "edp8.service", "broker": "edp_broker.main", "pool": "edp_pool.main",
                    "mcp": "edp8.mcp_server", "bridge": "edp8.slack_bridge", "supervisor": "edp8.supervisor"}
SERVICE_FLAG = "--heronry-service"


def _run_service(name: str) -> int:
    import runpy
    mod = _SERVICE_MODULES.get(name)
    if mod is None:
        print(f"unknown service {name!r}", file=sys.stderr)
        return 2
    sys.argv = [mod]
    runpy.run_module(mod, run_name="__main__", alter_sys=True)
    return 0


# ------------------------------------------------------------------------------------------ helpers

def _fmt(v: object) -> str:
    return "-" if v is None or v == "" else str(v)


def _table(rows: list[dict], cols: list[str], head: dict[str, str]) -> None:
    table = [[head.get(c, c) for c in cols]]
    table += [[_fmt(r.get(c)) for c in cols] for r in rows]
    widths = [max(len(row[i]) for row in table) for i in range(len(cols))]
    for n, row in enumerate(table):
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
        if n == 0:
            print("  ".join("-" * widths[i] for i in range(len(cols))))


def load_dotenv() -> None:
    """Dev mode keeps today's one `.env` in the home (v8/.env): its values join the environment unless
    the environment already has them (the old launchers' rule; a key set twice: the last line wins)."""
    from . import settings
    home = settings.home()
    if home is None:
        return
    f = home / ".env"
    try:
        lines = f.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return
    values: dict[str, str] = {}
    for line in lines:
        t = line.strip()
        if not t or t.startswith("#") or "=" not in t:
            continue
        k, v = t.split("=", 1)
        v = v.split(" #", 1)[0].split("\t#", 1)[0].strip()
        values[k.strip()] = v
    import os
    for k, v in values.items():
        if not os.environ.get(k):
            settings.set_env(k, v)


def _split(argv: list[str]) -> tuple[list[str], dict[str, str | bool]]:
    """Positional args and --flags (`--x v`, `--x=v`, bare `--x` = True)."""
    pos: list[str] = []
    opts: dict[str, str | bool] = {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            k = a[2:]
            if "=" in k:
                k, v = k.split("=", 1)
                opts[k] = v
            elif i + 1 < len(argv) and not argv[i + 1].startswith("--") and k in _VALUED:
                opts[k] = argv[i + 1]
                i += 1
            else:
                opts[k] = True
        elif a == "-f":
            opts["force"] = True
        else:
            pos.append(a)
        i += 1
    return pos, opts


#: flags that take a value (everything else is a switch)
_VALUED = {"harness", "owner", "admin-token", "from", "board-port", "mcp-port", "pool-port", "broker-port",
           "version", "spec", "db", "by", "timeout", "release-url", "agent-home-source"}


def _targets(pos: list[str]) -> list[str]:
    from . import launcher
    want = pos[0] if pos else "all"
    if want == "all":
        return list(launcher.ORDER)
    if want not in launcher.ORDER:
        raise SystemExit(f"unknown service {want!r} (board|broker|pool|mcp|bridge|all)")
    return [want]


# ------------------------------------------------------------------------------------------ status

_COLS = ["service", "state", "pid", "port", "url", "git_rev", "uptime", "last_probe", "last_restart_reason"]
_HEAD = {"git_rev": "rev", "last_probe": "last probe", "last_restart_reason": "last restart"}


def status(argv: list[str]) -> int:
    from . import launcher
    _, opts = _split(argv)
    rows = launcher.status_rows()
    if opts.get("json"):
        print(launcher.dumps(rows))
        return 0
    _table(rows, _COLS, _HEAD)
    down = [r["service"] for r in rows if r.get("state") == "down" and r["service"] != "bridge"]
    if down:
        print()  # the gap goes to stdout: an empty stderr line reads as a bare RemoteException in PowerShell 5.1
        print(f"down: {', '.join(down)} — `heronry start` starts them (the supervisor restarts a crashed one). "
              f"Seats never start shared services (design §22).", file=sys.stderr)
    return 0


# ------------------------------------------------------------------------------------------ start/stop

def _via_control(path: str, body: dict) -> dict | None:
    """Ask the running supervisor (it records the action and will not fight it); None when none runs."""
    from . import control, launcher
    if not launcher.supervisor_running():
        return None
    try:
        return control.call(path, body)
    except control.ControlUnavailable:
        return None


def start(argv: list[str]) -> int:
    from . import launcher
    pos, opts = _split(argv)
    rc = 0
    for svc in _targets(pos):
        try:
            out = _via_control(f"/services/{svc}/start", {"by": _who()}) or launcher.start(svc)
        except Exception as e:  # noqa: BLE001
            print(f"{svc:<8} FAILED  {e}", file=sys.stderr)
            rc = 1
            continue
        _say(out)
    if not opts.get("no-supervisor") and rc == 0:
        try:
            _say(launcher.ensure_supervisor())
        except Exception as e:  # noqa: BLE001
            print(f"supervisor FAILED  {e}", file=sys.stderr)
            rc = 1
    return rc


def _say(out: dict) -> None:
    svc, state = out.get("service"), out.get("state")
    text = {"already_running": "already running", "started": "started", "stopped": "stopped",
            "not_running": "not running", "skipped": "skipped", "restarted": "restarted"}.get(str(state), str(state))
    tail = []
    if out.get("pid"):
        tail.append(f"pid {out['pid']}")
    if out.get("url"):
        tail.append(str(out["url"]))
    if out.get("reason"):
        tail.append(f"({out['reason']})")
    print(f"{svc:<10} {text:<16} {'  '.join(tail)}".rstrip())


def _who() -> str:
    import getpass
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001
        return "cli"


def _pool_guard(verb: str, force: bool) -> bool:
    from . import launcher
    seats = launcher.live_seats()
    if seats is None:
        seats = ["<pool did not answer: seat list unknown>"]
    if not seats:
        return True
    print(f"pool {verb} takes these {len(seats)} seat(s) offline:")
    for s in seats:
        print(f"  - {s}")
    if not force:
        print(f"refusing to {verb} the pool without --force", file=sys.stderr)
        return False
    return True


def stop(argv: list[str]) -> int:
    from . import launcher
    pos, opts = _split(argv)
    force = bool(opts.get("force"))
    targets = _targets(pos)
    if "pool" in targets and not _pool_guard("stop", force):
        return 3
    rc = 0
    everything = not pos or pos[0] == "all"
    if everything:  # the supervisor goes first, so nothing is restarted behind our back
        _say(launcher.stop_supervisor())
    for svc in reversed(targets):
        out = None if everything else _via_control(f"/services/{svc}/stop", {"by": _who(), "force": force})
        out = out or launcher.stop(svc)
        _say(out)
        if out.get("survivors"):
            print(f"{svc}: still running {out['survivors']}", file=sys.stderr)
            rc = 1
    return rc


def restart(argv: list[str]) -> int:
    from . import launcher, supervisor
    pos, opts = _split(argv)
    force = bool(opts.get("force"))
    targets = _targets(pos)
    if "pool" in targets and not _pool_guard("restart", force):
        return 3
    rc = 0
    for svc in targets:
        if not launcher.enabled(svc):
            continue
        try:
            out = _via_control(f"/services/{svc}/restart", {"by": _who(), "force": force})
            if out is None:
                supervisor.relaunch(svc)
                supervisor.make_emit()(svc, "manual restart via heronry restart", _who())
                out = {"service": svc, "state": "restarted", "pid": (launcher.run_state.read(svc) or {}).get("pid"),
                       "url": launcher.url(svc)}
            _say(out)
        except Exception as e:  # noqa: BLE001
            print(f"{svc:<8} FAILED  {e}", file=sys.stderr)
            rc = 1
    return rc


# ------------------------------------------------------------------------------------------ misc

def _version_string() -> str:
    from .brand import PRODUCT_NAME
    try:
        from importlib.metadata import version
        ver = version("edp8")  # the internal distribution name stays (R8b)
    except Exception:  # noqa: BLE001 — a source checkout without an install still answers
        ver = "unknown"
    return f"{PRODUCT_NAME} {ver}"


def version_cmd(_argv: list[str]) -> int:
    print(_version_string())
    return 0


def gui(_argv: list[str]) -> int:
    try:
        from . import desktop  # S8 s-6dcf78f803
    except ImportError:
        from .brand import DESKTOP_APP_NAME
        print(f"{DESKTOP_APP_NAME} is not part of this build yet. The board runs in your browser: "
              f"`heronry start`, then open the board URL from `heronry status` (/ui).", file=sys.stderr)
        return 2
    return int(desktop.main() or 0)


def _lazy(module: str, fn: str = "main"):
    def run(argv: list[str]) -> int:
        import importlib
        return int(getattr(importlib.import_module(module), fn)(argv) or 0)
    return run


def help_cmd(_argv: list[str]) -> int:
    from .brand import CLI_NAME, PRODUCT_NAME, TAGLINE
    print(f"{PRODUCT_NAME}: {TAGLINE}\n")
    print(f"usage: {CLI_NAME} <command> [args]\n")
    print("commands:")
    for name, text in (
        ("init", "first-time setup: dirs, config, tokens, agent home, harnesses (--harness claude,codex)"),
        ("start [svc|all]", "start services (board, broker, pool, mcp, bridge) and the supervisor"),
        ("stop [svc|all]", "stop services and verify nothing is left (--force to take pool seats down)"),
        ("restart [svc|all]", "restart through the supervisor (records service_restarted)"),
        ("status", "one row per service: state, pid, port, url, rev, uptime, last probe, last restart"),
        ("doctor", "check prerequisites, harnesses, ports, secrets and claude folder trust"),
        ("update", "check for a new release; --apply installs it (backup, stop, upgrade, start)"),
        ("import --from DIR", "copy an existing v8 install's state (dry run first; --apply to copy)"),
        ("gui", "open the desktop app"),
        ("version", "print the product name and version (also --version)"),
        ("help", "this text (also --help, -h)"),
    ):
        print(f"  {name:<20} {text}")
    return 0


_COMMANDS = {
    "status": status, "start": start, "stop": stop, "restart": restart, "version": version_cmd,
    "help": help_cmd, "gui": gui,
    "init": _lazy("edp8.setup", "init_cmd"), "doctor": _lazy("edp8.setup", "doctor_cmd"),
    "import": _lazy("edp8.importer", "main"), "update": _lazy("edp8.updater", "main"),
    # S13 owns `heronry workflows …` (the update's compat check runs it from the NEW release)
    "workflows": _lazy("edp8.workflows_cli", "main"),
}
_ALIASES = {"--version": "version", "-V": "version", "--help": "help", "-h": "help"}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) >= 2 and argv[0] == SERVICE_FLAG:  # bundle re-entry: before anything else is imported
        return _run_service(argv[1])
    from .brand import CLI_NAME
    load_dotenv()
    cmd = argv[0] if argv else "status"
    cmd = _ALIASES.get(cmd, cmd)
    fn = _COMMANDS.get(cmd)
    if fn is None:
        print(f"{CLI_NAME}: unknown command {cmd!r}. commands: {', '.join(_COMMANDS)}", file=sys.stderr)
        return 2
    return fn(argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
