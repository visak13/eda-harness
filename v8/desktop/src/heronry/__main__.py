"""The bundle's one entry point (S8 s-6dcf78f803, strategyhl-5af811e7bd §3).

Inside a Briefcase bundle `sys.executable` is the app stub, so every service the launcher starts comes back
here as `<app> --heronry-service <svc>` (launcher.service_argv). That flag is dispatched FIRST, before any GUI
module is imported. A CLI verb (`<app> status`, `<app> version` …) runs the `heronry` CLI; no argument opens
Heronry Desktop.
"""

from __future__ import annotations

import json
import os
import sys

SERVICE_FLAG = "--heronry-service"


def _probe() -> None:
    """HERONRY_BUNDLE_PROBE=<file>: append what the stub handed us (the re-entry spike's measurement)."""
    target = os.environ.get("HERONRY_BUNDLE_PROBE")
    if not target:
        return
    row = {"pid": os.getpid(), "executable": sys.executable, "frozen": getattr(sys, "frozen", None),
           "argv": sys.argv, "orig_argv": getattr(sys, "orig_argv", None), "prefix": sys.prefix}
    with open(target, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def _as_interpreter(argv: list[str]) -> int:
    """`<app> -m <module> …`, `<app> -c <code> …` and `<app> <script.py> …` behave as `python` would.

    The helpers the packages start with `sys.executable` (edp_contracts.proc.detach's `-c` shim, the seats'
    `-m edp8.feed_driver` monitor, the pool's `-m edp_pool.console_input`, the update helper script) are not
    services; inside a bundle `sys.executable` is this app, so they land here. Services never do: they come
    through `--heronry-service` (launcher.service_argv)."""
    import runpy
    flag = argv[0]
    if flag == "-m":
        if len(argv) < 2:
            print("Argument expected for the -m option", file=sys.stderr)
            return 2
        sys.argv = [argv[1], *argv[2:]]
        runpy.run_module(argv[1], run_name="__main__", alter_sys=True)
        return 0
    if flag == "-c":
        if len(argv) < 2:
            print("Argument expected for the -c option", file=sys.stderr)
            return 2
        sys.argv = ["-c", *argv[2:]]
        exec(compile(argv[1], "<string>", "exec"), {"__name__": "__main__", "__builtins__": __builtins__})
        return 0
    sys.argv = list(argv)
    runpy.run_path(argv[0], run_name="__main__")
    return 0


def main() -> int:
    _probe()
    argv = sys.argv[1:]
    if len(argv) >= 2 and argv[0] == SERVICE_FLAG:
        from edp8.cli import _run_service  # no GUI import on this path
        return _run_service(argv[1])
    if argv and (argv[0] in ("-m", "-c") or argv[0].endswith(".py")):
        return _as_interpreter(argv)
    if argv:
        from edp8.cli import main as cli_main
        return int(cli_main(argv) or 0)
    from edp8.cli import main as cli_main
    return int(cli_main(["gui"]) or 0)


if __name__ == "__main__":
    sys.exit(main())
