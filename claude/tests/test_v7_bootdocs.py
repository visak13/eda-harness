"""v7 §2.3 — the boot-doc compiler CI gate: budgets hold, the checked-in
commands match a fresh compile (no hand-edits to compiled output), and no
source module is silently orphaned."""

from edp_claude.bootdocs import compile_all


def test_budgets_drift_and_orphans():
    rep = compile_all(write=False)
    orphans = rep.pop("_orphans")
    assert orphans == [], (
        f"source modules consumed by no command and not declared in the "
        f"manifest's `uncompiled` notes: {orphans} — the orphan gate is how "
        f"'no value lost' stays checkable; wire them in or declare them.")
    for cmd, row in rep.items():
        assert not row["over_budget"], (
            f"{cmd}: {row['tokens']} tokens exceeds its {row['budget']} "
            f"budget — tighten the source modules; the budget is the "
            f"boot-cost contract, never headroom.")
        assert not row["drift"], (
            f"{cmd}: the checked-in .claude/commands/{cmd}.md differs from "
            f"a fresh compile — it was hand-edited or the sources changed "
            f"without recompiling. Run `python -m edp_claude.bootdocs`.")


def test_compiled_commands_carry_the_header():
    from edp_claude.bootdocs import HEADER, _default_roots, load_manifest
    src, out = _default_roots()
    for cmd in load_manifest(src)["commands"]:
        text = (out / f"{cmd}.md").read_text("utf-8")
        assert text.startswith(HEADER.split("\n")[0]), cmd
