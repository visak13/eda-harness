"""A guide edit must be visible to a shell that never restarts.

Found live 2026-07-27. `_read_guide_cached` was an `lru_cache` keyed on the
PATH ALONE. The MCP server subprocess outlives turns and wake-from-cron, so
once a long-lived shell had read a guide, every later read returned the
pre-edit body for the rest of that shell's life — silently, with no marker.

That is not a cosmetic staleness bug. The neuron's own launch contract tells
it to fold corrected orchestration rules back into
`docs/guides/orchestrator-launch.md`; the neuron is therefore the WRITER and
the READER of the same file. The comment on the cache said "restart is the
natural invalidation", which is only true when someone restarts — and the one
shell guaranteed not to restart is the one driving the recipe. The rule it
had just written reached nobody, including itself, and the read looked
perfectly successful.

The failure is an absence that looks like a pass: a stale read and a fresh
read are the same successful `get_guide` call.
"""

import inspect
from pathlib import Path

from edp_claude.tools import _tools


def test_edited_guide_is_re_read_by_the_same_process(tmp_path: Path):
    g = tmp_path / "some-guide.md"
    g.write_text("RULE ONE\n", encoding="utf-8")

    first = _tools._read_guide(g)
    assert first == "RULE ONE\n"

    # the edit a neuron folds back into its own launch contract
    g.write_text("RULE ONE\nRULE TWO — the correction\n", encoding="utf-8")

    second = _tools._read_guide(g)
    assert "RULE TWO" in second, (
        "the edit landed on disk and the same process read the pre-edit body"
    )


def test_the_cache_is_still_a_cache(tmp_path: Path):
    """Non-vacuity: the test above would also pass if caching were simply
    removed, which would be a different (slower) system. Pin that an
    UNCHANGED file is served from the cache — same object identity, no
    re-read — so the fix is an invalidation, not a deletion."""
    g = tmp_path / "steady.md"
    g.write_text("UNCHANGED\n", encoding="utf-8")

    a = _tools._read_guide(g)
    b = _tools._read_guide(g)
    assert a is b, "an unchanged guide should still be served from the cache"


def test_a_missing_file_does_not_explode_in_the_stamp(tmp_path: Path):
    """`_read_guide` stats before it reads. A file that vanishes between the
    caller's exists() check and the stat must surface as the read's own error,
    not as an unrelated OSError from the cache key."""
    missing = tmp_path / "gone.md"
    try:
        _tools._read_guide(missing)
    except FileNotFoundError:
        pass  # the read's own error — correct
    else:
        raise AssertionError("expected the missing-file read to raise")


def test_get_guide_goes_through_the_invalidating_reader():
    """The helper being correct is worthless if the tool bypasses it. Both
    call sites — the guide tool and the specialist-doc loader — must route
    through `_read_guide`, never `_read_guide_cached` with a bare path."""
    for fn in (_tools.GetGuide._run, _tools.ConsultSpecialist._run):
        src = inspect.getsource(fn)
        assert "_read_guide_cached(" not in src, (
            f"{fn.__qualname__} bypasses the mtime stamp"
        )
