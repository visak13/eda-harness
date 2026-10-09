"""RC2 gate, hop2 (architect m-b7abaedb27, adversary m-fcbc23ab01): after `heronry update`, no file under the
sandbox agent home's `.claude` may name a tool the installed product does not register. A stale role card or skill
points every seat at a removed tool (`assemble_ruleset` was the live case). The refresh keeps a file it judges
user-edited and writes `<file>.new` beside it (edp8.materialise), so a `.new` file is reported by name too.

    python gate_agent_home.py <.claude dir> <registry.json> [<registry before the update.json>]

The registries are the tool names the installed product prints (`heronry.exe -c`, see gate_rc2_upgrade.ps1):
the board's tools plus the proxied browser tools. Reads only the given files.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

#: a tool call as the cards and skills write it: `context_delta(cursor=...)`; a snake_case name right before `(`
CALL = re.compile(r"(?<![\w.])([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\(")
NEW_SUFFIX = ".new"


def load_registry(path: Path) -> set[str]:
    return set(json.loads(path.read_text(encoding="utf-8-sig")))


def scan(claude: Path, registry: set[str], removed: set[str] = frozenset()) -> dict[str, dict[str, list[str]] | list[str]]:
    """`unknown`: a called name the registry lacks -> the files naming it; `removed`: a tool the update dropped,
    named anywhere (bare or called) -> the files; `new_files`: every `<file>.new` the refresh left beside a kept file."""
    unknown: dict[str, set[str]] = {}
    gone: dict[str, set[str]] = {}
    new_files: list[str] = []
    for f in sorted(p for p in claude.rglob("*") if p.is_file()):
        rel = f.relative_to(claude).as_posix()
        if f.name.endswith(NEW_SUFFIX):
            new_files.append(rel)
        text = f.read_text(encoding="utf-8", errors="replace")
        for m in CALL.finditer(text):
            if m.group(1) not in registry:
                unknown.setdefault(m.group(1), set()).add(rel)
        for name in removed:
            if re.search(rf"(?<![\w.]){re.escape(name)}\b", text):
                gone.setdefault(name, set()).add(rel)
    return {"unknown": {k: sorted(v) for k, v in sorted(unknown.items())},
            "removed": {k: sorted(v) for k, v in sorted(gone.items())},
            "new_files": new_files}


def main(argv: list[str]) -> int:
    claude, after = Path(argv[0]), load_registry(Path(argv[1]))
    before = load_registry(Path(argv[2])) if len(argv) > 2 and Path(argv[2]).is_file() else set()
    found = scan(claude, after, before - after)
    print(json.dumps(found, indent=1))
    return 1 if any(found.values()) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
