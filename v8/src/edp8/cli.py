"""The product CLI, `heronry` (alias `edp8`): the cmd layer over the one launcher (design-e963c656f5 §4.4,
S3 s-870e401942). User-facing names come from `brand.py` (§4.12).

    heronry init      dirs, config.toml, tokens, agent home, harness choice, claude folder trust
    heronry start|stop|restart [svc|all]    services through `edp8.launcher` (+ the supervisor); `code` is the
                      optional code server (edp8.code_service), in `all` only with code_server.autostart
    heronry status    one row per service: state, pid, port, url, rev, uptime, last probe, last restart
    heronry doctor    prerequisites, harnesses (with install links), ports, secrets, trust
    heronry prereqs [install]   the prerequisites checklist; install the missing ones (edp_contracts.prereqs)
    heronry update    check GitHub Releases; apply = compat check, DB backup, stop, reinstall, start
    heronry import --from <v8 dir>   copy an existing v8 state (dry run first; the source is never written)
    heronry gui       the desktop app (S8)
    heronry version

`--heronry-service <svc>` is the frozen bundle's service re-entry (strategyhl-5af811e7bd §3): it runs that
service's module and nothing else, before anything GUI-related is imported.
"""

from __future__ import annotations

import sys
from typing import NamedTuple

#: frozen-bundle re-entry: service name -> module run as __main__
_SERVICE_MODULES = {"board": "edp8.service", "broker": "edp_broker.main", "pool": "edp_pool.main",
                    "mcp": "edp8.mcp_server", "bridge": "edp8.slack_bridge", "supervisor": "edp8.supervisor",
                    # the code server's host guard (S21): the only re-entered service that takes arguments
                    "code-guard": "edp8.code_guard"}
SERVICE_FLAG = "--heronry-service"


def _run_service(name: str, args: list[str] | None = None) -> int:
    import runpy
    mod = _SERVICE_MODULES.get(name)
    if mod is None:
        print(f"unknown service {name!r}", file=sys.stderr)
        return 2
    sys.argv = [mod, *(args or [])]
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
    for k, v in values.items():
        if not settings.env_raw(k):
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
_VALUED = {"harness", "owner", "admin-token", "from", "ports", "board-port", "mcp-port", "pool-port", "broker-port",
           "code-port", "version", "spec", "db", "by", "timeout", "release-url", "previous-url",
           "agent-home-source"}


def _targets(pos: list[str]) -> list[str]:
    """The services a verb acts on. `all` is ORDER, plus the optional code server (S21) only when
    code_server.autostart is on: it is opt-in, so a plain `heronry start|stop` leaves it alone."""
    from . import code_service, launcher
    want = pos[0] if pos else "all"
    if want == "all":
        return [*launcher.ORDER, *([launcher.CODE] if code_service.autostart() else [])]
    if want not in (*launcher.ORDER, launcher.CODE, launcher.SUPERVISOR):
        raise SystemExit(f"unknown service {want!r} (board|broker|pool|mcp|bridge|code|supervisor|all)")
    return [want]


def _code(verb: str, explicit: bool) -> int:
    """`heronry start|stop|restart code` (S21): edp8.code_service directly. The supervisor does not watch the
    code server, so there is nothing to race; the Admin console reaches the same module through the
    supervisor's control port. A missing code-server is a failure only when `code` was asked for by name."""
    from . import code_service
    try:
        if verb == "start":
            out = code_service.start(say=lambda m: print(f"code       {m}"))
        elif verb == "stop":
            out = code_service.stop()
        else:
            out = code_service.restart(say=lambda m: print(f"code       {m}"))
    except code_service.CodeError as e:
        print(f"code       FAILED  {e}", file=sys.stderr)
        return 1
    if out.get("state") == "not_installed":
        print(f"code       not installed  {out.get('install_hint')}", file=sys.stderr if explicit else sys.stdout)
        return 1 if explicit else 0
    _say(out)
    if out.get("survivors"):
        print(f"code: still running {out['survivors']}", file=sys.stderr)
        return 1
    return 0


def _legacy_supervisor() -> bool:
    """A supervisor runs without a control port (started by a pre-S3 launcher): it cannot be asked to hold
    off, so a single-service stop/restart replaces it rather than race its restarts."""
    from . import control, launcher
    if not launcher.supervisor_running():
        return False
    try:
        control.endpoint()
    except control.ControlUnavailable:
        return True
    return False


# ------------------------------------------------------------------------------------------ status

_COLS = ["service", "state", "pid", "port", "url", "git_rev", "uptime", "last_probe", "last_restart_reason", "reason"]
_HEAD = {"git_rev": "rev", "last_probe": "last probe", "last_restart_reason": "last restart"}


def status(argv: list[str]) -> int:
    from . import launcher
    _, opts = _split(argv)
    rows = launcher.status_rows()
    if opts.get("json"):
        print(launcher.dumps(rows))
        return 0
    _table(rows, _COLS, _HEAD)
    down = [r["service"] for r in rows if r.get("state") == "down" and r["service"] != "bridge"
            and (r["service"] != launcher.CODE or r.get("autostart"))]
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
    targets = _targets(pos)
    for svc in targets:
        if svc == launcher.SUPERVISOR:
            continue  # started below, last
        if svc == launcher.CODE:
            continue  # started below, after the board it links to
        try:
            out = _via_control(f"/services/{svc}/start", {"by": _who()}) or launcher.start(svc)
        except Exception as e:  # noqa: BLE001
            print(f"{svc:<8} FAILED  {e}", file=sys.stderr)
            rc = 1
            continue
        _say(out)
    if targets == [launcher.CODE]:
        return _code("start", explicit=True)
    if not opts.get("no-supervisor") and rc == 0:
        try:
            _say(launcher.ensure_supervisor())
        except Exception as e:  # noqa: BLE001
            print(f"supervisor FAILED  {e}", file=sys.stderr)
            rc = 1
    if launcher.CODE in targets and rc == 0:  # `all` with code_server.autostart
        rc = _code("start", explicit=False)
    if rc == 0:
        try:
            from .updater import notice
            line = notice()  # daily, silent offline, off with HERONRY_NO_UPDATE_CHECK=1 and in dev mode
        except Exception:  # noqa: BLE001 — an update check never fails a start
            line = None
        if line:
            print(line)
    if rc == 0 and "board" in _targets(pos):
        _first_run_setup(open_browser=_may_open_browser(opts))
    return rc


def _may_open_browser(opts: dict) -> bool:
    """Only a person at a terminal gets a browser tab (m-98e4f2770f: test and seat `start`s opened five
    /ui/setup tabs in the owner's own browser). All must hold, else the URL is only printed: no --no-browser
    and no HERONRY_NO_BROWSER; no seat identity in the environment; not a source checkout (dev mode, the
    fleet); stdin and stdout are a TTY."""
    from . import settings
    if opts.get("no-browser") or settings.environ_copy().get("HERONRY_NO_BROWSER"):
        return False
    if settings.env_raw("EDP_HANDLE") or settings.env_raw("EDP8_PARTICIPANT"):
        return False
    try:
        if settings.dev_mode():
            return False
    except Exception:  # noqa: BLE001 — undecidable = do not open
        return False
    try:
        return bool(sys.stdin and sys.stdin.isatty() and sys.stdout and sys.stdout.isatty())
    except (ValueError, OSError):
        return False


def _first_run_setup(open_browser: bool) -> None:
    """Design §4.8 Onboarding: until the wizard is finished, `start` opens /ui/setup with a one-time
    sign-in code for the init human (never a token in the address bar); afterwards it opens nothing."""
    from . import launcher
    from .admin import setup_api
    try:
        if setup_api.state()["done"]:
            return
        url = f"{str(launcher.url('board')).rstrip('/')}/ui/setup?code={setup_api.issue_setup_code()}"
    except Exception as e:  # noqa: BLE001 — the wizard is a convenience; never fail a start over it
        print(f"setup     skipped  ({e})", file=sys.stderr)
        return
    print(f"setup      first run: finish setup at {url}  (the link signs you in once, within 24 h)")
    if open_browser:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass


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
    if "pool" in targets and not opts.get("keep-seats") and not _pool_guard("stop", force):
        return 3
    rc = 0
    everything = not pos or pos[0] == "all"
    if targets == [launcher.SUPERVISOR]:
        _say(launcher.stop_supervisor())
        return 0
    if targets == [launcher.CODE]:
        return _code("stop", explicit=True)
    if launcher.CODE in targets:  # `all` with autostart: the code server goes first, before the board it links to
        rc = _code("stop", explicit=False)
        targets = [t for t in targets if t != launcher.CODE]
    if everything:  # the supervisor goes first, so nothing is restarted behind our back
        _say(launcher.stop_supervisor())
    elif _legacy_supervisor():
        print("note: the running supervisor has no control port (started by the old launcher); stopping it "
              f"so it does not restart {targets[0]} — `heronry start supervisor` brings a new one")
        _say(launcher.stop_supervisor())
    for svc in reversed(targets):
        # --keep-seats (pool): stop only the pool's own processes; its seat shells run on and the next pool
        # re-adopts them (the legacy edp.ps1 contract: a pool stop is never a tree kill)
        keep = bool(opts.get("keep-seats"))
        out = None if everything else _via_control(f"/services/{svc}/stop",
                                                   {"by": _who(), "force": force, "keep_seats": keep})
        out = out or launcher.stop(svc, keep_seats=keep)
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
    if targets == [launcher.SUPERVISOR]:
        _say(launcher.stop_supervisor())
        _say(launcher.ensure_supervisor())
        return 0
    if targets == [launcher.CODE]:
        return _code("restart", explicit=True)
    code_too = launcher.CODE in targets
    targets = [t for t in targets if t != launcher.CODE]
    replace = _legacy_supervisor()
    if replace:  # it would race the relaunch below; a new one (with a control port) starts after
        _say(launcher.stop_supervisor())
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
    if replace:
        _say(launcher.ensure_supervisor())
    if code_too and rc == 0:
        rc = _code("restart", explicit=False)
    return rc


# ------------------------------------------------------------------------------------------ misc

def _version_string() -> str:
    from . import __version__  # the internal package name stays (R8b)
    from .brand import PRODUCT_NAME
    return f"{PRODUCT_NAME} {__version__}"


def version_cmd(_argv: list[str]) -> int:
    print(_version_string())
    return 0


def gui(argv: list[str]) -> int:
    try:
        from . import desktop  # S8 s-6dcf78f803
    except ImportError:
        from .brand import DESKTOP_APP_NAME
        print(f"{DESKTOP_APP_NAME} is not part of this build yet. The board runs in your browser: "
              f"`heronry start`, then open the board URL from `heronry status` (/ui).", file=sys.stderr)
        return 2
    return int(desktop.main(argv) or 0)


def _lazy(module: str, fn: str = "main"):
    def run(argv: list[str]) -> int:
        import importlib
        return int(getattr(importlib.import_module(module), fn)(argv) or 0)
    return run


class Command(NamedTuple):
    """One `heronry` command as `help` prints it and the project site's CLI reference renders it (S15)."""
    name: str
    usage: str
    summary: str
    flags: tuple[tuple[str, str], ...] = ()


#: the command table: `help` prints it and the site's CLI reference is generated from it, so a new command or flag
#: is declared here once (docs/site/hooks/sitegen.py)
COMMANDS: tuple[Command, ...] = (
    Command("init", "init", "first-time setup: dirs, config, tokens, agent home, harnesses, ports", (
        ("--harness claude,codex,pi", "the seat harnesses to use; at least one (asked when interactive)"),
        ("--owner NAME", "the first human's handle"),
        ("--ports N", "a port block: board N, mcp N+2, pool N-99, broker N-100, code N+10"),
        ("--board-port / --mcp-port / --pool-port / --broker-port / --code-port N", "one service's port"),
        ("--admin-token TOKEN", "use this admin token instead of generating one"),
        ("--yes", "no questions: take the defaults"),
        ("--force", "run even in a source checkout (dev mode)"),
    )),
    Command("start", "start [svc|all]", "start services (board, broker, pool, mcp, bridge) and the supervisor; "
            "`start code` starts the optional code server (VS Code in the browser)", (
        ("--no-browser", "do not open the setup wizard in a browser on first run"),
        ("--no-supervisor", "start the services without the supervisor that restarts a crashed one"),
    )),
    Command("stop", "stop [svc|all]", "stop services and verify nothing is left", (
        ("--force", "stop the pool even with live seats"),
        ("--keep-seats", "stop only the pool's own processes; its seat shells run on"),
    )),
    Command("restart", "restart [svc|all]", "restart through the supervisor (records service_restarted)", (
        ("--force", "restart the pool even with live seats"),
    )),
    Command("status", "status", "one row per service: state, pid, port, url, rev, uptime, last probe, last restart", (
        ("--json", "print the rows as JSON"),
    )),
    Command("doctor", "doctor", "check prerequisites, harnesses, ports, secrets and claude folder trust", (
        ("--agent [text]", "ask the Help seat (an agent that diagnoses and proposes fixes you approve)"),
        ("--bundle [PATH]", "write a redacted diagnostics zip to attach to a GitHub issue"),
    )),
    Command("prereqs", "prereqs [install]", "list the tools Heronry needs; install installs the missing ones", (
        ("--yes", "install without asking"),
        ("--no-embed", "skip the local search model"),
        ("--only NAME", "install only this prerequisite"),
        ("--with NAME", "also install this optional prerequisite"),
        ("--json", "print the checklist as JSON"),
    )),
    Command("update", "update", "check for a new release and install it (backup, stop, upgrade, start)", (
        ("--check", "only report the current and latest versions"),
        ("--dry-run", "check, download and verify, then stop before changing anything"),
        ("--force", "reinstall the same version, update with live seats or an unanswering pool (takes them "
                    "offline), or update with no way back when the installed version's wheels can't be secured"),
        ("--allow-downgrade", "install an older release"),
        ("--skip-compat", "skip the custom-workflow compatibility check"),
        ("--release-url URL", "update from this release instead of the latest"),
        ("--previous-url URL", "the installed version's release, for the rollback wheels (default: its GitHub tag)"),
    )),
    Command("import", "import --from DIR", "copy an existing v8 install's state (dry run first)", (
        ("--from DIR", "the v8 folder to copy from (never written)"),
        ("--apply", "copy for real (without it: a dry run with a diff report)"),
        ("--force", "import even in a source checkout (dev mode)"),
    )),
    Command("workflows", "workflows check --db PATH", "check every custom workflow in a board DB against this version", (
        ("--db PATH", "the board database (read on a scratch copy)"),
        ("--json", "print a JSON list of {workflow, version, ok, errors}"),
    )),
    Command("gui", "gui", "open the desktop app", (
        ("--capture [DIR]", "save the app's own window content as PNGs under its data folder, then quit"),
    )),
    Command("version", "version", "print the product name and version (also --version)"),
    Command("help", "help", "this text (also --help, -h)"),
)


def help_cmd(_argv: list[str]) -> int:
    from .brand import CLI_NAME, PRODUCT_NAME, TAGLINE
    print(f"{PRODUCT_NAME}: {TAGLINE}\n")
    print(f"usage: {CLI_NAME} <command> [args]\n")
    print("commands:")
    for c in COMMANDS:
        print(f"  {c.usage:<20} {c.summary}")
        for flag, text in c.flags:
            print(f"  {'':<20}   {flag}  {text}")
    return 0


_COMMANDS = {
    "status": status, "start": start, "stop": stop, "restart": restart, "version": version_cmd,
    "help": help_cmd, "gui": gui,
    "init": _lazy("edp8.setup", "init_cmd"), "doctor": _lazy("edp8.setup", "doctor_cmd"),
    "prereqs": _lazy("edp8.prereqs_cmd", "main"),
    "import": _lazy("edp8.importer", "main"), "update": _lazy("edp8.updater", "main"),
    # S13 owns `heronry workflows …` (the update's compat check runs it from the NEW release)
    "workflows": _lazy("edp8.workflows_cli", "main"),
}
_ALIASES = {"--version": "version", "-V": "version", "--help": "help", "-h": "help"}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) >= 2 and argv[0] == SERVICE_FLAG:  # bundle re-entry: before anything else is imported
        return _run_service(argv[1], argv[2:])
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
