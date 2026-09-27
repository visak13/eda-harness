"""S11 F6 (t-c2401d98c6): a published version's materialised card never shares a file with another version.

card_name used to truncate `wf-<id>-<version>-<role>` to 41 chars, so two versions of a long workflow id
resolved to one file and publishing v2 overwrote the card v1's epics were pinned to."""
import random
import re
import string

from edp8 import workflow as wf
from edp8.board import Board, materialise_card
from edp8.store import Store

EDP_CARD = re.compile(r"[a-z][a-z0-9-]{0,40}")  # the pool's / seat runners' EDP_CARD pattern


def _two_versions(b: Board, wf_id: str) -> tuple[str, str]:
    first = wf.dump(b.workflows.duplicate("standard@1", new_id=wf_id, by="owner"))
    next(r for r in first["roles"] if r["id"] == "engineer")["card_md"] = "S11 card version ONE"
    b.workflows.save(first, by="owner")
    v1 = b.workflows.publish(wf_id, 1, by="owner")
    second = wf.dump(b.workflows.duplicate(v1.ref, by="owner"))
    next(r for r in second["roles"] if r["id"] == "engineer")["card_md"] = "S11 card version TWO"
    b.workflows.save(second, by="owner")
    v2 = b.workflows.publish(wf_id, 2, by="owner")
    return v1.ref, v2.ref


def test_f6_repro_long_id_versions_keep_distinct_cards(tmp_path):
    """The adversary's repro (tests/s11_review_repro.py::test_published_card_versions_collide), inverted."""
    b = Board(Store(":memory:"))
    r1, r2 = _two_versions(b, "workflow-" + "a" * 35)
    name1, body1 = b.workflows.resolve(r1).card("engineer")
    name2, body2 = b.workflows.resolve(r2).card("engineer")
    old = materialise_card(name1, body1, tmp_path)
    newer = materialise_card(name2, body2, tmp_path)
    assert name1 != name2 and old != newer
    assert "version ONE" in old.read_text(encoding="utf-8") and "version TWO" not in old.read_text(encoding="utf-8")
    assert "version TWO" in newer.read_text(encoding="utf-8")
    for n in (name1, name2):
        assert EDP_CARD.fullmatch(n) and n.startswith("wf-workflow-aaaa")


def test_card_name_is_bounded_readable_and_stable():
    n = wf.card_name("crew", 1, "designer")
    assert n.startswith("wf-crew-1-designer-") and EDP_CARD.fullmatch(n)
    assert n == wf.card_name("crew", 1, "designer")  # deterministic: spawn and startup agree
    long = wf.card_name("x" * 500, 10**9, "r" * 200)
    assert EDP_CARD.fullmatch(long) and len(long) <= 41


def test_distinct_triples_never_share_a_name():
    """Property: over crafted near-misses and a seeded random sample, distinct (id, version, role) triples
    map to distinct names that all match the EDP_CARD pattern."""
    crafted = [
        ("workflow-" + "a" * 35, 1, "engineer"), ("workflow-" + "a" * 35, 2, "engineer"),
        ("workflow-" + "a" * 35, 1, "engineer2"), ("workflow-" + "a" * 36, 1, "engineer"),
        ("Lean", 1, "engineer"), ("lean", 1, "engineer"), ("le_an", 1, "engineer"), ("le-an", 1, "engineer"),
        ("a-1", 2, "b"), ("a", 12, "b"), ("a-12", 1, "b"), ("a", 1, "2-b"), ("a-1-2", 1, "b"),
        ("crew", 1, "designer"), ("crew", 1, "Designer"), ("crew", 1, "designer "),
    ]
    rng = random.Random(0xF6)
    alphabet = string.ascii_letters + string.digits + "-_. "
    sample = {(("".join(rng.choice(alphabet) for _ in range(rng.randint(1, 60)))),
               rng.choice([1, 2, 3, 9, 10, 11, 99, 100, rng.randint(1, 10**6)]),
               "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 30)))) for _ in range(20000)}
    # many versions and roles of the SAME long ids: the shape that collided
    for base in ("workflow-" + "a" * 35, "b" * 60):
        sample |= {(base, v, role) for v in range(1, 60) for role in ("engineer", "architect", "qa", "sme")}
    triples = set(crafted) | sample
    names = {}
    for t in triples:
        n = wf.card_name(*t)
        assert EDP_CARD.fullmatch(n), (t, n)
        assert names.setdefault(n, t) == t, f"{t} and {names[n]} share {n}"
    assert len(names) == len(triples)


def test_board_start_rematerialises_a_missing_pinned_card(tmp_path):
    """Migration: a pinned version's inline card whose file is missing is written at board start; a file
    already there (e.g. one a running seat booted from) is left byte-for-byte alone."""
    b = Board(Store(":memory:"))
    r1, r2 = _two_versions(b, "workflow-" + "a" * 35)
    b.workflows.pin("epic-one", r1)
    b.workflows.pin("epic-two", r2)
    cmd = tmp_path / ".claude" / "commands"
    name1, _ = b.workflows.resolve(r1).card("engineer")
    name2, _ = b.workflows.resolve(r2).card("engineer")
    cmd.mkdir(parents=True)
    (cmd / f"{name2}.md").write_text("seat-booted copy", encoding="utf-8")
    written = b.materialise_pinned_cards(tmp_path)
    assert written == [name1]
    assert "version ONE" in (cmd / f"{name1}.md").read_text(encoding="utf-8")
    assert (cmd / f"{name2}.md").read_text(encoding="utf-8") == "seat-booted copy"
    assert b.materialise_pinned_cards(tmp_path) == []  # idempotent
    # Standard (shipped cards, no card_md) writes nothing
    b2 = Board(Store(":memory:"))
    b2.workflows.pin("epic-std", "standard@1")
    assert b2.materialise_pinned_cards(tmp_path / "std") == []
