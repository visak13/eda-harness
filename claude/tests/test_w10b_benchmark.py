"""W10b/a4b — the benchmark entry gate.

`test_w10b_model_tiering.py` pins the SHAPE of the tier table. This file pins
the thing that table was always missing: that any row claiming to be MEASURED is
backed by a real entry in `docs/design/MODEL-TIERING-BENCHMARK.md`.

The bar this pins:

* T1  the doc carries a benchmark ENTRY naming the task, the date, both exact
      model ids, the `thinking` and `effort` settings, and the trial count.
      "A result without its settings is not a result" — the doc's own rule.
* T2  EVERY `MODEL_TIERS` row at status="measured" is NAMED in the doc. No
      measured row without an entry. This is DESIGN-v6 W10b's own gate — the one
      the design itself violated (d80) by labelling a tier "measured" on the
      authority of a document that did not exist. It was PROSE; here it is CODE.
      If there are no measured rows, that is asserted too, and the doc must say
      why the flip was withheld.
* T3  "haiku" still appears NOWHERE in the tier table or its resolution path.
* T4  a row carries ONLY `{model, status}` (+`benchmark_task`) — NO row may
      declare `thinking` or `effort`. a4's T5 pinned the OPPOSITE (that every row
      set both) and called it the comparability guarantee; nothing read either
      field, so it guaranteed nothing. A declared-and-dropped field reads to the
      next author as a setting in force. This test refuses any field the spawn
      path would silently drop.

Every assertion is done in PYTHON: the verify shell is PowerShell and has no
`grep` (d8/R11).
"""

import inspect
import re
from pathlib import Path

from edp_claude.tools import roles as roles_mod
from edp_claude.tools.roles import (
    MODEL_TIERS,
    SONNET,
    resolve_model_tier,
    spawn_model_for,
)

_ROOT = Path(__file__).resolve().parents[1]
_DOC = _ROOT / "docs" / "design" / "MODEL-TIERING-BENCHMARK.md"

#: the benchmark a4b actually ran; the doc must carry its entry.
BENCH_TASK = "a4b/BENCH-WORKER-CODING"

OPUS_ID = "claude-opus-4-8"
#: the Sonnet the table TIERS TO now (claude-sonnet-4-6; USER RULING 2026-07-16),
#: read from the source of truth — NOT the model a4b historically measured
#: (claude-sonnet-5). The doc must name this id (T1) and no tier may resolve to
#: anything but OPUS_ID / SONNET_ID (T4).
SONNET_ID = SONNET


def _doc() -> str:
    assert _DOC.is_file(), f"{_DOC} does not exist"
    return _DOC.read_text(encoding="utf-8")


def _tier_key_str(role: str, task_class: str) -> str:
    """How a tier row is spelled in the doc: `("worker", "coding")`."""
    return f'("{role}", "{task_class}")'


# ── T1 ─────────────────────────────────────────────────────────────────────
def test_t1_doc_carries_a_real_entry_with_its_settings():
    """A result without its settings is not a result (the doc's ground rule 4).

    Pins the six things a4b's brief requires the entry to state: the task, the
    date, both exact model ids, the `thinking` setting, the `effort` setting,
    and the trial count.
    """
    doc = _doc()

    assert BENCH_TASK in doc, (
        f"the doc names no {BENCH_TASK} entry — a candidate tier that nobody "
        f"measures is a no-op (d77)")

    # THE ENTRY ITSELF: a heading naming the benchmark task AND its date. The
    # task id appearing in a candidates table is a citation, not a result.
    assert re.search(
        rf"^#+\s.*{re.escape(BENCH_TASK)}.*\b20\d{{2}}-\d{{2}}-\d{{2}}\b",
        doc, re.M), (
        f"the doc has no dated entry heading for {BENCH_TASK}; a task id in a "
        f"candidates table is not an entry")

    # both exact model ids, verbatim
    for mid in (OPUS_ID, SONNET_ID):
        assert mid in doc, f"entry does not name the exact model id {mid!r}"

    # thinking + effort settings, and the trial count
    assert re.search(r"thinking", doc, re.I), "entry states no `thinking` setting"
    assert re.search(r"effort", doc, re.I), "entry states no `effort` setting"
    assert re.search(r"\b(\d+)\s*(trials?|per arm)", doc, re.I) or re.search(
        r"trials?\b[^\n]*\b\d+", doc, re.I), "entry states no trial count"


# ── T2 ─────────────────────────────────────────────────────────────────────
def test_t2_every_measured_row_is_named_in_the_benchmark_doc():
    """THE DESIGN'S OWN GATE, IN CODE.

    "No tier goes default without a MODEL-TIERING-BENCHMARK.md entry." DESIGN-v6
    asserted that in prose and then broke it in the same section (d80). A rule
    that lives only in prose is a rule that a document can violate about itself.

    Mutation-proof: add a fake `("worker", "narrow")` row at status="measured"
    that the doc does not name → this test goes RED at the assert below. A clean
    corpus cannot prove its own guard (d64).
    """
    doc = _doc()
    measured = {k: v for k, v in MODEL_TIERS.items() if v["status"] == "measured"}

    if not measured:
        # An honest negative / a costed deferral. Assert BOTH halves: that no row
        # claims measured, and that the doc SAYS WHY the flip was withheld.
        assert re.search(r"no tier is measured|flip is (refused|withheld|deferred)",
                         doc, re.I), (
            "no MODEL_TIERS row is measured, but the doc does not say why the "
            "flip was withheld — an unexplained absence is not an honest negative")
        return

    # A BARE KEY-SUBSTRING CHECK WOULD BE VACUOUS. The doc's "what this does not
    # license" table names EVERY tier key, including the unmeasured ones — so
    # `key in doc` passes for a row that the doc explicitly calls unmeasured.
    # Require the key to appear on a line that calls it `measured`, where the
    # \b guards stop `unmeasured` from matching.
    for (role, task_class), tier in measured.items():
        key = _tier_key_str(role, task_class)
        assert key in doc, (
            f"MODEL_TIERS row {key} claims status='measured' but "
            f"{_DOC.name} never names it. This is exactly d80: a tier labelled "
            f"measured on the authority of an entry that does not exist.")

        backed = [ln for ln in doc.splitlines()
                  if key in ln and re.search(r"\bmeasured\b", ln, re.I)]
        assert backed, (
            f"MODEL_TIERS row {key} claims status='measured', and the doc names "
            f"the key — but on no line that calls it measured. The doc lists "
            f"every tier key (including the ones it calls UNmeasured), so naming "
            f"is not backing. d80 is a tier labelled measured on the authority "
            f"of an entry that does not assert it.")

        assert tier["benchmark_task"].split(":")[0] in doc, (
            f"measured row {key} names benchmark {tier['benchmark_task']!r}, "
            f"which the doc does not carry")
        assert tier["model"] in doc, (
            f"measured row {key} resolves to {tier['model']!r}, a model the "
            f"benchmark doc does not name")


def test_t2b_the_guard_is_not_vacuous():
    """T2's loop must actually iterate over something real, and its key-spelling
    must match the doc's. Without this, T2 passes trivially forever."""
    doc = _doc()
    # the tier-key spelling T2 searches for is the spelling the doc uses
    assert _tier_key_str("worker", "coding") in doc, (
        "the doc does not spell tier keys the way T2 searches for them; T2 "
        "would pass vacuously for any measured row")
    assert MODEL_TIERS, "MODEL_TIERS is empty"


# ── T3 ─────────────────────────────────────────────────────────────────────
def test_t3_no_haiku_in_the_tier_table_or_the_resolution_path():
    """d53 (user ruling) excludes Haiku on cost/judgment grounds; the API
    excludes it on two more (it rejects `effort` outright, and carries a 200K
    context window against our 1M). Not a row, not a fallback, not a comment."""
    blob = repr(sorted(MODEL_TIERS.items(), key=lambda kv: kv[0]))
    assert "haiku" not in blob.lower(), "haiku leaked into MODEL_TIERS"

    for fn in (resolve_model_tier, spawn_model_for):
        src = inspect.getsource(fn)
        assert "haiku" not in src.lower(), (
            f"haiku leaked into the resolution path: {fn.__name__}")

    # NOTE: roles.py's PROSE legitimately says "HAIKU IS NEVER A TIER". That is
    # the guard, not a leak. A module-wide substring ban would forbid the module
    # from naming the thing it excludes — and would fail on this very comment.
    # The ban is on DATA and on the RESOLUTION PATH, which is where a leak could
    # actually select a model.
    for (role, tc), tier in MODEL_TIERS.items():
        assert "haiku" not in tier["model"].lower(), (
            f"tier ({role},{tc}) resolves to a haiku model")


# ── T4 ─────────────────────────────────────────────────────────────────────
def test_t4_the_spawn_path_carries_only_what_the_tier_row_declares():
    """THE ANTI-INERT-FIELD PIN, and it is the lesson a4b paid for.

    a4's T5 pinned that every row declared `thinking` and `effort`, and called
    that the guarantee that a benchmark's two arms differ only in the model. It
    was not. NOTHING READ EITHER FIELD: `spawn_model_for` returns a model string
    and `pty_launcher.build_argv` emits only `["--model", model]`. A row could
    declare `thinking="disabled"` while the spawned shell thought freely — and
    that is exactly what production did.

    So the row is `{model, status}` (+`benchmark_task`), per DESIGN-v6 line 490,
    and this test refuses any field the spawn path would silently drop. A
    declared-and-dropped field is worse than an absent one: it reads, to the next
    author, as a setting that is in force.
    """
    allowed = {"model", "status", "benchmark_task"}
    for key, tier in sorted(MODEL_TIERS.items(), key=lambda kv: kv[0]):
        extra = set(tier) - allowed
        assert not extra, (
            f"tier {key} declares {sorted(extra)}, which NO production code "
            f"reads. Wire the Claude Code env/settings surface the harness "
            f"already owns (build_argv/build_env) — do not add an inert field.")
        assert tier["model"] in (OPUS_ID, SONNET_ID), (
            f"tier {key} resolves to an untiered model {tier['model']!r}")
        assert tier["status"] in ("default", "candidate", "measured"), (
            f"tier {key} has status={tier['status']!r}")
