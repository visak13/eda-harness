"""t-cfd8462f9d (owner m-fcb4463e1e: "who raised a decision on the epic without any text?"): no gate opens without
text. The board's auto-opened acceptance gate carries a plain-words question naming the epic's title; MCP gate_open
and REST refuse an empty or whitespace note unless the workflow gate declares a default question; a legacy gate
stored blank renders the generated question in every GateRow. Board + Store(':memory:') and a TestClient.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from edp8 import broker_adapter, views
from edp8 import workflow as wflow
from edp8.board import Board, BoardError
from edp8.schemas import Check, DocType, EventKind, Gate, Role, TicketKind, TicketStatus, WorkType
from edp8.service import create_app
from edp8.store import Store


class _Pool:
    def spawn(self, role, participant_id, **kw):
        return {"ok": True, "participant_id": participant_id}


@pytest.fixture
def board():
    return Board(Store(":memory:"), pool=_Pool(), free_mb=lambda: 4096)


@pytest.fixture
def r(board):
    roles = {"owner": Role.owner, "architect": Role.architect, "engineer": Role.engineer, "qa": Role.qa}
    return {h: board.participant_create("human" if h == "owner" else "agent", role, h, id_=h)
            for h, role in roles.items()}


def _story(board, r, epic, title):
    return board.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature,
                               title=title, parent_id=epic.id)


def _story_to_review(board, r, epic, story):
    d = board.doc_create(r["architect"], doc_type=DocType.design, title="d", body_md="b", scope=epic.id)
    board.ticket_update(r["architect"], story.id, design_ref=d.id)
    crit = board.criterion_create(r["architect"], ticket_id=story.id, text="c", check=Check.command)
    board.ticket_update(r["architect"], story.id, status=TicketStatus.designed)
    board.ticket_update(r["owner"], story.id, status=TicketStatus.signed_off)
    board.ticket_update(r["architect"], story.id, status=TicketStatus.ready)
    board.ticket_update(r["architect"], story.id, assignee=r["engineer"].id)
    board.ticket_update(r["engineer"], story.id, status=TicketStatus.in_progress)
    ev = board.doc_create(r["engineer"], doc_type=DocType.report, title="e", body_md="ok", scope=epic.id)
    board.criterion_update(r["engineer"], crit.id, evidence_ref=ev.id)
    board.ticket_update(r["engineer"], story.id, status=TicketStatus.in_review)
    return story


def _opened(board, tid, gate):
    return [e for e in board.store.query("event", {"subject_id": tid, "kind": EventKind.gate_opened})
            if e.data.get("gate") == gate]


# ---- (1) the board's own opens say what they ask -------------------------------------------------

def test_auto_opened_acceptance_gate_names_the_epic_and_the_ask(board, r):
    """The live bug (ev-28a4d0cb87): every story released → the board opened `acceptance` with no note."""
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature,
                               title="Productize the app")
    s1, s2 = _story(board, r, epic, "S1"), _story(board, r, epic, "S2")
    _story_to_review(board, r, epic, s1)
    assert not _opened(board, epic.id, Gate.acceptance)  # S2 still holds the epic
    _story_to_review(board, r, epic, s2)
    [ev] = _opened(board, epic.id, Gate.acceptance)
    assert ev.data["by"] == "board"
    note = ev.data["note"]
    assert note == ("Every story on “Productize the app” is in review (2 stories). qa is giving its verdicts; "
                    "once qa's report passes, accept the epic here: done, partial, or send back.")


@pytest.mark.parametrize("gate", list(Gate))
def test_every_gate_kind_has_a_plain_question_with_the_title(board, r, gate):
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="Ship it")
    story = board.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature,
                                title="The story", parent_id=epic.id)
    for t in (epic, story):
        q = board.gate_question(t, gate)
        assert q.strip() and t.title in q and "{" not in q


def test_any_path_that_skips_the_edge_still_stores_a_question(board, r):
    """Defence in depth: Board.gate_open itself never stores a blank note (dry-run walk, scripts, old callers)."""
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E1")
    ev = board.gate_open(epic.id, Gate.demo, by="arch", note="   ")
    assert ev.data["note"] == "Look at the demo of “E1”: approve it, or say what to change."


# ---- (2) seats and humans are refused a blank note ------------------------------------------------

@pytest.mark.parametrize("note", ["", "   ", "\n\t"])
def test_require_gate_note_refuses_blank(board, r, note):
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E1")
    with pytest.raises(BoardError) as ei:
        board.require_gate_note(epic.id, Gate.demo, note)
    assert ei.value.code == "validation"
    assert "needs a note" in ei.value.message and "“E1”" in ei.value.hint
    assert board.require_gate_note(epic.id, Gate.demo, "  is the demo good?  ") == "is the demo good?"


def test_a_workflow_gate_question_is_the_default_note(board, r):
    """S13 data: a gate definition may carry a `question` template; then a blank note takes it, never blank."""
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E1")
    wf = board.workflow_of(epic)
    wf.gates["demo"] = wf.gates["demo"].model_copy(update={"question": "Demo of {title} ({id}): ship it?"})
    assert board.require_gate_note(epic.id, Gate.demo, "") == f"Demo of E1 ({epic.id}): ship it?"
    # the standard workflow declares none, so a seat must always write its question
    std = wflow.build_standard()
    assert all(not g.question for g in std.gates)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP8_TOKENS", str(tmp_path / "tokens.json"))
    monkeypatch.setattr(broker_adapter, "publish", lambda *a, **k: True)
    c = TestClient(create_app(Board(Store(":memory:")), admin_token="t"))
    for pid, role, typ in [("sam", "owner", "human"), ("arch", "architect", "agent")]:
        assert c.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                      headers={"X-Admin": "t"}).json()["ok"]
    return c


def _rest_epic(client):
    r = client.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "Rest epic"},
                    headers={"X-Participant": "sam"}).json()
    assert r["ok"], r
    return r["value"]["id"]


@pytest.mark.parametrize("body", [{}, {"note": ""}, {"note": "   "}])
def test_rest_refuses_a_blank_note(client, body):
    epic = _rest_epic(client)
    resp = client.post(f"/v1/gates/{epic}/demo/open", json=body, headers={"X-Participant": "arch"})
    j = resp.json()
    assert not j["ok"] and j["error"]["code"] == "validation", j
    assert "needs a note" in j["error"]["message"]
    gates = client.get(f"/v1/gates/{epic}", headers={"X-Participant": "sam"}).json()["value"]
    assert gates == [] or all(g.get("gate") != "demo" for g in gates)


def test_rest_opens_with_a_note_and_stores_it(client):
    epic = _rest_epic(client)
    j = client.post(f"/v1/gates/{epic}/demo/open", json={"note": "  is the demo good?  "},
                    headers={"X-Participant": "arch"}).json()
    assert j["ok"], j
    assert j["value"]["data"]["note"] == "is the demo good?"


def test_mcp_gate_open_refuses_a_blank_note(client, monkeypatch):
    """MCP gate_open rides the REST route through the client, so it gets the same refusal."""
    from edp8 import bundles

    class _C:
        def gate_open(self, ticket_id, gate, note=""):
            return client.post(f"/v1/gates/{ticket_id}/{gate}/open", json={"note": note},
                               headers={"X-Participant": "arch"}).json()

    monkeypatch.setattr(bundles, "get_client", lambda: _C())
    epic = _rest_epic(client)
    out = bundles._gate_open(bundles.GateOpenArgs(ticket_id=epic, gate="demo"))
    assert not out["ok"] and out["error"]["code"] == "validation"
    assert "note" in bundles.GateOpenArgs.model_fields["note"].description


# ---- (3) a legacy blank gate never renders blank --------------------------------------------------

def test_legacy_blank_gate_rows_render_the_generated_question(board, r):
    """A gate stored blank before the fix (epic-7f3d64e6de's) reads its generated question everywhere a GateRow
    is built, without rewriting history."""
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="Old epic")
    ev = board._emit(epic.id, EventKind.gate_opened, {"gate": Gate.acceptance, "by": "board", "note": ""})
    assert ev.data["note"] == ""  # the stored record stays as it was
    page = views.epic_page(board, epic.id) if hasattr(views, "epic_page") else None
    rows = page["answerable_gates"] if page else []
    rows += views.ticket_page(board, epic.id)["open_gates"] if hasattr(views, "ticket_page") else []
    assert rows, "no GateRow builder found"
    for row in rows:
        assert row["note"].startswith("Every story on “Old epic” is in review (0 stories).")
