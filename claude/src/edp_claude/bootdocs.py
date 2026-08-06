"""The boot-doc compiler — one bounded read per role boot (v7 §2.3).

WHY. A role's knowledge was spread over 7-12 `get_guide` fetches (a planner
sat on ~13.6k tokens of framework prose before any project content), with
command-vs-card duplication (~70% overlap measured on the reviewer pair).
This compiler assembles each slash command's body from single-topic SOURCE
MODULES under docs/guides-src/, so:

  * boot = ONE read (the command body IS the boot doc; the pool's typed
    activation is unchanged),
  * every command has a token BUDGET enforced here and in CI
    (tests/test_v7_bootdocs.py) using the same chars/4 estimator as
    _bounds.py,
  * the compiled output is DRIFT-GATED: CI recompiles and asserts the
    checked-in .claude/commands/*.md match — hand-edits to a compiled
    command fail the build with "edit the source module instead",
  * NO VALUE IS LOST silently: every source module must be consumed by a
    command or explicitly listed in the manifest's `uncompiled` notes —
    the orphan gate.

Cards (docs/guides/<role>-card.md) are NOT deleted: they remain the
post-compaction reground unit (the rewire block re-injects them), and the
deep guides remain get_guide-fetchable. The boot fan-out is what dies.

Deterministic, no LLM, no network. `python -m edp_claude.bootdocs` compiles
in place; `compile_all(write=False)` is the CI check mode.
"""

import json
import sys
from pathlib import Path

HEADER = ("<!-- COMPILED by edp_claude.bootdocs from docs/guides-src/ — DO "
          "NOT EDIT THIS FILE. Edit the source modules and run `python -m "
          "edp_claude.bootdocs`; CI drift-gates this output. -->\n\n")


def approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _default_roots() -> tuple[Path, Path]:
    home = Path(__file__).resolve().parents[2]      # .../claude
    return home / "docs" / "guides-src", home / ".claude" / "commands"


def load_manifest(src_root: Path) -> dict:
    return json.loads((src_root / "manifest.json").read_text("utf-8"))


def compile_command(src_root: Path, modules: list[str]) -> str:
    parts = []
    for m in modules:
        p = src_root / m
        parts.append(p.read_text("utf-8").strip())
    return HEADER + "\n\n".join(parts) + "\n"


def compile_all(src_root: Path | None = None, out_dir: Path | None = None,
                write: bool = True) -> dict:
    """Compile every manifest command. Returns {command: {tokens, budget,
    over_budget, drift}} — `drift` is set in check mode (write=False) when
    the checked-in file differs from the compiled output."""
    d_src, d_out = _default_roots()
    src_root = src_root or d_src
    out_dir = out_dir or d_out
    man = load_manifest(src_root)
    report: dict = {}
    used: set[str] = set()
    for cmd, modules in man["commands"].items():
        used.update(modules)
        text = compile_command(src_root, modules)
        toks = approx_tokens(text)
        budget = int(man["budgets"][cmd])
        row = {"tokens": toks, "budget": budget,
               "over_budget": toks > budget, "drift": False}
        out_path = out_dir / f"{cmd}.md"
        if write:
            out_path.write_text(text, encoding="utf-8", newline="\n")
        else:
            current = (out_path.read_text("utf-8")
                       if out_path.is_file() else "")
            row["drift"] = current != text
        report[cmd] = row

    # orphan gate: every module on disk is consumed or the manifest says why
    on_disk = {str(p.relative_to(src_root)).replace("\\", "/")
               for p in src_root.rglob("*.md")}
    report["_orphans"] = sorted(on_disk - used)
    return report


def main() -> int:
    rep = compile_all(write=True)
    bad = False
    for cmd, row in rep.items():
        if cmd == "_orphans":
            continue
        flag = " OVER BUDGET" if row["over_budget"] else ""
        print(f"{cmd:<14} {row['tokens']:>5} tok / budget "
              f"{row['budget']}{flag}")
        bad = bad or row["over_budget"]
    if rep["_orphans"]:
        print(f"ORPHAN MODULES (unused, undeclared): {rep['_orphans']}")
        bad = True
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
