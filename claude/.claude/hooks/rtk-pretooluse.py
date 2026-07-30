#!/usr/bin/env python3
"""PreToolUse hook — let `rtk` compress Bash tool OUTPUT, without ever changing
what the command MEANS.

DESIGN-v6 W6: `rtk` (a local Rust binary) compresses command OUTPUT before it
enters the model's context — a big token win for Bash-heavy worker shells
(build/test/grep loops), costing zero model tokens itself. It is wired here so
every spawned shell that loads the settings inheriting this hook gets it.

THE BUG THIS FILE EXISTS TO NOT REPEAT (measured, s30/a2b + a2d)
----------------------------------------------------------------
The previous version rewrote the WHOLE command string into `rtk <cmd>`. rtk
execs the FIRST TOKEN as a binary; when that token is a shell builtin or a bare
variable assignment, rtk silently drops it and runs the REST anyway, exiting 0:

    X=hello; echo "[$X]"   ->  printed []            (assignment vanished)
    cd /tmp; pwd           ->  printed the OLD cwd   (the `cd` VANISHED)

So `cd <dir> && rm -rf <relative>` would have deleted against the WRONG cwd and
reported success. A wrapper that changes what a command MEANS is categorically
worse than one that saves nothing. The bug was OURS, not rtk's: rtk expects a
SINGLE EXECUTABLE (`rtk grep foo`), and it publishes `rtk rewrite` precisely so
hooks do not have to guess. We were not asking it.

THE CONTRACT NOW (three gates; ALL must pass, else pass through untouched)
-------------------------------------------------------------------------
  1. SHAPE GATE (ours, fail-closed). We only ever consider a SIMPLE command: no
     shell metacharacters at all (no `;` `&` `|` `<` `>` `(` `)` backtick `$`
     quotes backslash newline), a first token that is a bare command NAME (not
     an assignment, not a path), and that name is not a shell builtin/keyword.
     Chains, quoted strings, redirections, subshells, `bash -c ...`,
     builtin-first and assignment-first commands therefore NEVER reach rtk —
     they pass through byte-for-byte. This is what makes the semantics hazard
     structurally unreachable rather than merely unlikely.

  2. PRESENCE GATE (ours, fail-closed). The first token must be a binary we have
     MEASURED to exist in the Bash shell. rtk SUBSTITUTES ITS OWN
     IMPLEMENTATION for an adapter-supported binary the host does not have, so
     `tree src` — exit 127 `command not found` raw — came back EXIT 0 WITH JUNK
     STDOUT: success reported for a command that cannot run (`rg` similarly
     became exit 1). Not wrapping a binary that is not there makes that
     fabricated exit STRUCTURALLY UNREACHABLE, and it costs nothing: a binary
     that is not installed was never compressing anything.

     THE LIST IS MEASURED, NOT RESOLVED — AND `shutil.which` IS THE WRONG
     INSTRUMENT HERE, WHICH IS ONLY KNOWABLE BY MEASURING IT (s30/a2e). This
     hook runs as a WINDOWS process, but the commands it compresses live in Git
     Bash's `/usr/bin`, which is NOT on the Windows PATH. From here,
     `which('grep'|'ls'|'wc'|'ps'|'cat')` all return None, while `tree` and
     `find` resolve to the ENTIRELY DIFFERENT Windows `tree.COM`/`find.EXE`. A
     PATH-resolution guard would therefore have killed 100% of the measured
     compression AND left the divergence standing — inertness wearing the
     costume of a safety fix. So the set below is a2e's MEASUREMENT of what
     actually resolves and compresses in the Bash shell, not a probe of this
     process's PATH.

     FAIL-CLOSED: rtk claims ~29 adapters, but only these were measured. An
     adapter we never proved present is NOT wrapped — we assert nothing about
     it either way. Forfeits only unmeasured, never-counted compression; buys
     the absent-binary class in full, for every absent binary rather than only
     the two we happened to name. To add one: MEASURE it in the Bash shell
     first, then add it here.

  3. ADAPTER GATE (rtk's, authoritative). `rtk rewrite <cmd>` IS rtk's own
     "single source of truth for hooks" (its `--help`, verbatim). It prints the
     rewritten command iff rtk actually has an adapter for it, and prints
     NOTHING when it does not. We ask it per command rather than hard-coding a
     list, so the allowlist can never drift out of date with the installed rtk,
     and we run rtk's OWN rewrite rather than a hand-built `rtk ` + cmd (rtk
     knows, e.g., that `cat f` becomes `rtk read f`, which we could not guess).

     Exit code is deliberately IGNORED. Measured against rtk 0.43.0, `rtk
     rewrite` exits 3 — not the documented 0 — on supported commands while
     still printing the rewrite, so the idiom rtk's own help suggests
     (`REWRITTEN=$(rtk rewrite "$CMD") || exit 0`) would silently discard every
     rewrite and kill the benefit. EMPTY STDOUT is the reliable "unsupported"
     signal, and that is what we key on.

Both gates are additionally gated on env `EDP_RTK == '1'` (the pool's
`build_env` sets it per spawn), so rtk can be switched off fleet-wide.

FAIL-SAFE IS MANDATORY. In EVERY other case — EDP_RTK unset, rtk absent, the
probe erroring or timing out, a non-Bash tool, a malformed payload, or ANY
internal exception — the hook PASSES THROUGH: it emits nothing and exits 0, so
the Bash command runs exactly as it would with no hook at all. This hook must
NEVER block or error out a Bash call.

THE COST OF WRAPPING, MEASURED (s30/a2e) — "ERRORS KEPT VERBATIM" IS **FALSE**
----------------------------------------------------------------------------
This docstring used to end: *"rtk keeps stderr/errors verbatim by design, so
when the compressed view is insufficient an agent can re-run raw."* That claim
had gone unmeasured since W6.1. It was finally measured, and it is STRUCK — not
softened — because it is wrong on adapted commands:

    wc -l /no/such/file    error text DROPPED ENTIRELY (empty stderr)
    git status (non-repo)  error REWRITTEN ("Not a git repository")
    grep/cat on a bad path error path MSYS-MANGLED (C:/Program Files/Git/...)

Exit codes ARE preserved in every case, so a FAILURE STILL READS AS A FAILURE —
that is the property that matters most, and it holds. But an agent CANNOT always
learn WHY a wrapped command failed, nor copy a path back out of the error to
re-run it raw. That degrades exactly the signal a worker needs to self-correct,
and it is the standing cost to weigh against the 54-94% compression. Do not
re-add a verbatim-errors claim to this file without measuring it first.

Reads the PreToolUse JSON on stdin; on a match prints an `updatedInput`
allow-decision, else exits 0 (unchanged permission flow). Kept dependency-free
+ tiny so it adds negligible latency to each Bash call."""
import json
import os
import re
import subprocess
import sys

# Anything here means the string is not a single simple command: the shell would
# do something structural with it (sequence, chain, pipe, redirect, subshell,
# expansion, quoting, escaping). We refuse to touch such a command at all.
_SHELL_METACHARS = set(";&|<>()`$\"'\\\n\r")

# A bare command name: letters/digits and the punctuation real binaries use.
# Excludes `=` (assignment-first) and path separators (`/`, `\`) by construction.
_BARE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9._+-]*$")

# Shell builtins and keywords. rtk 0.43.0 already declines all of these, but the
# denylist is OURS on purpose: several collide by NAME with real rtk adapters
# (`test`, `read`, `time`, `env`, `find`), and a future rtk that starts claiming
# one of them must not be able to make `cd` or `export` disappear again. Defense
# in depth — the safety property must not depend on the vendor's judgment.
_SHELL_BUILTINS = frozenset("""
alias bg bind break builtin caller case cd command compgen complete compopt
continue coproc declare dirs disown do done echo elif else enable esac eval exec
exit export false fc fg fi for function getopts hash help history if in jobs kill
let local logout mapfile popd printf pushd pwd read readarray readonly return
select set shift shopt source suspend test then time times trap true type typeset
ulimit umask unalias unset until wait while
""".split()) | {".", ":", "[", "[["}

# Binaries MEASURED to exist in the Bash shell (s30/a2e, Windows 11 + Git-Bash).
# Wrapping is confined to these, so rtk can never be asked to substitute its own
# implementation for a binary the host lacks — which is what turned an exit-127
# `tree` into a junk-stdout exit 0. See the PRESENCE GATE in the module
# docstring: this is a MEASUREMENT, and `shutil.which` is a measurably wrong way
# to reproduce it from this Windows process. Do not "improve" it into one.
#
# Measured PRESENT and left in:   grep ls find wc ps  (the 54%-94% compressors)
#                                 cat du df git       (present; pass through ~0%)
# Measured ABSENT and kept out:   tree                (the substitution bug)
# NOT a binary at all, kept out:  rg — and the REASON matters, because the
#   obvious re-measurement gets it backwards (s30/a2f). `rg` is NOT absent: it
#   is a BASH FUNCTION Claude Code injects, shelling out to claude.exe. It is
#   not on PATH, and `bash -c` DROPS shell functions — which is why an earlier
#   probe read exit 127 and filed it as "missing". In a real worker shell `rg`
#   WORKS. It must stay out regardless: rtk execs the first token as a BINARY,
#   bypassing the function entirely, so wrapping `rg` replaced a working search
#   with empty stdout + exit 1 — a SILENT FALSE NEGATIVE, which an agent reads
#   as "no matches". Do NOT "fix" this by measuring `rg` present in an
#   interactive shell and adding it: present-as-a-function is exactly the case
#   that breaks.
# Never measured, so kept out:    every other rtk adapter (gh glab docker
#   kubectl pytest jest vitest cargo make curl wget psql aws dotnet tsc prisma
#   pnpm head tail …) — unproven presence is not presence.
_MEASURED_PRESENT = frozenset({
    "cat", "df", "du", "find", "git", "grep", "ls", "ps", "wc",
})

_TIMEOUT_S = 5


def _rtk_rewrite(command: str) -> str | None:
    """Ask rtk itself whether it can compress `command`, and how.

    Returns rtk's own rewritten command, or None if rtk has no adapter for it
    (empty stdout), rtk is absent, or the probe fails/times out. Never raises."""
    try:
        proc = subprocess.run(
            ["rtk", "rewrite", command],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=_TIMEOUT_S,
            text=True,
        )
    except Exception:  # noqa: BLE001 — missing binary, timeout, OSError → no-op
        return None
    # Exit code is NOT the signal (see module docstring: 0.43.0 exits 3 on
    # success). Non-empty stdout is.
    rewritten = (proc.stdout or "").strip()
    return rewritten or None


def rewrite(command: str) -> str | None:
    """Return the rtk-compressed form of this Bash `command`, or None to pass it
    through byte-for-byte. Pure except for the env read + the `rtk rewrite`
    probe; importable for tests."""
    if os.environ.get("EDP_RTK") != "1":
        return None

    cmd = (command or "").strip()
    if not cmd:
        return None

    # Idempotent: never re-wrap a command that is already an rtk invocation.
    if cmd.split()[0] == "rtk":
        return None

    # --- Gate 1: shape. Only a single simple command may proceed. -------------
    if any(ch in _SHELL_METACHARS for ch in cmd):
        return None

    first = cmd.split()[0]
    if not _BARE_NAME.match(first):
        return None  # assignment-first (FOO=bar), path-qualified, or exotic
    if first in _SHELL_BUILTINS:
        return None  # cd / export / test / read / time / … stay untouched

    # --- Gate 2: presence. Only binaries measured to EXIST in the Bash shell. -
    # An absent binary would be silently substituted by rtk's own implementation
    # (`tree` -> exit 0 + junk, for a command that cannot run). Fail-closed:
    # unmeasured is treated as absent.
    if first not in _MEASURED_PRESENT:
        return None

    # --- Gate 3: adapter. rtk decides, and rtk supplies the rewrite. ----------
    rewritten = _rtk_rewrite(cmd)
    if not rewritten or rewritten == cmd:
        return None
    return rewritten


def main() -> int:
    try:
        data = json.load(sys.stdin)
        if (data.get("tool_name") or "") != "Bash":
            return 0  # only Bash — every other tool passes through
        tool_input = data.get("tool_input") or {}
        command = tool_input.get("command", "") or ""
        wrapped = rewrite(command)
        if wrapped is None:
            return 0  # pass through: run exactly as it would with no hook
        print(json.dumps({"hookSpecificOutput": {  # noqa: T201 — stdout IS
            # the hook interface: this allow+updatedInput JSON is read by the
            # harness, which runs `updatedInput.command` in place of the input.
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": {**tool_input, "command": wrapped},
        }}))
        return 0
    except Exception:  # noqa: BLE001 — FAIL-SAFE: never block/error a Bash
        # call. Any unexpected failure collapses into clean pass-through.
        return 0


if __name__ == "__main__":
    sys.exit(main())
