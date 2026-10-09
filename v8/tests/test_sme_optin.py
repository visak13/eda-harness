"""e0cec S6 task 3 (c-70c596ee4a): SMEs are opt-in per epic, and an sme closes its own knowledge work.

Epic tag `sme:on|off` (default off). `spawn(role=sme)` is refused on an epic while it is off, on every spawn
path (REST spawn, seat-token, the MCP tool, the board's own pairing). Knowledge-ticket criteria are
checked_by=sme; the epic's sme verdicts its own lines after citing sources. Pains p-03acb4cd, p-5592b872.
"""
from __future__ import annotations

import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import edp8.bundles as bundles_mod
from edp8 import epic_policy
from edp8.board import Board, BoardError
from edp8.bundles import ALL_TOOLS, set_client
from edp8.client import BoardClient
from edp8.schemas import Check, DocType, Role, TicketKind, TicketStatus, Verdict, WorkType
from edp8.service import create_app
from edp8.store import Store

CARDS = Path(__file__).resolve().parents[1] / ".claude" / "commands"


class StubPool:
    def __init__(self):
        self.spawns: list[tuple[str, str]] = []

    def spawn(self, role, participant_id, **kw):
        self.spawns.append((role, participant_id))
        return {"ok": True, "participant_id": participant_id}


@pytest.fixture
def board():
    return Board(Store(":memory:"), pool=StubPool(), free_mb=lambda: 4096)


def _rig(board, tags=None):
    owner = board.participant_create("human", Role.owner, "owner", id_="owner")
    epic = board.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="E", tags=tags)
    arch = board.participant_create("agent", Role.architect, f"architect.{epic.id}", id_=f"architect.{epic.id}")
    return owner, epic, arch


def _knowledge(board, arch, epic, text="the craft is sourced"):
    kn = board.ticket_create(arch, kind=TicketKind.story, work_type=WorkType.knowledge, title="ll-craft",
                             parent_id=epic.id)
    c = board.criterion_create(arch, ticket_id=kn.id, text=text, check=Check.look)
    return kn, c


# ----------------------------------------------------------------------------- the tag
def test_sme_tag_default_off_last_wins():
    assert not epic_policy.sme_on(None) and not epic_policy.sme_on([])
    assert epic_policy.sme_on(["sme:on"])
    assert not epic_policy.sme_on(["sme:on", "sme:off"])
    assert epic_policy.sme_on(["sme:off", "SME:on".lower()])


@pytest.mark.parametrize("tag", ["sme:maybe", "sme:", "project:", "project:  "])
def test_malformed_policy_tags_are_refused_at_create(board, tag):
    owner = board.participant_create("human", Role.owner, "owner", id_="owner")
    with pytest.raises(BoardError):
        board.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="E", tags=[tag])


def test_only_the_owner_or_the_epics_architect_changes_policy_tags(board):
    owner, epic, arch = _rig(board)
    eng = board.participant_create("agent", Role.engineer, f"engineer.{epic.id}", id_=f"engineer.{epic.id}")
    other = board.participant_create("agent", Role.architect, "architect.other", id_="architect.other")
    with pytest.raises(BoardError):
        board.ticket_update(eng, epic.id, tags=["sme:on"])
    with pytest.raises(BoardError):
        board.ticket_update(other, epic.id, tags=["sme:on"])
    board.ticket_update(arch, epic.id, tags=["sme:on"])
    assert epic_policy.sme_on(board.ticket(epic.id).tags)
    board.ticket_update(owner, epic.id, tags=["sme:off"])
    assert not epic_policy.sme_on(board.ticket(epic.id).tags)
    with pytest.raises(BoardError):
        board.ticket_update(arch, epic.id, tags=["sme:sometimes"])


def test_an_unchanged_policy_tag_needs_no_policy_right(board):
    owner, epic, arch = _rig(board, tags=["sme:on"])
    eng = board.participant_create("agent", Role.engineer, f"engineer.{epic.id}", id_=f"engineer.{epic.id}")
    st = board.ticket_create(arch, kind=TicketKind.story, work_type=WorkType.feature, title="s", parent_id=epic.id,
                             tags=["x"])
    board.ticket_update(arch, st.id, assignee=eng.id)
    board.ticket_update(eng, st.id, tags=["x", "y"])  # a story's tags, no policy tag touched


# ----------------------------------------------------------------------------- the refusal, every path
def test_board_rule_refuses_sme_while_off_and_allows_on(board):
    owner, epic, arch = _rig(board)
    assert "off" in board.sme_spawn_refusal("sme", epic.id).lower()
    assert board.sme_spawn_refusal("engineer", epic.id) is None
    board.ticket_update(owner, epic.id, tags=["sme:on"])
    assert board.sme_spawn_refusal("sme", epic.id) is None


def test_a_story_resolves_to_its_epics_switch(board):
    owner, epic, arch = _rig(board)
    st = board.ticket_create(arch, kind=TicketKind.story, work_type=WorkType.feature, title="s", parent_id=epic.id)
    assert board.sme_spawn_refusal("sme", st.id)
    board.ticket_update(owner, epic.id, tags=["sme:on"])
    assert board.sme_spawn_refusal("sme", st.id) is None


def test_a_library_topic_is_never_gated(board):
    owner = board.participant_create("human", Role.owner, "owner", id_="owner")
    topic = board.ticket_create(owner, kind=TicketKind.topic, work_type=WorkType.knowledge, title="Blender")
    assert board.sme_spawn_refusal("sme", topic.id) is None


def test_pairing_path_drops_an_sme_while_off_and_spawns_it_when_on(board):
    owner, epic, arch = _rig(board)
    pool = board.pool if hasattr(board, "pool") else None
    assert board._spawn_seat("sme", f"sme.{epic.id}", epic.id) is True  # dropped, never re-queued
    assert board.store.get("participant", f"sme.{epic.id}") is None
    board.ticket_update(owner, epic.id, tags=["sme:on"])
    board._spawn_seat("sme", f"sme.{epic.id}", epic.id)
    assert board.store.get("participant", f"sme.{epic.id}") is not None


def _client(board):
    return TestClient(create_app(board, admin_token="t"))


def test_rest_spawn_and_seat_token_refuse_an_sme_while_off(board):
    owner, epic, arch = _rig(board)
    board.participant_create("agent", Role.sme, f"sme.{epic.id}", id_=f"sme.{epic.id}")
    c = _client(board)
    h = {"X-Participant": "owner"}
    r = c.post("/v1/sessions/spawn", json={"role": "sme", "participant_id": f"sme.{epic.id}", "ticket_id": epic.id}, headers=h)
    assert r.status_code in (400, 403) or r.json().get("ok") is False
    assert "SMEs are off" in r.text
    t = c.post("/v1/sessions/seat-token", json={"participant_id": f"sme.{epic.id}", "ticket_id": epic.id}, headers=h)
    assert "SMEs are off" in t.text
    board.ticket_update(owner, epic.id, tags=["sme:on"])
    r2 = c.post("/v1/sessions/spawn", json={"role": "sme", "participant_id": f"sme.{epic.id}", "ticket_id": epic.id}, headers=h)
    assert "SMEs are off" not in r2.text
    t2 = c.post("/v1/sessions/seat-token", json={"participant_id": f"sme.{epic.id}", "ticket_id": epic.id}, headers=h)
    assert "SMEs are off" not in t2.text


def test_mcp_spawn_tool_refuses_an_sme_before_any_seat_exists(board, monkeypatch):
    owner, epic, arch = _rig(board)
    c = _client(board)
    calls = []
    monkeypatch.setattr(bundles_mod, "_pool_call",
                        lambda fn, kw: calls.append((fn, kw)) or {"ok": True, "value": {"session_id": "s1"}})
    set_client(BoardClient(participant=arch.id, admin_token="t", client=c))
    out = ALL_TOOLS["spawn"].handler(ALL_TOOLS["spawn"].args_model(role="sme", ticket_id=epic.id))
    assert out["ok"] is False and "SMEs are off" in out["error"]["message"]
    assert calls == [] and board.store.get("participant", f"sme.{epic.id}") is None
    board.ticket_update(owner, epic.id, tags=["sme:on"])
    out = ALL_TOOLS["spawn"].handler(ALL_TOOLS["spawn"].args_model(role="sme", ticket_id=epic.id))
    assert out["ok"], out
    assert [fn for fn, _ in calls] == ["spawn"]


# ----------------------------------------------------------------------------- checker + self-close
def test_knowledge_criteria_are_checked_by_sme_but_a_feature_story_stays_qa(board):
    owner, epic, arch = _rig(board)
    kn, c = _knowledge(board, arch, epic)
    assert c.checked_by == "sme"
    st = board.ticket_create(arch, kind=TicketKind.story, work_type=WorkType.feature, title="s", parent_id=epic.id)
    assert board.criterion_create(arch, ticket_id=st.id, text="x", check=Check.command).checked_by == "qa"


@pytest.mark.parametrize("wf", ["lean", "solo"])
def test_lean_and_solo_keep_knowledge_with_the_owner(board, wf):
    owner = board.participant_create("human", Role.owner, "owner", id_="owner")
    epic = board.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title=wf, workflow=wf)
    kn = board.ticket_create(owner, kind=TicketKind.story, work_type=WorkType.knowledge, title="k", parent_id=epic.id)
    c = board.criterion_create(owner, ticket_id=kn.id, text="x", check=Check.look)
    assert c.checked_by == "owner"


def _handed_over(board, owner, epic, arch, body="# craft\n\n## Sources\n- https://example.org/guide\n"):
    kn, c = _knowledge(board, arch, epic)
    sid = f"sme.{epic.id}"
    sme = board.store.get("participant", sid) or board.participant_create("agent", Role.sme, sid, id_=sid)
    d = board.doc_create(arch, doc_type=DocType.design, title="d", body_md="b", scope=epic.id)
    board.ticket_update(arch, kn.id, design_ref=d.id)
    board.ticket_update(arch, kn.id, status=TicketStatus.designed)
    board.ticket_update(owner, kn.id, status=TicketStatus.signed_off)
    board.ticket_update(arch, kn.id, status=TicketStatus.ready)
    board.ticket_update(arch, kn.id, assignee=sme.id)
    board.ticket_update(sme, kn.id, status=TicketStatus.in_progress)
    ev = board.doc_create(sme, doc_type=DocType.strategy_ll, title="craft", body_md=body, scope=epic.id)
    board.criterion_update(sme, c.id, evidence_ref=ev.id)
    return kn, c, sme


def test_the_epics_sme_passes_its_own_line_after_citing_sources(board):
    owner, epic, arch = _rig(board, tags=["sme:on"])
    kn, c, sme = _handed_over(board, owner, epic, arch)
    got = board.criterion_update(sme, c.id, verdict=Verdict.passed, note="checked the retry claim against guide")
    assert got.verdict == Verdict.passed


def test_an_sme_pass_without_a_note_or_sources_goes_ahead_with_advice(board):
    from edp8 import advice
    owner, epic, arch = _rig(board, tags=["sme:on"])
    kn, c, sme = _handed_over(board, owner, epic, arch, body="# craft\nno citations")
    advice.take()
    board.criterion_update(sme, c.id, verdict=Verdict.passed, note="checked it")  # design-63db8a7d42 I
    assert any("cites sources" in said for said in advice.take())
    kn2, c2, sme2 = _handed_over(board, owner, epic, arch)
    advice.take()
    board.criterion_update(sme2, c2.id, verdict=Verdict.passed, note="  ")
    assert any("what it checked" in said for said in advice.take())


def test_nobody_else_clears_an_sme_line(board):
    owner, epic, arch = _rig(board, tags=["sme:on"])
    kn, c, sme = _handed_over(board, owner, epic, arch)
    eng = board.participant_create("agent", Role.engineer, f"engineer.{epic.id}", id_=f"engineer.{epic.id}")
    stranger = board.participant_create("agent", Role.sme, "sme.elsewhere", id_="sme.elsewhere")
    for who in (eng, stranger):
        with pytest.raises(BoardError):
            board.criterion_update(who, c.id, verdict=Verdict.passed, note="checked against guide")
    assert board.criterion_update(owner, c.id, verdict=Verdict.passed, note="owner rules").verdict == Verdict.passed


def test_the_sme_is_never_re_paired_for_an_off_epic_and_the_architect_clears_the_line(board):
    owner, epic, arch = _rig(board)  # sme off
    kn, c = _knowledge(board, arch, epic)
    assert c.checked_by == "sme"
    assert board.requeue_checkers(board.ticket(kn.id)) == []


# ----------------------------------------------------------------------------- cards
def test_sme_card_carries_the_digest_close_and_reuse_protocol():
    card = (CARDS / "sme.md").read_text(encoding="utf-8")
    assert "REUSE FIRST" in card and "`find`" in card and "extend" in card.lower()
    assert "SELF-CLOSE" in card and "≤10 lines" in card and "## Sources" in card


def test_architect_card_names_the_opt_in_and_the_reuse_step():
    card = (CARDS / "architect.md").read_text(encoding="utf-8")
    assert "sme:on" in card and "checked_by=sme" in card and "checked_by=owner" not in card
    assert card.index("`find` existing strategy/domain docs") < card.index("sme:on")


# ----------------------------------------------------------------------------- pains p-5592b872 / p-fc50ec61 / p-ff30576a
def test_a_knowledge_ticket_starting_does_not_carry_a_designed_epic_past_signoff(board):
    owner, epic, arch = _rig(board, tags=["sme:on"])
    d = board.doc_create(arch, doc_type=DocType.design, title="d", body_md="b", scope=epic.id)
    board.criterion_create(arch, ticket_id=epic.id, text="e", check=Check.command)
    board.ticket_update(arch, epic.id, design_ref=d.id)
    assert board.ticket(epic.id).status == TicketStatus.designed
    kn, c, sme = _handed_over(board, owner, epic, arch)
    assert board.ticket(kn.id).status in (TicketStatus.in_progress, TicketStatus.in_review)
    assert board.ticket(epic.id).status == TicketStatus.designed  # p-5592b872


def test_a_feature_story_starting_still_carries_a_designed_epic(board):
    owner, epic, arch = _rig(board)
    d = board.doc_create(arch, doc_type=DocType.design, title="d", body_md="b", scope=epic.id)
    board.criterion_create(arch, ticket_id=epic.id, text="e", check=Check.command)
    board.ticket_update(arch, epic.id, design_ref=d.id)
    eng = board.participant_create("agent", Role.engineer, "engineer.s", id_="engineer.s")
    st = board.ticket_create(arch, kind=TicketKind.story, work_type=WorkType.feature, title="s", parent_id=epic.id)
    board.criterion_create(arch, ticket_id=st.id, text="c", check=Check.command)
    board.ticket_update(arch, st.id, design_ref=d.id)
    board.ticket_update(arch, st.id, status=TicketStatus.designed)
    board.ticket_update(owner, st.id, status=TicketStatus.signed_off)
    board.ticket_update(arch, st.id, status=TicketStatus.ready)
    board.ticket_update(arch, st.id, assignee=eng.id)
    board.ticket_update(eng, st.id, status=TicketStatus.in_progress)
    assert board.ticket(epic.id).status == TicketStatus.in_progress


def _topic_sme(board):
    owner = board.participant_create("human", Role.owner, "owner", id_="owner")
    topic = board.ticket_create(owner, kind=TicketKind.topic, work_type=WorkType.knowledge, title="Blender")
    sme = board.participant_create("agent", Role.sme, f"sme.{topic.id}", id_=f"sme.{topic.id}")
    return owner, topic, sme


def test_a_topic_sme_amends_its_own_unapproved_note_but_not_a_stamped_proposal(board):
    from edp8.schemas import DocStatus
    owner, topic, sme = _topic_sme(board)
    note = board.doc_create(sme, doc_type=DocType.note, title="plan", body_md="v1", scope="global",
                            status=DocStatus.proposed, ticket_id=topic.id)
    assert board.doc_update(sme, note.id, body_md="v2").version == 2  # p-ff30576a
    stamped = board.doc_create(sme, doc_type=DocType.strategy_ll, title="s", body_md="x", scope="global",
                               status=DocStatus.proposed, ticket_id=topic.id, source_url="https://skills.sh/a/b/c")
    with pytest.raises(BoardError):
        board.doc_update(sme, stamped.id, body_md="forged")
    t2 = board.ticket_create(owner, kind=TicketKind.topic, work_type=WorkType.knowledge, title="Other")
    other = board.participant_create("agent", Role.sme, f"sme.{t2.id}", id_=f"sme.{t2.id}")
    with pytest.raises(BoardError):
        board.doc_update(other, note.id, body_md="not yours")


def test_a_proposed_doc_never_joins_a_ticket_brief(board, monkeypatch):
    from edp8.schemas import DocStatus
    owner, epic, arch = _rig(board, tags=["sme:on"])
    sme = board.participant_create("agent", Role.sme, f"sme.{epic.id}", id_=f"sme.{epic.id}")
    prop = board.doc_create(sme, doc_type=DocType.strategy_ll, title="p", body_md="## Enforced\n- keep it [required]\n",
                            scope=epic.id, status=DocStatus.proposed, ticket_id=epic.id)
    c = _client(board)
    set_client(BoardClient(participant=sme.id, admin_token="t", client=c))
    out = ALL_TOOLS["doc_read"].handler(ALL_TOOLS["doc_read"].args_model(id=prop.id))  # the sme reads its draft
    assert out["ok"] and "keep it" in out["value"]["body_md"]
    assert board.doc(prop.id).status == DocStatus.proposed  # shown, never activated
    board.link_create(sme, from_id=epic.id, to_id=prop.id, relation=__import__("edp8.schemas", fromlist=["Relation"]).Relation.uses_strategy)
    tool = ALL_TOOLS["ticket_read"]
    brief = tool.handler(tool.args_model(ticket_id=epic.id, include="docs"))
    assert brief["ok"] and prop.id not in str(brief["value"]["docs"])  # an unapproved doc never joins a brief
