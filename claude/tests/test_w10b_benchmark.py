"""W10b/a4b — the benchmark entry gate. RE-POINTED (2026-08-12 dead-surface
retirement).

This file pinned the sync between `roles.MODEL_TIERS` and
`docs/design/MODEL-TIERING-BENCHMARK.md` (T1: the entry states its settings;
T2: every measured row is doc-backed; T3: no haiku; T4: no inert row fields).
The tier table itself was RETIRED on 2026-08-12 — the v7 WS4 seat registry
(models.json via edp_contracts.seats) is the only role→model binding — so the
doc-sync half of the old gate has no subject. The doc survives as recorded
history (it documents WHY no measured flip ever happened, d80); what is worth
pinning now is that the retirement is total and that the survivors keep the
two properties that were never about the table:

* R1  the tier symbols are GONE from roles.py — a re-added table would be a
      silent second resolver next to the seat registry.
* R2  "haiku" appears nowhere in the surviving resolution path (d53 stands:
      never a tier, never a fallback).
* R3  the benchmark doc still exists as history and still records the honest
      negative (no measured tier / the flip withheld), so the d80 story stays
      readable at the path every old comment cites.
"""

import inspect
from pathlib import Path

from edp_claude.tools import roles as roles_mod
from edp_claude.tools.roles import spawn_model_for

_ROOT = Path(__file__).resolve().parents[1]
_DOC = _ROOT / "docs" / "design" / "MODEL-TIERING-BENCHMARK.md"


def test_r1_the_tier_table_and_its_lookups_are_gone():
    """2026-08-12 dead-surface retirement: the seat registry is the ONLY
    role→model resolver. A resurrected table would silently compete with it."""
    for gone in ("MODEL_TIERS", "resolve_model_tier", "HOST_DEFAULT_MODEL",
                 "SONNET", "DEFAULT_TASK_CLASS", "_OPUS_DEFAULT", "_candidate"):
        assert not hasattr(roles_mod, gone), (
            f"roles.{gone} is back — the W10b tier table was retired "
            "2026-08-12; models.json seats are the only binding")
    # …and nothing in roles.py reads the retired env re-point either
    src = Path(inspect.getfile(roles_mod)).read_text(encoding="utf-8")
    assert 'environ.get("EDP_WORKER_SONNET_MODEL"' not in src


def test_r2_no_haiku_in_the_surviving_resolution_path():
    """d53 (user ruling) excludes Haiku on cost/judgment grounds. The table it
    could have leaked into is gone; the surviving path must stay clean."""
    assert "haiku" not in inspect.getsource(spawn_model_for).lower()


def test_r3_the_benchmark_doc_survives_as_history():
    """The doc is HISTORY, not a live contract: it records the a4b benchmark
    and the honest negative that no tier was ever measured (d80). Deleting it
    would orphan every decision comment that cites it."""
    assert _DOC.is_file(), f"{_DOC} does not exist"
    doc = _DOC.read_text(encoding="utf-8")
    assert "a4b/BENCH-WORKER-CODING" in doc
    # the honest negative stays stated
    lowered = doc.lower()
    assert ("no tier is measured" in lowered or "flip is withheld" in lowered
            or "flip is refused" in lowered or "flip is deferred" in lowered)
