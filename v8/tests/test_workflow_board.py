"""S13 (s-461403ebd1, design-e963c656f5 §4.14(b)): the board reads its rules from the epic's pinned workflow.

- c-e7cba464fc: a duplicated workflow with a changed cap and checker changes an epic pinned to it, and a
  Standard epic keeps today's behaviour; a newer version never moves a running epic;
- c-5c7afde0e8: a custom role and transition in a test workflow get auto-carry and refusal with no code
  change; the S16 guards are Standard's declared preconditions; an unanswerable gate is hidden;
- c-0e2611c3f2: a Lean epic (owner → engineer → qa) and a Solo epic (owner → engineer, owner checks) each
  walk to done.
Board + Store(':memory:') directly (a private board per test).
"""
from __future__ import annotations

import pytest

from edp8 import views
from edp8 import workflow as wf
from edp8.board import Board, BoardError
from edp8.schemas import Check, DocType, Gate, Role, TicketKind, TicketStatus, Verdict, WorkType
from edp8.store import Store


class _Pool:
    def __init__(self):
        self.spawned: list[tuple[str, str]] = []

    def spawn(self, role, pid, **_):
        self.spawned.append((role, pid))
        return {"ok": True}


@pytest.fixture
def board():
    return Board(Store(":memory:"), pool=_Pool(), free_mb=lambda: 10_000)


@pytest.fixture
def ps(board):
    return {
        "owner": board.participant_create("human", Role.owner, "owner", id_="owner"),
        "arch": board.participant_create("agent", Role.architect, "arch", id_="arch"),
        "eng": board.participant_create("agent", Role.engineer, "eng", id_="eng"),
        "qa": board.participant_create("agent", Role.qa, "qa", id_="qa"),
    }


def _publish(board, body: dict) -> str:
    board.workflows.save(body, by="owner")
    return board.workflows.publish(body["id"], body["version"], by="owner").ref


def _team_workflow(board, *, stories: int, story_checker: str) -> str:
    d = wf.dump(board.workflows.duplicate("standard@1", new_id="team", by="owner"))
    d["caps"]["stories_per_epic"] = stories
    d["checkers"] = [{"when": {"kinds": ["task"]}, "role": "engineer"}, {"role": story_checker}]
    return _publish(board, d)


def _story(board, ps, epic_id, title="S"):
    return board.ticket_create(ps["arch"], kind=TicketKind.story, work_type=WorkType.feature, title=title,
                               parent_id=epic_id)


# ---- c-e7cba464fc: data drives behaviour ------------------------------------------------------

def test_a_duplicated_workflow_changes_cap_and_checker_for_its_epic_only(board, ps):
    ref = _team_workflow(board, stories=1, story_checker="owner")
    team = board.ticket_create(ps["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="T",
                               workflow=ref)
    std = board.ticket_create(ps["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="S")
    assert board.workflows.pin_of(team.id) == "team@1" and board.workflows.pin_of(std.id) == "standard@1"
    # the cap: one open story on the team epic, eight on Standard
    s1 = _story(board, ps, team.id)
    with pytest.raises(BoardError, match="at most 1 open stories"):
        _story(board, ps, team.id, "second")
    _story(board, ps, std.id)
    _story(board, ps, std.id, "second")
    # the checker map: the team epic's story criteria are the owner's, Standard's are qa's
    c_team = board.criterion_create(ps["arch"], ticket_id=s1.id, text="x", check=Check.command)
    c_std = board.criterion_create(ps["arch"], ticket_id=_story(board, ps, std.id, "third").id, text="x",
                                   check=Check.command)
    assert (c_team.checked_by, c_std.checked_by) == ("owner", "qa")


def test_a_new_version_never_moves_a_running_epic(board, ps):
    ref1 = _team_workflow(board, stories=1, story_checker="qa")
    epic = board.ticket_create(ps["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="T",
                               workflow="team")
    v2 = wf.dump(board.workflows.duplicate(ref1, by="owner"))
    v2["caps"]["stories_per_epic"] = 5
    ref2 = _publish(board, v2)
    assert (ref1, ref2) == ("team@1", "team@2")
    assert board.workflow_of(epic).ref == "team@1" and board.workflow_of(epic).cap("stories_per_epic") == 1
    newer = board.ticket_create(ps["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="N",
                                workflow="team")
    assert board.workflow_of(newer).ref == "team@2"


def test_an_epic_cannot_pin_a_draft(board, ps):
    board.workflows.duplicate("standard@1", new_id="draft", by="owner")
    with pytest.raises(BoardError, match="draft"):
        board.ticket_create(ps["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="D",
                            workflow="draft@1")


def test_existing_epics_pin_standard_at_board_open(tmp_path):
    db = tmp_path / "b.db"
    b1 = Board(Store(db))
    owner = b1.participant_create("human", Role.owner, "owner", id_="owner")
    e = b1.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="old")
    b1.store._conn.execute("DELETE FROM workflow_pins")  # an epic from before S13
    b1.store._conn.commit()
    b2 = Board(Store(db))
    assert b2.workflows.pin_of(e.id) == "standard@1"


# ---- c-5c7afde0e8: guards as data -------------------------------------------------------------

def _custom_workflow(board) -> str:
    """A custom `designer` role marks stories designed (not the architect), and a story with its design_ref
    and a criterion is carried to designed by the board (a custom auto edge) — no board code knows either."""
    d = wf.dump(board.workflows.duplicate("standard@1", new_id="custom", by="owner"))
    d["roles"].append({"id": "designer", "card_md": "# designer\nYou design stories.", "spawnable": True,
                       "capacity_class": "planner", "criterion_author": True, "doc_types": ["design", "note"],
                       "bundle": ["whoami", "context", "criterion_create", "ticket_update"]})
    for r in d["roles"]:
        if r["id"] == "owner":
            r["may_spawn"].append("designer")
    d["permissions"]["set_design_ref"].append("designer")
    for tr in d["transitions"]:
        if tr["to"] == "designed":
            tr["requires"][0] = {"check": "role_in", "params": {"roles": ["designer"]}, "code": "scope",
                                 "message": "only the designer marks a {kind} designed"}
            if tr["from"] == "drafted":
                tr["auto"], tr["auto_when"] = True, {"kinds": ["epic", "story"]}
    return _publish(board, d)


def test_a_custom_role_and_transition_get_refusal_and_auto_carry(board, ps):
    ref = _custom_workflow(board)
    epic = board.ticket_create(ps["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="C",
                               workflow=ref)
    designer = board.participant_create("agent", "designer", "designer", id_="designer")
    assert designer.role == "designer" and designer.role.value == "designer"
    s = _story(board, ps, epic.id)
    # refusal names the role, then the missing piece
    with pytest.raises(BoardError, match="only the designer marks a story designed"):
        board.ticket_update(ps["arch"], s.id, status=TicketStatus.designed)
    with pytest.raises(BoardError, match="designed needs a design_ref doc"):
        board.ticket_update(designer, s.id, status=TicketStatus.designed)
    # auto-carry: design_ref then a criterion, and the board moves the story itself
    d = board.doc_create(designer, doc_type=DocType.design, title="d", body_md="# d", scope=s.id)
    board.ticket_update(designer, s.id, design_ref=d.id)
    assert board.ticket(s.id).status == TicketStatus.drafted
    board.criterion_create(designer, ticket_id=s.id, text="x", check=Check.command)
    assert board.ticket(s.id).status == TicketStatus.designed
    # the same edge on a Standard epic stays the architect's, with no auto-carry for a story
    std = board.ticket_create(ps["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="S")
    s2 = _story(board, ps, std.id)
    with pytest.raises(BoardError, match="only the architect marks a ticket designed"):
        board.ticket_update(designer, s2.id, status=TicketStatus.designed)


def test_an_unknown_custom_role_is_refused():
    b = Board(Store(":memory:"))
    with pytest.raises(BoardError, match="not a built-in role nor a role of any pinned workflow"):
        b.participant_create("agent", "designer", "designer", id_="designer")


def test_s16_guards_are_standards_declared_preconditions():
    std = wf.build_standard()
    carry = next(t for t in std.transitions if (t.from_, t.to) == ("drafted", "designed"))
    assert carry.auto and carry.auto_when.kinds == ["epic"]
    assert [p.check for p in carry.requires] == ["role_in", "design_ref", "criteria_min"]
    signoff = next(g for g in std.gates if g.id == "design_signoff")
    assert [p.check for p in signoff.requires] == ["story_cap", "design_ref", "kind_in", "design_ready",
                                                    "signoff_lint"]
    assert [p.check for p in signoff.answer_requires] == ["human_epic_owner"]
    assert all(g.requires for g in std.gates)  # the lint's gate_without_precondition holds for Standard


def test_a_gate_the_owner_cannot_answer_is_hidden_from_needs_you(board, ps):
    d = wf.dump(board.workflows.duplicate("standard@1", new_id="nogate", by="owner"))
    for g in d["gates"]:
        if g["id"] == "scope":
            g["answerers"] = ["architect"]
    # publish refuses it now (gate_unanswerable, c-328185ac06); a version stored before that invariant
    # (written straight to the table here) must still never reach Needs you
    with pytest.raises(wf.WorkflowError, match="gate_unanswerable"):
        board.workflows.save(d, by="owner") and board.workflows.publish("nogate", 1, by="owner")
    board.workflows._put(wf.WorkflowDef.model_validate({**d, "published": True}), "test")
    ref = "nogate@1"
    epic = board.ticket_create(ps["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="G",
                               workflow=ref)
    std = board.ticket_create(ps["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="S")
    board.gate_open(epic.id, Gate.scope, by="arch")
    board.gate_open(std.id, Gate.scope, by="arch")
    listed = [(g["ticket_id"], g["gate"]) for g in views.decisions_for(board, ps["owner"])["gates"]]
    assert listed == [(std.id, "scope")]
    assert "answered by" in board.gate_answer_refusal(ps["owner"], epic.id, Gate.scope).message


# ---- c-0e2611c3f2: Lean and Solo walk to done -------------------------------------------------

def _walk(board, ps, preset: str, *, checker, at_acceptance=lambda b, epic: None):
    """owner creates and designs the epic, signs it off, writes a story, the engineer builds it, and the
    checker (qa in Lean, the owner in Solo) passes the story and the epic."""
    owner, eng = ps["owner"], ps["eng"]
    epic = board.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title=preset,
                               workflow=preset)
    assert board.workflow_of(epic).ref == f"{preset}@1"
    design = board.doc_create(owner, doc_type=DocType.design, title="d", body_md="# d", scope=epic.id)
    board.ticket_update(owner, epic.id, design_ref=design.id)
    ec = board.criterion_create(owner, ticket_id=epic.id, text="epic ships", check=Check.verdict)
    assert board.ticket(epic.id).status == TicketStatus.designed  # auto-carry
    board.gate_open(epic.id, Gate.design_signoff, by="owner")
    board.gate_answer(owner, epic.id, Gate.design_signoff, "go")
    assert board.ticket(epic.id).status == TicketStatus.signed_off
    s = board.ticket_create(owner, kind=TicketKind.story, work_type=WorkType.feature, title="build",
                            parent_id=epic.id, assignee=eng.id)
    sc = board.criterion_create(owner, ticket_id=s.id, text="works", check=Check.command)
    board.ticket_update(owner, s.id, design_ref=design.id)
    board.ticket_update(owner, s.id, status=TicketStatus.designed)
    board.ticket_update(owner, s.id, status=TicketStatus.signed_off)
    assert board.ticket(s.id).status == TicketStatus.ready  # the release cascade
    board.ticket_update(eng, s.id, status=TicketStatus.in_progress)
    rep = board.doc_create(eng, doc_type=DocType.report, title="r", body_md="evidence", scope=s.id)
    board.criterion_update(eng, sc.id, evidence_ref=rep.id)
    board.ticket_update(eng, s.id, status=TicketStatus.in_review)
    assert board.ticket(epic.id).status == TicketStatus.in_review  # every story released
    at_acceptance(board, epic)
    who = checker(board)
    for c in (sc,):
        board.criterion_update(who, c.id, verdict=Verdict.passed)
    assert board.ticket(s.id).status == TicketStatus.done
    board.criterion_update(who, ec.id, evidence_ref=rep.id)
    board.criterion_update(who, ec.id, verdict=Verdict.passed)
    assert board.ticket(epic.id).status == TicketStatus.done
    return epic, sc, ec


def test_lean_epic_walks_owner_engineer_qa_to_done(board, ps):
    paired: list[str] = []
    epic, sc, ec = _walk(board, ps, "lean", checker=lambda b: b.participant("qa"),
                         at_acceptance=lambda b, e: paired.extend(b.run_pending_pairings()["spawned"]))
    assert (sc.checked_by, ec.checked_by) == ("qa", "qa")
    assert paired == [f"qa.{epic.id}"]  # the acceptance gate paired the qa seat


def test_solo_epic_walks_owner_engineer_owner_checks_to_done(board, ps):
    paired: list[str] = []
    epic, sc, ec = _walk(board, ps, "solo", checker=lambda b: b.participant("owner"),
                         at_acceptance=lambda b, e: paired.extend(b.run_pending_pairings()["spawned"]))
    assert (sc.checked_by, ec.checked_by) == ("owner", "owner")
    assert paired == [] and board._pool.spawned == []  # no checker seat is paired in Solo


def test_lean_has_no_architect(board, ps):
    epic = board.ticket_create(ps["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="L",
                               workflow="lean")
    with pytest.raises(BoardError, match="may not create a story"):
        _story(board, ps, epic.id)
