"""`heronry prereqs [install]`: the one prerequisites step (t-08612be1b0) over `edp_contracts.prereqs`.

    heronry prereqs                      the checklist: found (version), missing (the fix), optional and off
    heronry prereqs --json               the same rows as JSON (the admin API serves the same dicts)
    heronry prereqs install              install the missing required tools after ONE yes/no question
        --yes                            no question (unattended: install.ps1 -Yes, the MSI's first run)
        --no-embed                       skip the embedder and its model (search stays keyword-only)
        --only NAME[,NAME]               just these (the setup wizard's Install button), optional ones included
        --with NAME[,NAME]               the required ones plus these optional ones

install.ps1 / install.sh run `heronry prereqs install` right after `uv tool install`; the desktop installer runs
it on first launch; the wizard runs `--only <name> --yes`. Exit 0 when every required tool (and a harness) is
present afterwards, 1 otherwise, 2 on a usage error.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from edp_contracts import prereqs as pq


def _split_csv(v: str) -> list[str]:
    return [x.strip() for x in v.split(",") if x.strip()]


_OS_WORDS = {"win32": "Windows", "darwin": "macOS", "linux": "Linux"}


def _opts(argv: list[str]) -> tuple[list[str], dict[str, Any]]:
    pos: list[str] = []
    opts: dict[str, Any] = {}
    it = iter(argv)
    for a in it:
        if a in ("--yes", "-y", "--no-embed", "--json"):
            opts[a.lstrip("-")] = True
        elif a in ("--only", "--with"):
            opts[a.lstrip("-")] = _split_csv(next(it, ""))
        elif a.startswith(("--only=", "--with=")):
            k, v = a[2:].split("=", 1)
            opts[k] = _split_csv(v)
        elif a.startswith("-"):
            raise SystemExit(f"heronry prereqs: unknown option {a}")
        else:
            pos.append(a)
    for name in [*opts.get("only", []), *opts.get("with", [])]:
        try:
            pq.by_name(name)
        except KeyError as e:
            raise SystemExit(f"heronry prereqs: {e.args[0]}") from None
    return pos, opts


def rows(embed: bool = True) -> list[pq.Status]:
    return pq.detect_all(embed=embed)


def _line(r: pq.Status) -> str:
    if r.state == "ok":
        detail = " ".join(x for x in (r.version, f"({r.path})" if r.path else "") if x)
    elif r.state == "off":
        detail = f"optional, turns on {r.feature}: {r.fix}"
    elif r.need == "harness":
        detail = f"{r.feature} (at least one of claude/codex): {r.fix}"
    else:
        detail = f"{r.need}: {r.fix}"
    return f"  {r.state:<9}{r.name:<17}{detail}"


def print_checklist(got: list[pq.Status]) -> None:
    print(f"prerequisites ({_OS_WORDS.get(pq.this_os(), pq.this_os())})")
    for r in got:
        print(_line(r))
    for name, why in pq.BUNDLED:
        print(f"  {'bundled':<9}{name:<17}{why}")
    for name, why in pq.NOT_NEEDED:
        print(f"  {'-':<9}{name:<17}{why}")


def _missing_required(got: list[pq.Status], embed: bool) -> list[str]:
    bad = [r.name for r in got if r.state != "ok" and r.need == "required"]
    if not pq.harness_ok(got):
        bad.append("a harness (claude or codex)")
    return bad


def _sign_in_hints(got: list[pq.Status]) -> None:
    from .admin.harnesses import signed_in
    for r in got:
        if r.need in ("harness", "optional") and r.login and r.state == "ok" and signed_in(r.name) is False:
            print(f"  sign in to {r.name}: run `{r.login}`")


def check(opts: dict[str, Any]) -> int:
    embed = not opts.get("no-embed")
    got = rows(embed)
    if opts.get("json"):
        print(json.dumps({"os": pq.this_os(), "rows": [r.to_dict() for r in got],
                          "bundled": [dict(zip(("name", "why"), b)) for b in pq.BUNDLED],
                          "not_needed": [dict(zip(("name", "why"), b)) for b in pq.NOT_NEEDED]}, indent=2))
    else:
        print_checklist(got)
    return 1 if _missing_required(got, embed) else 0


def install(opts: dict[str, Any], *, ask=input, isatty=None) -> int:
    embed = not opts.get("no-embed")
    only = opts.get("only") or []
    got = rows(embed)
    steps, left = pq.plan(got, embed=embed, only=only, optional=opts.get("with") or [])
    if not steps:
        print("heronry prereqs: nothing to install" + ("" if only else "; every required tool is present"))
    else:
        print("heronry prereqs will install:")
        for s in steps:
            print(f"  {s.name:<17}{s.reason}: {pq.describe_recipe(pq.by_name(s.name), s.recipe)}")
        tty = sys.stdin.isatty() if isatty is None else isatty
        if not opts.get("yes"):
            if not tty:
                print("heronry prereqs: not a terminal and no --yes; nothing installed. Re-run with --yes, or run "
                      "the commands above yourself.")
                return 1
            answer = ask(f"Install {'this' if len(steps) == 1 else f'these {len(steps)}'} now? [Y/n] ").strip()
            if answer.lower() not in ("", "y", "yes"):
                print("heronry prereqs: nothing installed")
                return 1
        results = pq.run_steps(steps)
        got = rows(embed)
        if any(r.state != "ok" for r in got if r.name in results):
            pq.refresh_path()  # winget wrote PATH to the registry; this process has the old one
            got = rows(embed)
        for s in steps:
            now = next(r for r in got if r.name == s.name)
            print(f"  {'installed' if now.state == 'ok' else 'FAILED':<10}{s.name}"
                  + (f" {now.version}" if now.version and now.state == "ok" else "")
                  + ("" if now.state == "ok" else f" (exit {results.get(s.name)}): {now.fix}"))
    optional_off = [r for r in got if r.state == "off" and r.name not in only]
    if optional_off and not only:
        print("optional (heronry prereqs install --only <name>):")
        for r in optional_off:
            print(f"  {r.name:<17}turns on {r.feature}")
    for r in left:
        print(f"  manual   {r.name:<17}{r.fix}")
    _sign_in_hints(got)
    bad = _missing_required(got, embed)
    if bad and not only:
        print(f"heronry prereqs: still missing: {', '.join(bad)}")
        return 1
    if only and any(r.state != "ok" for r in got if r.name in only):
        return 1
    return 0


def main(argv: list[str]) -> int:
    pos, opts = _opts(argv)
    verb = pos[0] if pos else "check"
    if verb == "check":
        return check(opts)
    if verb == "install":
        return install(opts)
    print(f"heronry prereqs: unknown verb {verb!r} (check | install)", file=sys.stderr)
    return 2
