"""s-ccdafcb229 (owner m-b0a7f9cda9): board fixes for open pain records, one test per record."""
from __future__ import annotations

import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest

from edp8.board import Board
from edp8.schemas import Check, DocType, Role, TicketKind, TicketStatus, Verdict, WorkType
from edp8.store import Store


@pytest.fixture
def b():
    board = Board(Store(":memory:"))
    ps = {
        "owner": board.participant_create("human", Role.owner, "owner", id_="owner"),
        "arch": board.participant_create("agent", Role.architect, "arch", id_="arch"),
        "eng": board.participant_create("agent", Role.engineer, "eng", id_="eng"),
        "qa": board.participant_create("agent", Role.qa, "qa", id_="qa"),
    }
    return board, ps


def _sign_quick_design(board, ps, t):
    """s-ccdafcb229: the quick engineer's design note is signed off by the owner before any start."""
    from edp8.schemas import Gate
    d = board.doc_create(ps["eng"], doc_type=DocType.note, title="Design", body_md="what/how", scope=t.id)
    board.ticket_update(ps["eng"], t.id, design_ref=d.id)
    board.gate_open(t.id, Gate.design_signoff, by="eng", note="please review")
    board.gate_answer(ps["owner"], t.id, Gate.design_signoff, "go")


def _quick_worked(board, ps):
    t = board.ticket_create(ps["owner"], kind=TicketKind.story, work_type=WorkType.feature, title="Q",
                            words="w", tags=["quick"], assignee="eng")
    _sign_quick_design(board, ps, t)
    board.ticket_update(ps["eng"], t.id, status=TicketStatus.in_progress)
    c = board.criterion_create(ps["eng"], ticket_id=t.id, text="x", check=Check.verdict)
    rep = board.doc_create(ps["eng"], doc_type=DocType.report, title="R", body_md="done", scope=t.id)
    board.criterion_update(ps["eng"], c.id, evidence_ref=rep.id)
    board.ticket_update(ps["eng"], t.id, status=TicketStatus.in_review)
    return t, c


# ------------------------------------------------------------------ p-334391e9 post-commit failure

def test_a_stored_verdict_is_not_reported_as_an_error_when_a_later_step_fails(b, monkeypatch):
    board, ps = b
    t, c = _quick_worked(board, ps)

    def boom(*a, **k):
        raise RuntimeError("event write failed")
    monkeypatch.setattr(board, "_auto_advance", boom)
    warnings: list[str] = []
    out = board.criterion_update(ps["owner"], c.id, verdict=Verdict.passed, evidence_version=1, warnings=warnings)
    assert out.verdict == Verdict.passed
    assert board.store.get("criterion", c.id).verdict == Verdict.passed
    assert warnings and "event write failed" in warnings[0]


def test_a_validation_error_still_raises_before_anything_is_stored(b):
    board, ps = b
    t, c = _quick_worked(board, ps)
    with pytest.raises(Exception):
        board.criterion_update(ps["qa"], c.id, verdict=Verdict.passed)  # qa is not this checker
    assert board.store.get("criterion", c.id).verdict != Verdict.passed


# ------------------------------------------------------------------ p-3fd57a36 sign-off after a start

def _designed_epic_with_story(board, ps):
    from edp8.schemas import Gate
    epic = board.ticket_create(ps["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    d = board.doc_create(ps["arch"], doc_type=DocType.design, title="d", body_md="# d", scope=epic.id)
    board.criterion_create(ps["arch"], ticket_id=epic.id, text="epic works", check=Check.command)
    board.ticket_update(ps["arch"], epic.id, design_ref=d.id)
    story = board.ticket_create(ps["arch"], kind=TicketKind.story, work_type=WorkType.feature, title="S",
                                parent_id=epic.id)
    board.criterion_create(ps["arch"], ticket_id=story.id, text="story works", check=Check.command)
    board.ticket_update(ps["arch"], story.id, design_ref=d.id, status=TicketStatus.designed)
    board.gate_open(epic.id, Gate.design_signoff, by="arch", note="please sign")
    board.ticket_update(ps["arch"], story.id, status=TicketStatus.signed_off)
    return epic, story


def test_design_signoff_stays_answerable_after_a_child_story_started(b):
    from edp8.schemas import Gate
    board, ps = b
    epic, story = _designed_epic_with_story(board, ps)
    board.ticket_update(ps["arch"], story.id, status=TicketStatus.ready)
    board.ticket_update(ps["arch"], story.id, assignee="eng")
    board.ticket_update(ps["eng"], story.id, status=TicketStatus.in_progress)
    assert board.ticket(epic.id).status == TicketStatus.in_progress  # carried forward by the start
    board.gate_answer(ps["owner"], epic.id, Gate.design_signoff, "signed off")
    assert not board.open_gates(epic.id, Gate.design_signoff)
    assert board.ticket(epic.id).status == TicketStatus.in_progress  # never moved backward


# ------------------------------------------------------------------ p-b618055b answered scope lifts the cap

def test_an_answered_scope_gate_lifts_the_story_cap_for_design_signoff(b):
    from edp8.board import STORY_CAP, BoardError
    from edp8.schemas import Gate
    board, ps = b
    epic = board.ticket_create(ps["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    for i in range(STORY_CAP):
        board.ticket_create(ps["arch"], kind=TicketKind.story, work_type=WorkType.feature, title=f"S{i}",
                            parent_id=epic.id)
    board.gate_open(epic.id, Gate.scope, by="arch", note="need more stories")
    board.gate_answer(ps["owner"], epic.id, Gate.scope, "add as many as you want")
    board.ticket_create(ps["arch"], kind=TicketKind.story, work_type=WorkType.feature, title="S9", parent_id=epic.id)
    board.gate_open(epic.id, Gate.design_signoff, by="arch", note="sign")  # no longer refused
    assert board.open_gates(epic.id, Gate.design_signoff)



# ------------------------------------------------------------------ epic walk (owner m-b0a7f9cda9)

def _epic_with_evidenced_story(board, ps):
    from edp8.schemas import Gate
    epic, story = _designed_epic_with_story(board, ps)
    board.gate_answer(ps["owner"], epic.id, Gate.design_signoff, "signed off")
    board.ticket_update(ps["arch"], story.id, assignee="eng")
    board.ticket_update(ps["eng"], story.id, status=TicketStatus.in_progress)
    rep = board.doc_create(ps["eng"], doc_type=DocType.report, title="R", body_md="done", scope=story.id)
    (c,) = board.criteria(story.id)
    board.criterion_update(ps["eng"], c.id, evidence_ref=rep.id)
    return epic, story, c


def test_the_board_carries_the_epic_to_in_review_when_every_story_is_released(b):
    from edp8.schemas import Gate
    board, ps = b
    epic, story, _ = _epic_with_evidenced_story(board, ps)
    assert board.ticket(epic.id).status == TicketStatus.in_progress
    board.ticket_update(ps["eng"], story.id, status=TicketStatus.in_review)
    assert board.ticket(epic.id).status == TicketStatus.in_review  # no seat moved it
    assert board.open_gates(epic.id, Gate.acceptance)


def test_a_story_sent_back_reopens_the_epic(b):
    board, ps = b
    epic, story, c = _epic_with_evidenced_story(board, ps)
    board.ticket_update(ps["eng"], story.id, status=TicketStatus.in_review)
    board.criterion_update(ps["qa"], c.id, verdict=Verdict.failed)
    board.ticket_update(ps["qa"], story.id, status=TicketStatus.in_progress)
    assert board.ticket(epic.id).status == TicketStatus.in_progress


def test_qa_verdicts_close_the_story_and_the_epic_without_a_status_call(b):
    board, ps = b
    epic, story, c = _epic_with_evidenced_story(board, ps)
    board.ticket_update(ps["eng"], story.id, status=TicketStatus.in_review)
    board.criterion_update(ps["qa"], c.id, verdict=Verdict.passed)
    assert board.ticket(story.id).status == TicketStatus.done
    rep = board.doc_create(ps["qa"], doc_type=DocType.report, title="QA", body_md="ok", scope=epic.id)
    (ec,) = board.criteria(epic.id)
    board.criterion_update(ps["qa"], ec.id, evidence_ref=rep.id)
    board.criterion_update(ps["qa"], ec.id, verdict=Verdict.passed)
    assert board.ticket(epic.id).status == TicketStatus.done  # in_review was board-carried


def test_the_architect_may_finish_its_epic_but_not_a_story(b):
    from edp8.board import BoardError
    board, ps = b
    epic, story, c = _epic_with_evidenced_story(board, ps)
    board.ticket_update(ps["owner"], epic.id, assignee="arch")  # arch is THIS epic's architect
    board.ticket_update(ps["eng"], story.id, status=TicketStatus.in_review)
    with pytest.raises(BoardError, match="done is set"):
        board.ticket_update(ps["arch"], story.id, status=TicketStatus.done)
    board.criterion_update(ps["qa"], c.id, verdict=Verdict.passed)
    (ec,) = board.criteria(epic.id)
    ec.verdict, ec.evidence_ref = Verdict.passed, "r"
    board.store.put("criterion", ec)  # verdict stored without the auto-advance (e.g. a board restart)
    allowed = {t["to"]: t["allowed"] for t in board.legal_transitions(ps["arch"], epic.id)["transitions"]}
    assert allowed["done"] and allowed["partial"]
    board.ticket_update(ps["arch"], epic.id, status=TicketStatus.done)
    assert board.ticket(epic.id).status == TicketStatus.done


# ------------------------------------------------------------------ quick design stop (owner m-b13c61ddea)

def test_a_quick_task_cannot_start_before_the_owner_signs_its_design(b):
    from edp8.board import BoardError
    from edp8.schemas import Gate
    board, ps = b
    t = board.ticket_create(ps["owner"], kind=TicketKind.story, work_type=WorkType.feature, title="Q",
                            words="w", tags=["quick"], assignee="eng")
    with pytest.raises(BoardError, match="design sign-off"):
        board.ticket_update(ps["eng"], t.id, status=TicketStatus.in_progress)
    d = board.doc_create(ps["eng"], doc_type=DocType.note, title="Design", body_md="plan", scope=t.id)
    board.ticket_update(ps["eng"], t.id, design_ref=d.id)
    board.gate_open(t.id, Gate.design_signoff, by="eng", note="review please")
    with pytest.raises(BoardError, match="design sign-off"):  # open, not yet answered
        board.ticket_update(ps["eng"], t.id, status=TicketStatus.in_progress)
    board.gate_answer(ps["owner"], t.id, Gate.design_signoff, "approved")
    board.ticket_update(ps["eng"], t.id, status=TicketStatus.in_progress)
    assert board.ticket(t.id).status == TicketStatus.in_progress


def test_a_quick_design_signoff_needs_a_design_note(b):
    from edp8.board import BoardError
    from edp8.schemas import Gate
    board, ps = b
    t = board.ticket_create(ps["owner"], kind=TicketKind.story, work_type=WorkType.feature, title="Q",
                            words="w", tags=["quick"], assignee="eng")
    board.gate_open(t.id, Gate.design_signoff, by="eng", note="review")
    with pytest.raises(BoardError, match="no design note"):
        board.gate_answer(ps["owner"], t.id, Gate.design_signoff, "approved")


# ------------------------------------------------------------------ per-flow card (owner m-b13c61ddea)

def test_an_engineer_on_a_quick_task_gets_the_quick_card_and_nobody_else_does(b):
    from edp8.board import seat_card_env
    board, ps = b
    q = board.ticket_create(ps["owner"], kind=TicketKind.story, work_type=WorkType.feature, title="Q",
                            words="w", tags=["quick"])
    epic = board.ticket_create(ps["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    s = board.ticket_create(ps["arch"], kind=TicketKind.story, work_type=WorkType.feature, title="S",
                            parent_id=epic.id)
    assert seat_card_env(q, "engineer") == {"EDP_CARD": "engineer-quick"}
    assert seat_card_env(q, "qa") == {}
    assert seat_card_env(s, "engineer") == {}
    assert seat_card_env(None, "engineer") == {}


def test_the_quick_card_exists_and_the_codex_seat_picks_it(tmp_path):
    from pathlib import Path
    from edp8.codex_seat.run import _card_name
    home = Path(__file__).resolve().parents[1]
    assert (home / ".claude" / "commands" / "engineer-quick.md").is_file()
    assert _card_name(home, "engineer-quick", "engineer") == "engineer-quick"
    assert _card_name(home, "no-such-card", "engineer") == "engineer"
    assert _card_name(home, None, "engineer") == "engineer"


def test_retire_roles_deletes_coordinator_consultant_and_owner_agent_rows_keeps_the_human_owner():
    """s-ccdafcb229 (owner ruling): the coordinator/consultant roles and the owner-role AGENT are retired;
    Store._retire_roles_locked deletes their participant rows at open and keeps the human owner."""
    import json

    store = Store(":memory:")
    rows = [
        {"id": "coordinator", "type": "agent", "role": "coordinator", "handle": "coordinator"},
        {"id": "consultant", "type": "agent", "role": "consultant", "handle": "consultant"},
        {"id": "owner-bot", "type": "agent", "role": "owner", "handle": "owner-bot"},
        {"id": "human-owner", "type": "human", "role": "owner", "handle": "human-owner"},
        {"id": "eng", "type": "agent", "role": "engineer", "handle": "eng"},
    ]
    with store._lock, store._conn:
        for r in rows:
            store._conn.execute("INSERT INTO participant(id, body, role, handle) VALUES (?,?,?,?)",
                                (r["id"], json.dumps(r), r["role"], r["handle"]))
        gone = store._retire_roles_locked()
    assert sorted(gone) == ["consultant", "coordinator", "owner-bot"]
    left = {r[0] for r in store._conn.execute("SELECT id FROM participant").fetchall()}
    assert left == {"human-owner", "eng"}
    assert store._retire_roles_locked() == []  # idempotent
    assert store.get("participant", "human-owner").role == Role.owner


# ------------------------------------------------------------------ p-788f3934 embedder re-arm

def test_a_low_ram_embedder_fallback_re_arms_once_ram_recovers(monkeypatch):
    from edp8 import search

    class Fake:
        name = "fake"

        def embed(self, texts, is_query=False):
            return [[1.0, 0.0] for _ in texts]

    made = iter([search.NullEmbedder(fallback_reason="low_ram: 0.91GB free < 1.5GB floor"), Fake()])
    monkeypatch.setattr(search, "make_embedder", lambda *a, **k: next(made))
    ram = {"gb": 0.9}
    monkeypatch.setattr(search, "_free_ram_gb", lambda: ram["gb"])
    idx = search.Index()
    st = idx.status()
    assert st["embedder"] == "none" and "re-checked" in st["reason"]  # still low: reason is current
    ram["gb"] = 4.0
    assert idx.status()["embedder"] == "none"  # throttled: no re-probe inside the interval
    monkeypatch.setattr(search, "REARM_INTERVAL_S", 0.0)
    idx._rearm_at = 0.0
    assert idx.status()["embedder"] == "fake"


def test_an_injected_or_forced_null_embedder_is_never_re_armed(monkeypatch):
    from edp8 import search
    monkeypatch.setattr(search, "_free_ram_gb", lambda: 64.0)
    idx = search.Index(embedder=search.NullEmbedder(fallback_reason="low_ram: x"))
    assert idx.status()["embedder"] == "none"


# ------------------------------------------------------------------ p-73d192bf prompt → board

def test_the_notify_hook_posts_a_blocked_question_for_a_seat_on_a_prompt(tmp_path):
    import http.server
    import json as _json
    import subprocess
    import sys
    import threading
    from pathlib import Path
    got: list[dict] = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            got.append({"path": self.path, "who": self.headers.get("X-Participant"),
                        "body": _json.loads(self.rfile.read(n))})
            self.send_response(200); self.end_headers(); self.wfile.write(b"{}")

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    hook = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "notify-user.py"
    env = {"SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""), "EDP_TOASTS": "0",
           "EDP_HANDLE": "engineer.s-abc", "EDP8_BOARD_URL": f"http://127.0.0.1:{srv.server_port}",
           "EDP_NOTIFY_STATE": str(tmp_path / "notify-state.json")}  # no rate-limit carry-over between runs
    for ntype in ("idle_prompt", "permission_prompt"):
        subprocess.run([sys.executable, str(hook)], input=_json.dumps(
            {"notification_type": ntype, "message": "Dangerous rm operation"}), text=True, env=env,
            timeout=20, cwd=tmp_path)
    srv.shutdown()
    assert len(got) == 1  # idle is the normal wait; only the prompt is a block
    b = got[0]
    assert b["path"] == "/v1/messages" and b["who"] == "engineer.s-abc"
    assert b["body"]["ticket_id"] == "s-abc" and b["body"]["to"] == "owner" and b["body"]["kind"] == "question"
    assert "[blocked]" in b["body"]["text"] and "Dangerous rm operation" in b["body"]["text"]


# ------------------------------------------------------------------ Astra adversarial findings (s-ccdafcb229)

def test_astra1_a_doc_owned_by_a_retired_role_still_loads():
    import json
    store = Store(":memory:")
    body = {"id": "note-old", "doc_type": "note", "title": "t", "body_md": "b", "version": 1,
            "owner_role": "coordinator", "scope": "global", "created_by": "coordinator"}
    with store._lock, store._conn:
        store._conn.execute("INSERT INTO doc(id, body, doc_type, scope, owner_role) VALUES (?,?,?,?,?)",
                            ("note-old", json.dumps(body), "note", "global", "coordinator"))
        store._conn.execute("INSERT INTO doc_versions(doc_id, version, body) VALUES (?,?,?)",
                            ("note-old", 1, json.dumps(body)))
        store._retire_roles_locked()
    d = store.get("doc", "note-old")
    assert d.owner_role == Role.architect
    raw = json.loads(store._conn.execute("SELECT body FROM doc_versions WHERE doc_id='note-old'").fetchone()[0])
    assert raw["owner_role"] == "architect" and raw["retired_owner_role"] == "coordinator"


def test_astra2_another_architect_cannot_walk_someone_elses_epic(b):
    from edp8.board import BoardError
    board, ps = b
    epic, story, c = _epic_with_evidenced_story(board, ps)
    board.ticket_update(ps["owner"], epic.id, assignee="arch")
    other = board.participant_create("agent", Role.architect, "arch2", id_="arch2")
    board.ticket_update(ps["eng"], story.id, status=TicketStatus.in_review)
    board.criterion_update(ps["qa"], c.id, verdict=Verdict.passed)
    (ec,) = board.criteria(epic.id)
    ec.verdict, ec.evidence_ref = Verdict.passed, "r"
    board.store.put("criterion", ec)
    with pytest.raises(BoardError, match="done is set"):
        board.ticket_update(other, epic.id, status=TicketStatus.done)
    board.ticket_update(ps["arch"], epic.id, status=TicketStatus.done)


def test_astra3_a_quick_task_cannot_start_through_blocked_nor_after_a_reopened_gate(b):
    from edp8.board import BoardError
    from edp8.schemas import Gate
    board, ps = b
    t = board.ticket_create(ps["owner"], kind=TicketKind.story, work_type=WorkType.feature, title="Q",
                            words="w", tags=["quick"], assignee="eng")
    board.ticket_update(ps["eng"], t.id, status=TicketStatus.blocked)
    with pytest.raises(BoardError, match="design sign-off"):
        board.ticket_update(ps["eng"], t.id, status=TicketStatus.in_progress)
    _sign_quick_design(board, ps, t)
    board.gate_open(t.id, Gate.design_signoff, by="eng", note="changed the design")
    with pytest.raises(BoardError, match="design sign-off"):
        board.ticket_update(ps["eng"], t.id, status=TicketStatus.in_progress)


def test_astra5_one_failed_post_commit_step_does_not_skip_the_quick_reopen(b, monkeypatch):
    from edp8 import views
    board, ps = b
    t, c = _quick_worked(board, ps)

    def boom(*a, **k):
        raise OSError("event insert failed")
    monkeypatch.setattr(board, "_criterion_event", boom)
    out = views.record_verdict(board, ps["owner"], criterion_id=c.id, verdict="fail", note="", ticket_id=t.id,
                               evidence_version=1)
    assert board.ticket(t.id).status == TicketStatus.in_progress  # the reopen still ran
    assert out["warnings"] and "event insert failed" in out["warnings"][0]


def test_astra6_design_signoff_answerable_after_the_board_carried_the_epic_to_in_review(b):
    from edp8.schemas import Gate
    board, ps = b
    epic, story = _designed_epic_with_story(board, ps)
    board.ticket_update(ps["arch"], story.id, status=TicketStatus.ready)
    board.ticket_update(ps["arch"], story.id, assignee="eng")
    board.ticket_update(ps["eng"], story.id, status=TicketStatus.in_progress)
    rep = board.doc_create(ps["eng"], doc_type=DocType.report, title="R", body_md="done", scope=story.id)
    (c,) = board.criteria(story.id)
    board.criterion_update(ps["eng"], c.id, evidence_ref=rep.id)
    board.ticket_update(ps["eng"], story.id, status=TicketStatus.in_review)
    assert board.ticket(epic.id).status == TicketStatus.in_review
    board.gate_answer(ps["owner"], epic.id, Gate.design_signoff, "signed off")
    assert not board.open_gates(epic.id, Gate.design_signoff)


def test_astra7_and_8_quick_design_feedback_reaches_the_engineer_and_the_gate_is_a_decision(b):
    from edp8 import design_review, views
    from edp8.schemas import Gate
    board, ps = b
    t = board.ticket_create(ps["owner"], kind=TicketKind.story, work_type=WorkType.feature, title="Q",
                            words="w", tags=["quick"], assignee="eng")
    d = board.doc_create(ps["eng"], doc_type=DocType.note, title="Design", body_md="plan", scope=t.id)
    board.ticket_update(ps["eng"], t.id, design_ref=d.id)
    board.gate_open(t.id, Gate.design_signoff, by="eng", note="review please")
    assert any(tid == t.id for tid, _ in views._owner_gates(board, ps["owner"]))

    class Body:
        ticket_id, design_ref, reviewed_version, artifacts = t.id, d.id, 1, []
    m = design_review._feedback(board, ps["owner"], Body(), "tighten the plan", __import__(
        "edp8.schemas", fromlist=["MessageKind"]).MessageKind.steer)
    assert m.to == "eng"


def test_astra9_the_service_index_is_board_picked_so_it_re_arms():
    import inspect
    from edp8 import service
    src = inspect.getsource(service)
    assert "Index(cache=cache)" in src and "Index(embedder=make_embedder()" not in src


def test_astra10_the_headless_pi_seat_honours_the_quick_card():
    from pathlib import Path
    from edp8.pi_seat.run import _card_name
    home = Path(__file__).resolve().parents[1]
    assert _card_name(home, "engineer-quick", "engineer") == "engineer-quick"
    assert _card_name(home, "../engineer-quick", "engineer") == "engineer"
    assert _card_name(home, None, "engineer") == "engineer"


def test_astra11_an_unblocked_epic_whose_stories_are_released_goes_to_in_review(b):
    board, ps = b
    epic, story, _ = _epic_with_evidenced_story(board, ps)
    board.ticket_update(ps["owner"], epic.id, assignee="arch")
    board.ticket_update(ps["arch"], epic.id, status=TicketStatus.blocked)
    board.ticket_update(ps["eng"], story.id, status=TicketStatus.in_review)
    assert board.ticket(epic.id).status == TicketStatus.blocked  # an explicit block wins while it lasts
    board.ticket_update(ps["arch"], epic.id, status=TicketStatus.in_progress)
    assert board.ticket(epic.id).status == TicketStatus.in_review
