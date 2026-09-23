"""S18 — RSI phase 1: the self-triggered retrieval regression tripwire (report-9a85d0418e §9).

One test group per story criterion: c1 trigger semantics (c-b32f4d6dfb), c2 code identity (c-02a7344e05),
c3 tripwire (c-2592f51022), c4 fail closed (c-a0038d9443), c5 evaluator immutability (c-4e4dce3a13),
c6 no generative calls (c-ebc2d7d550), c7 disable and upgrade (definition of done)."""

from __future__ import annotations

import ast
import hashlib
import json
import shutil
import sqlite3
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest

from edp8 import rsi
from edp8.board import Board
from edp8.schemas import Decision, DecisionStatus, KgLink, Ticket, now
from edp8.store import Store

V8 = Path(__file__).resolve().parents[1]
SYNTHETIC = V8 / "tests" / "rsi" / "synthetic.json"
TARGET = "epic-rsitest"
PLENTY = lambda: 64_000.0  # noqa: E731 — free MB: never under the RAM floor in a unit test


def _manifest(tmp_path: Path, exams: list[dict] | None = None, name: str = "manifest.json") -> Path:
    p = tmp_path / name
    p.write_text(json.dumps({"finding": {"ticket_id": TARGET, "to": "architect"},
                             "exams": exams if exams is not None else
                             [{"name": "synthetic", "path": str(SYNTHETIC), "required": "required_ids"}]}),
                 encoding="utf-8")
    return p


def _code(tmp_path: Path) -> rsi.CodeIdentity:
    """A CodeIdentity over private copies of the four retrieval files (so a test can edit 'the code')."""
    d = tmp_path / "code"
    d.mkdir(exist_ok=True)
    files = {}
    for n, p in rsi.module_files().items():
        dst = d / n
        if not dst.exists():
            shutil.copyfile(p, dst)
        files[n] = dst
    return rsi.CodeIdentity(files)


def _board(path: str | Path = ":memory:") -> Board:
    store = Store(path)
    if store.get("ticket", TARGET) is None:
        store.put("ticket", Ticket(id=TARGET, kind="epic", work_type="feature", title="rsi test epic",
                                   epic_id=TARGET))
    return Board(store)


@pytest.fixture
def world(tmp_path):
    b = _board()
    return {"board": b, "store": b.store, "manifest": _manifest(tmp_path), "code": _code(tmp_path)}


def _tick(w, **kw):
    kw.setdefault("manifest", w["manifest"])
    kw.setdefault("code", w["code"])
    kw.setdefault("free_mb", PLENTY)
    return rsi.tick(w["store"], None, board=w["board"], **kw)


def _add_decisions(store: Store, n: int, start: int = 0) -> list[str]:
    ids = []
    for i in range(start, start + n):
        d = Decision(id=f"dec-fp{i:04d}", scope=TARGET, text=f"fingerprint row {i}")
        store.put("decision", d)
        ids.append(d.id)
    return ids


def _age_last_consumed(store: Store, hours: float) -> None:
    st = rsi._state(store)
    st.last_consumed["at"] = (now() - timedelta(hours=hours)).isoformat()
    store.put("rsi_state", st)


def _runs(store: Store) -> list:
    return store.query("rsi_run", limit=1000)


def _findings(store: Store) -> list:
    return [m for m in store.query("message", {"kind": "finding"}, limit=1000)]


# ============================================================================ c1 trigger semantics
def test_c1_cold_bootstrap_writes_one_run_and_sets_last_pass(world):
    res = _tick(world)
    assert res["verdict"] == "pass"
    runs = _runs(world["store"])
    assert [r.trigger for r in runs] == ["bootstrap"]
    st = rsi._state(world["store"])
    assert st.last_pass_run == runs[0].id and st.in_flight is None
    assert st.last_consumed["run_id"] == runs[0].id
    assert _tick(world)["verdict"] is None  # nothing changed: no second run
    assert len(_runs(world["store"])) == 1


def test_c1_debounce_19_rows_no_run_20th_gives_one_t1(world):
    _tick(world)
    _add_decisions(world["store"], 19)
    res = _tick(world)
    assert res["verdict"] is None and "debounced" in res["reason"]
    assert len(_runs(world["store"])) == 1
    _add_decisions(world["store"], 1, start=19)
    res = _tick(world)
    assert res["verdict"] == "pass"
    assert [r.trigger for r in _runs(world["store"])] == ["bootstrap", "T1"]
    assert _tick(world)["verdict"] is None  # consumed: exactly one T1


def test_c1_withdrawal_only_change_triggers(world):
    ids = _add_decisions(world["store"], 3)
    _tick(world)
    _age_last_consumed(world["store"], 25)  # debounce satisfied by age, not by row count
    fp0 = rsi.fingerprint(rsi.corpus_rows(world["store"]))
    d = world["store"].get("decision", ids[0])
    d.status = DecisionStatus.withdrawn
    world["store"].put("decision", d)
    assert rsi.fingerprint(rsi.corpus_rows(world["store"])) != fp0
    assert _tick(world)["verdict"] == "pass"
    assert [r.trigger for r in _runs(world["store"])] == ["bootstrap", "T1"]


def test_c1_count_preserving_replacement_triggers(world):
    ids = _add_decisions(world["store"], 3)
    _tick(world)
    _age_last_consumed(world["store"], 25)
    s = world["store"]
    live_before = len([d for d in s.query("decision", limit=100) if d.status == "live"])
    fp0 = rsi.fingerprint(rsi.corpus_rows(s))
    old = s.get("decision", ids[0])
    old.status = DecisionStatus.replaced
    s.put("decision", old)
    s.put("decision", Decision(id="dec-fpnew", scope=TARGET, text="fingerprint row 0, reworded",
                               replaces=[old.id]))
    s.put("kglink", KgLink(id="kg-fpnew", from_id="dec-fpnew", to_id=old.id, kind="replaces"))
    assert len([d for d in s.query("decision", limit=100) if d.status == "live"]) == live_before
    assert rsi.fingerprint(rsi.corpus_rows(s)) != fp0
    assert _tick(world)["verdict"] == "pass"
    assert [r.trigger for r in _runs(s)] == ["bootstrap", "T1"]


def test_c1_two_concurrent_ticks_produce_one_run(tmp_path):
    db = tmp_path / "board.db"
    _board(db)  # create the DB + target once
    boards = [_board(db), _board(db)]  # two connections: a CLI tick and the board thread
    man, code = _manifest(tmp_path), _code(tmp_path)
    gate = threading.Barrier(2)
    out = []

    def go(b):
        gate.wait()
        out.append(rsi.tick(b.store, None, board=b, manifest=man, code=code, free_mb=PLENTY))

    ths = [threading.Thread(target=go, args=(b,)) for b in boards]
    [t.start() for t in ths]
    [t.join(30) for t in ths]
    assert sorted(str(r["verdict"]) for r in out) in (["None", "pass"], ["pass", "skipped"])
    assert len(_runs(Store(db))) == 1


def test_c1_live_lease_blocks_and_expired_lease_is_taken(world):
    s = world["store"]
    st = rsi._state(s)
    st.in_flight = {"run_id": "rsi-other", "lease_until": (now() + timedelta(minutes=5)).isoformat()}
    s.put("rsi_state", st)
    assert _tick(world)["verdict"] == "skipped"
    assert _runs(s) == []
    st.in_flight["lease_until"] = (now() - timedelta(seconds=1)).isoformat()  # the holder crashed
    s.put("rsi_state", st)
    assert _tick(world)["verdict"] == "pass"


def test_c1_pending_trigger_fires_once_after_restart(tmp_path):
    db = tmp_path / "board.db"
    man, code = _manifest(tmp_path), _code(tmp_path)
    b1 = _board(db)
    assert rsi.tick(b1.store, None, board=b1, manifest=man, code=code, free_mb=PLENTY)["verdict"] == "pass"
    _add_decisions(b1.store, 20)  # a trigger becomes pending ...
    b1.store.close()               # ... and the process dies before any tick sees it
    b2 = _board(db)                # restart: a new process, new connection, same DB
    r1 = rsi.tick(b2.store, None, board=b2, manifest=man, code=code, free_mb=PLENTY)
    r2 = rsi.tick(b2.store, None, board=b2, manifest=man, code=code, free_mb=PLENTY)
    assert (r1["verdict"], r2["verdict"]) == ("pass", None)
    assert [r.trigger for r in _runs(b2.store)] == ["bootstrap", "T1"]


# ============================================================================ c2 code identity
def test_c2_imported_knowledge_change_gives_t2(world, tmp_path):
    _tick(world)
    kp = world["code"].files["knowledge.py"]
    kp.write_bytes(kp.read_bytes() + b"\n# a retrieval change\n")
    world["code"] = rsi.CodeIdentity(world["code"].files)  # the restarted process imports the new code
    res = _tick(world)
    assert res["verdict"] == "pass"
    assert [r.trigger for r in _runs(world["store"])] == ["bootstrap", "T2"]


def test_c2_unrelated_file_change_gives_no_run(world):
    _tick(world)
    other = world["code"].files["knowledge.py"].parent / "board.py"
    other.write_text("# an unrelated module edited by a commit\n", encoding="utf-8")
    world["code"] = rsi.CodeIdentity(world["code"].files)  # restart after that commit
    assert _tick(world)["verdict"] is None
    assert len(_runs(world["store"])) == 1


def test_c2_dirty_disk_edit_holds_restart_pending_without_consuming(world):
    _tick(world)
    kp = world["code"].files["knowledge.py"]
    kp.write_bytes(kp.read_bytes() + b"\n# edited on disk, process not restarted\n")
    before = rsi._state(world["store"]).last_consumed
    res = _tick(world)
    assert res["verdict"] == "hold" and res["hold_reason"].startswith("restart pending")
    st = rsi._state(world["store"])
    assert st.last_consumed == before and st.last_attempt["outcome"] == "hold"
    assert len(_runs(world["store"])) == 1
    world["code"] = rsi.CodeIdentity(world["code"].files)  # the restart: the held trigger now fires
    assert _tick(world)["verdict"] == "pass"
    assert [r.trigger for r in _runs(world["store"])] == ["bootstrap", "T2"]


# ============================================================================ c3 tripwire
PATH_SWITCHES = {  # declared path -> the isolated lookup switch that disables it (and what it implies)
    "fts": ({"fts": False}, {"fts"}),
    "dense": ({"dense": False}, {"dense"}),
    "1-hop": ({"max_hops": 0}, {"1-hop", "2-hop"}),
    "2-hop": ({"max_hops": 1}, {"2-hop"}),
}


def test_c3_manifest_lists_fixture_synthetic_and_skips_exam4():
    m = json.loads((V8 / "tests" / "rsi" / "manifest.json").read_text(encoding="utf-8"))
    by = {e["name"]: e for e in m["exams"]}
    assert by["exam_regressions"] == {"name": "exam_regressions", "path": "tests/exam_regressions.json",
                                      "required": "expected_ids"}
    assert by["synthetic"]["path"] == "tests/rsi/synthetic.json" and by["synthetic"]["required"] == "required_ids"
    assert by["exam4"]["skip"].startswith("no required evidence")
    syn = json.loads(SYNTHETIC.read_text(encoding="utf-8"))
    assert {p for q in syn["questions"] for p in q["paths"]} == {"fts", "dense", "1-hop", "2-hop"}
    assert all(q["required_ids"] for q in syn["questions"])


@pytest.mark.parametrize("path", sorted(PATH_SWITCHES))
def test_c3_disabling_a_path_regresses_exactly_its_questions(world, path):
    assert _tick(world)["verdict"] == "pass"  # clean baseline
    assert _findings(world["store"]) == []    # the clean run posts nothing
    switch, disabled = PATH_SWITCHES[path]
    res = _tick(world, force=True, paths=switch)
    syn = json.loads(SYNTHETIC.read_text(encoding="utf-8"))
    need = {q["n"]: q["required_ids"] for q in syn["questions"] if disabled & set(q["paths"])}
    assert res["verdict"] == "regressed"
    run = world["store"].get("rsi_run", res["run"])
    missing = {p["n"]: p["missing_ids"] for p in run.per_question if p["missing_ids"]}
    assert missing == need
    assert {r["n"]: r["lost_ids"] for r in run.regressions} == need
    assert len(_findings(world["store"])) == 1


def test_c3_regressed_run_posts_exactly_one_finding_even_on_retick(world):
    _tick(world)
    r1 = _tick(world, force=True, paths={"fts": False})
    r2 = _tick(world, force=True, paths={"fts": False})  # re-tick: the same loss again
    assert r1["verdict"] == r2["verdict"] == "regressed"
    f = _findings(world["store"])
    assert len(f) == 1 and f[0].ticket_id == TARGET and r1["run"] in f[0].text
    assert r2["finding_msg_id"] == f[0].id
    run = world["store"].get("rsi_run", r1["run"])
    assert rsi.post_finding(world["store"], world["board"], run, {"ticket_id": TARGET, "to": "architect"},
                            None) == f[0].id  # idempotent by run id
    assert len(_findings(world["store"])) == 1
    st = rsi._state(world["store"])
    assert st.last_pass_run == _runs(world["store"])[0].id  # a regression never becomes the baseline


def test_c3_finding_goes_to_the_manifest_address_verbatim(world, tmp_path):
    """The tracked manifest names a seat id; the finding is posted `to` exactly that id (m-fe6450fe8e)."""
    to = json.loads(rsi.MANIFEST.read_text(encoding="utf-8"))["finding"]["to"]
    assert to == "architect.epic-6a8a6020fd"
    world["board"].participant_create("agent", "architect", to, id_=to)
    m = tmp_path / "m2.json"
    m.write_text(json.dumps({"finding": {"ticket_id": TARGET, "to": to},
                             "exams": [{"path": str(SYNTHETIC), "required": "required_ids"}]}), encoding="utf-8")
    _tick(world, manifest=m)
    res = _tick(world, manifest=m, force=True, paths={"max_hops": 0})
    f = _findings(world["store"])
    assert res["verdict"] == "regressed" and len(f) == 1
    assert f[0].to == to and f[0].kind == "finding" and f[0].created_by == "rsi"


# ============================================================================ c4 fail closed
def _assert_error_not_consumed(world, res, needle):
    assert res["verdict"] == "error" and needle in (res["error"] or "")
    st = rsi._state(world["store"])
    assert st.last_pass_run is None and st.last_consumed is None  # the trigger is still pending
    assert all(r.verdict == "error" for r in _runs(world["store"]))


def test_c4_missing_manifest_is_error(world, tmp_path):
    _assert_error_not_consumed(world, _tick(world, manifest=tmp_path / "absent.json"), "manifest unreadable")


@pytest.mark.parametrize("body", ["{not json", json.dumps({"exams": []}),
                                  json.dumps({"exams": [{"path": "x.json"}], "finding": {"ticket_id": TARGET, "to": "architect"}}),
                                  json.dumps({"exams": [{"path": "x.json", "required": "expected_ids"}]})])
def test_c4_malformed_manifest_is_error(world, tmp_path, body):
    p = tmp_path / "bad.json"
    p.write_text(body, encoding="utf-8")
    _assert_error_not_consumed(world, _tick(world, manifest=p), "manifest malformed")


def test_c4_missing_exam_is_error(world, tmp_path):
    m = _manifest(tmp_path, [{"path": str(tmp_path / "gone.json"), "required": "expected_ids"}])
    _assert_error_not_consumed(world, _tick(world, manifest=m), "exam missing")


@pytest.mark.parametrize("q", [{"epic": TARGET, "question": "q?"},            # no required evidence
                               {"question": "q?", "expected_ids": ["dec-x"]}])  # no epic
def test_c4_malformed_exam_is_error(world, tmp_path, q):
    e = tmp_path / "exam.json"
    e.write_text(json.dumps([q]), encoding="utf-8")
    m = _manifest(tmp_path, [{"path": str(e), "required": "expected_ids"}])
    _assert_error_not_consumed(world, _tick(world, manifest=m), "exam malformed")


def test_c4_lookup_exception_is_error_and_never_pass(world, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("index exploded")
    monkeypatch.setattr(rsi.knowledge, "wired_lookup", boom)
    _assert_error_not_consumed(world, _tick(world), "lookup failed on synthetic#1")


def test_c4_repeated_identical_error_does_not_pile_up_rows(world, tmp_path):
    bad = tmp_path / "absent.json"
    _tick(world, manifest=bad)
    res = _tick(world, manifest=bad)
    assert res["verdict"] == "error" and res.get("repeat")
    assert len(_runs(world["store"])) == 1


def test_c4_missing_finding_target_is_error(tmp_path):
    b = Board(Store(":memory:"))  # no target epic on this board
    res = rsi.tick(b.store, None, board=b, manifest=_manifest(tmp_path), code=_code(tmp_path), free_mb=PLENTY)
    assert res["verdict"] == "error" and TARGET in res["error"]


def test_c4_low_ram_and_lost_dense_hold(world):
    res = _tick(world, free_mb=lambda: 100.0)
    assert res["verdict"] == "hold" and res["hold_reason"].startswith("low RAM")
    assert _runs(world["store"]) == []

    class Idx:
        def __init__(self, active, warming=False):
            self.active, self.warming = active, warming

        def status(self):
            return {"embeddings_active": self.active, "warming": self.warming, "embedder": "fake"}

    s = world["store"]
    res = rsi.tick(s, Idx(False, warming=True), board=world["board"], manifest=world["manifest"],
                   code=world["code"], free_mb=PLENTY)
    assert res["verdict"] == "hold" and "warming" in res["hold_reason"]
    assert _tick(world)["verdict"] == "pass"
    base = _runs(s)[0]
    base.identity["dense_available"] = True  # pretend the baseline pass had the dense leg
    s.put("rsi_run", base)
    res = _tick(world, force=True)
    assert res["verdict"] == "hold" and "dense unavailable" in res["hold_reason"]


# ---------------------------------------------------------------- second opinion 20260923T053423Z-dab188b9
def test_so1_a_swallowed_leg_failure_is_an_error_not_a_pass(world, monkeypatch):
    """knowledge.lookup swallows a failing FTS leg for seats; the tripwire must still fail closed."""
    real = Store.fts_search

    def broken(self, *a, **k):
        if self.path == ":memory:" and self is not world["store"]:
            raise RuntimeError("fts index corrupt")
        return real(self, *a, **k)
    monkeypatch.setattr(Store, "fts_search", broken)
    _assert_error_not_consumed(world, _tick(world), "retrieval leg fts_search: RuntimeError")


def test_so2_manifest_and_exam_hashes_persist_on_the_run(world):
    res = _tick(world)
    run = world["store"].get("rsi_run", res["run"])
    assert run.identity["manifest_hash"] and list(run.identity["exam_hashes"]) == [str(SYNTHETIC)]
    assert run.identity["exam_hashes"][str(SYNTHETIC)] == hashlib.sha256(SYNTHETIC.read_bytes()).hexdigest()


def test_so3_an_expired_holder_cannot_commit_over_the_new_holder(world, monkeypatch):
    real = rsi.replay

    def slow(*a, **k):  # while this tick replays, its lease expires and another tick takes it
        st = rsi._state(world["store"])
        st.in_flight = {"run_id": "rsi-newholder", "lease_until": (now() + timedelta(minutes=5)).isoformat()}
        world["store"].put("rsi_state", st)
        return real(*a, **k)
    monkeypatch.setattr(rsi, "replay", slow)
    res = _tick(world)
    assert res["verdict"] == "skipped" and "lease lost" in res["reason"]
    assert _runs(world["store"]) == [] and rsi._state(world["store"]).last_pass_run is None


@pytest.mark.parametrize("req", ["dec-x", ["dec-x", ""], [1], []])
def test_so4_required_ids_must_be_a_list_of_id_strings(world, tmp_path, req):
    e = tmp_path / "exam.json"
    e.write_text(json.dumps([{"epic": TARGET, "question": "q?", "expected_ids": req}]), encoding="utf-8")
    m = _manifest(tmp_path, [{"path": str(e), "required": "expected_ids"}])
    _assert_error_not_consumed(world, _tick(world, manifest=m), "exam malformed")


def test_so4_duplicate_question_numbers_and_exam_names_are_errors(world, tmp_path):
    e = tmp_path / "exam.json"
    e.write_text(json.dumps([{"n": 1, "epic": TARGET, "question": "a?", "expected_ids": ["dec-a"]},
                             {"n": 1, "epic": TARGET, "question": "b?", "expected_ids": ["dec-b"]}]),
                 encoding="utf-8")
    m = _manifest(tmp_path, [{"path": str(e), "required": "expected_ids"}])
    _assert_error_not_consumed(world, _tick(world, manifest=m), "repeats question n=1")
    m2 = _manifest(tmp_path, [{"name": "x", "path": str(SYNTHETIC), "required": "required_ids"},
                              {"name": "x", "path": str(SYNTHETIC), "required": "required_ids"}], "m2.json")
    _assert_error_not_consumed(world, _tick(world, manifest=m2), "names must be unique")


def test_so5_any_record_field_lookup_reads_changes_the_fingerprint(world):
    s = world["store"]
    from edp8.schemas import Lesson
    s.put("decision", Decision(id="dec-dom", scope=TARGET, text="domains row"))
    s.put("lesson", Lesson(id="les-1", domain="ui", topic="x", text="a lesson"))
    fp = rsi.fingerprint(rsi.corpus_rows(s))
    d = s.get("decision", "dec-dom")
    d.domains = ["ui"]
    s.put("decision", d)
    fp2 = rsi.fingerprint(rsi.corpus_rows(s))
    les = s.get("lesson", "les-1")
    les.topic = "y"
    s.put("lesson", les)
    assert len({fp, fp2, rsi.fingerprint(rsi.corpus_rows(s))}) == 3


def test_so6_loaded_identity_is_what_the_module_executed(monkeypatch):
    from edp8 import knowledge
    assert rsi.CodeIdentity.from_process().stale() == []
    monkeypatch.setattr(knowledge, "SOURCE_SHA256", "0" * 64)  # the process ran older bytes than disk holds
    ci = rsi.CodeIdentity.from_process()
    assert ci.loaded["knowledge.py"] == "0" * 64 and ci.stale() == ["knowledge.py"]


def test_so7_unresolvable_finding_recipient_is_an_error(world, tmp_path):
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"finding": {"ticket_id": TARGET, "to": "nobody.registered"},
                             "exams": [{"path": str(SYNTHETIC), "required": "required_ids"}]}), encoding="utf-8")
    _assert_error_not_consumed(world, _tick(world, manifest=m), "nobody.registered")


def test_so8_same_loss_under_a_new_identity_gets_its_own_finding(world):
    _tick(world)
    r1 = _tick(world, force=True, paths={"fts": False})
    _add_decisions(world["store"], 20)  # the corpus moves: a new identity, the same loss
    r2 = _tick(world, paths={"fts": False})
    assert r1["verdict"] == r2["verdict"] == "regressed"
    assert r1["finding_msg_id"] != r2["finding_msg_id"] and len(_findings(world["store"])) == 2


def test_so9_repeated_identical_errors_stay_one_row(world, tmp_path):
    bad = tmp_path / "absent.json"
    for _ in range(4):
        _tick(world, manifest=bad)
    assert len(_runs(world["store"])) == 1


# ============================================================================ c5 evaluator immutability
def _hashes(paths):
    return {str(p): hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths}


def test_c5a_manifest_files_and_exam_py_unchanged_by_a_tick(tmp_path):
    # the REAL tracked manifest: every listed file that exists, plus exam.py
    m = json.loads(rsi.MANIFEST.read_text(encoding="utf-8"))
    files = [rsi.MANIFEST, rsi.module_files()["exam.py"]]
    files += [rsi._resolve(e["path"]) for e in m["exams"] if rsi._resolve(e["path"]).exists()]
    before = _hashes(files)
    b = _board()
    b.store.put("ticket", Ticket(id="epic-44a0576511", kind="epic", work_type="feature", title="x",
                                 epic_id="epic-44a0576511"))
    b.participant_create("agent", "architect", m["finding"]["to"], id_=m["finding"]["to"])
    res = rsi.tick(b.store, None, board=b, code=_code(tmp_path), free_mb=PLENTY)
    assert res["verdict"] == "pass"
    assert _hashes(files) == before


WRITE_ATTRS = {"write_text", "write_bytes", "unlink", "rename", "replace", "rmdir", "mkdir", "touch",
               "chmod", "remove", "makedirs", "removedirs", "truncate", "writelines", "open", "write"}
ALLOWED_PUT_TYPES = {"policy", "rsi_run", "rsi_state", "message"}
ALLOWED_BOARD_CALLS = {"ticket", "resolve_recipient", "_index", "_emit"}


def test_c5b_rsi_has_no_write_path_for_the_evaluator():
    src = (V8 / "src" / "edp8" / "rsi.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    # the one exception: synthetic_world fills its OWN in-memory store (never the board DB) with the fixture
    syn = next(f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) and f.name == "synthetic_world")
    assert 's = Store(":memory:")' in ast.unparse(syn).replace("'", '"')
    scratch = {id(n) for n in ast.walk(syn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "put" and isinstance(n.func.value, ast.Name) and n.func.value.id == "s"}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        if isinstance(node, ast.ImportFrom):
            imported |= {a.name for a in node.names} | {(node.module or "").split(".")[0]}
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                assert f.id != "open", "rsi.py must not open files (read via Path.read_bytes)"
            if isinstance(f, ast.Attribute):
                assert f.attr not in WRITE_ATTRS, f"file write path in rsi.py: .{f.attr}()"
                if f.attr == "put" and id(node) not in scratch:  # every board-store write names one of the RSI tables or the finding message
                    assert node.args and isinstance(node.args[0], ast.Constant) \
                        and node.args[0].value in ALLOWED_PUT_TYPES, ast.unparse(node)
                if isinstance(f.value, ast.Name) and f.value.id == "board":
                    assert f.attr in ALLOWED_BOARD_CALLS, f"board write path in rsi.py: board.{f.attr}()"
    for bad in ("shutil", "subprocess", "tempfile", "exam", "consult", "pool_adapter", "run_packs"):
        assert bad not in imported, f"rsi.py imports {bad}"
    for bad in ("record_decision", "record_claim", "withdraw_", "set_binding", "delete(", "exam.run_packs"):
        assert bad not in src, bad


# ============================================================================ c6 no generative calls
def test_c6_tick_passes_with_every_model_entry_point_raising(world, monkeypatch):
    import socket
    import subprocess

    from edp8 import consult, pool_adapter, search

    def forbidden(*a, **k):
        raise AssertionError("generative / external call during an rsi tick")

    for mod in (consult,):
        for name in dir(mod):
            if callable(getattr(mod, name)) and not name.startswith("__") and getattr(getattr(mod, name), "__module__", "") == mod.__name__:
                monkeypatch.setattr(mod, name, forbidden)
    monkeypatch.setattr(pool_adapter, "spawn", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(search, "make_embedder", forbidden)  # not even a model load
    assert _tick(world)["verdict"] == "pass"
    assert _tick(world, force=True, paths={"dense": False})["verdict"] == "regressed"


# ============================================================================ c7 disable and upgrade
def test_c7_thread_stops_within_one_loop_when_flag_unset(world, monkeypatch):
    monkeypatch.setenv("EDP8_RSI", "1")
    calls = []
    monkeypatch.setattr(rsi, "tick", lambda *a, **k: calls.append(1) or {"verdict": None})
    th, stop = rsi.start_thread(world["board"], interval_s=0.05, first_wait_s=0.01)
    deadline = time.monotonic() + 5
    while not calls and time.monotonic() < deadline:
        time.sleep(0.01)
    assert calls and th.is_alive()
    monkeypatch.delenv("EDP8_RSI")
    th.join(1.0)  # one loop is 0.05 s
    assert not th.is_alive()
    stop.set()


def test_c7_stop_event_ends_the_thread(world, monkeypatch):
    monkeypatch.setenv("EDP8_RSI", "1")
    monkeypatch.setattr(rsi, "tick", lambda *a, **k: {"verdict": None})
    th, stop = rsi.start_thread(world["board"], interval_s=3600, first_wait_s=3600)
    stop.set()
    th.join(1.0)
    assert not th.is_alive()


def _pre_phase1_db(path: Path) -> None:
    Store(path).close()
    con = sqlite3.connect(path)
    for t in ("policy", "rsi_run", "rsi_state"):
        con.execute(f"DROP TABLE IF EXISTS {t}")
    con.commit()
    con.close()


def test_c7_pre_phase1_db_boots_creates_tables_and_p0_once(tmp_path, monkeypatch):
    from edp8.service import create_app
    monkeypatch.delenv("EDP8_RSI", raising=False)
    db = tmp_path / "old.db"
    _pre_phase1_db(db)
    tables = {r[0] for r in sqlite3.connect(db).execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not tables & {"policy", "rsi_run", "rsi_state"}
    app = create_app(Board(Store(db)))
    assert app.state.rsi_stop is None  # EDP8_RSI unset: no thread
    s = Store(db)
    pols = s.query("policy", limit=10)
    assert [(p.id, p.status) for p in pols] == [("p-0", "incumbent")]
    assert pols[0].knobs["hops"] == 2 and pols[0].knobs["rrf_k"] == 60
    create_app(Board(Store(db)))  # second boot
    assert len(Store(db).query("policy", limit=10)) == 1


def test_c7_db_refuses_a_second_incumbent(tmp_path):
    from edp8.schemas import Policy
    s = Store(tmp_path / "b.db")
    rsi.ensure_p0(s)
    with pytest.raises(sqlite3.IntegrityError):
        s.put("policy", Policy(id="p-1", status="incumbent"))


def test_c7_thread_starts_only_with_flag(tmp_path, monkeypatch):
    from edp8.service import create_app
    monkeypatch.setenv("EDP8_RSI", "1")
    monkeypatch.setattr(rsi, "tick", lambda *a, **k: {"verdict": None})
    app = create_app(Board(Store(tmp_path / "c.db")))
    assert isinstance(app.state.rsi_stop, threading.Event)
    app.state.rsi_stop.set()


def test_cli_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    db = tmp_path / "cli.db"
    _board(db).store.close()
    monkeypatch.setattr(rsi, "_cli_board", lambda d: Board(Store(d)))
    monkeypatch.setattr(rsi, "_free_mb", PLENTY)
    code = rsi.main(["tick", "--dry-run", "--db", str(db), "--manifest", str(_manifest(tmp_path))])
    assert code == 0 and json.loads(capsys.readouterr().out)["dry_run"] is True
    s = Store(db)
    assert s.query("rsi_run", limit=5) == [] and s.get("rsi_state", rsi.STATE_ID) is None
    assert s.query("policy", limit=5) == []
