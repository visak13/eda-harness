"""e0cec S9 (s-8ca20e8543) task 5: the code guards that replace memory-only rules.

G4  spawn onto a parked seat says resume it, or reap then spawn with a steer (memory parked-dead-seat-reap-then-spawn)
G5  a refused criterion_create names the next move (memory qa-cannot-criterion-create)
G6  spawn(steer=) is posted before launch, so the seat's first context() carries it (memory steer-lands-after-boot-context)
"""
from __future__ import annotations

import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

import edp8.bundles as bundles_mod
from edp8.board import Board, BoardError
from edp8.bundles import ALL_TOOLS, set_client
from edp8.client import BoardClient
from edp8.schemas import Check, Role, TicketKind, WorkType
from edp8.service import create_app
from edp8.store import Store


class StubPool:
    def spawn(self, role, participant_id, **kw):
        return {"ok": True, "participant_id": participant_id}


@pytest.fixture
def board():
    return Board(Store(":memory:"), pool=StubPool(), free_mb=lambda: 4096)


def _rig(board):
    owner = board.participant_create("human", Role.owner, "owner", id_="owner")
    epic = board.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    arch = board.participant_create("agent", Role.architect, f"architect.{epic.id}", id_=f"architect.{epic.id}")
    story = board.ticket_create(arch, kind=TicketKind.story, work_type=WorkType.feature, title="S", parent_id=epic.id)
    return owner, epic, arch, story


def _spawn(board, arch, monkeypatch, pool_reply, **kw):
    c = TestClient(create_app(board, admin_token="t"))
    calls: list[tuple[str, dict]] = []

    def pool(fn, args):
        calls.append((fn, dict(args)))
        reply = pool_reply(fn, args) if callable(pool_reply) else pool_reply
        return reply

    monkeypatch.setattr(bundles_mod, "_pool_call", pool)
    set_client(BoardClient(participant=arch.id, admin_token="t", client=c))
    out = ALL_TOOLS["spawn"].handler(ALL_TOOLS["spawn"].args_model(**kw))
    return out, calls


# ----------------------------------------------------------------------------- G5
def test_qa_refusal_names_the_next_move(board):
    owner, epic, arch, story = _rig(board)
    qa = board.participant_create("agent", Role.qa, f"qa.{epic.id}", id_=f"qa.{epic.id}")
    with pytest.raises(BoardError) as ei:
        board.criterion_create(qa, ticket_id=story.id, text="x", check=Check.command)
    assert "qa may not write criteria" in ei.value.message
    assert "kind='deviation'" in ei.value.hint and "architect" in ei.value.hint


# ----------------------------------------------------------------------------- G6
def _inbox_texts(board, me):
    c = TestClient(create_app(board, admin_token="t"))
    return [(m["kind"], m["text"]) for m in c.get("/v1/inbox", headers={"X-Participant": me}).json()["value"]]


def test_spawn_steer_is_on_the_board_before_launch_and_not_sent_to_the_pool(board, monkeypatch):
    owner, epic, arch, story = _rig(board)
    me = f"engineer.{story.id}"
    seen_at_launch: list = []

    def reply(fn, args):
        if fn == "spawn":  # the steer must already wait for the seat when the shell starts
            seen_at_launch.extend(_inbox_texts(board, me))
        return {"ok": True, "value": {"session_id": "s1"}}

    out, calls = _spawn(board, arch, monkeypatch, reply, role="engineer", ticket_id=story.id,
                        steer="no consult tool exists; build task 1 first")
    assert out["ok"], out
    assert ("steer", "no consult tool exists; build task 1 first") in seen_at_launch
    assert "steer" not in next(a for fn, a in calls if fn == "spawn")


def test_spawn_steer_thread_comes_from_a_role_ticket_participant_id(board, monkeypatch):
    owner, epic, arch, story = _rig(board)
    out, _ = _spawn(board, arch, monkeypatch, {"ok": True, "value": {}}, role="engineer",
                    participant_id=f"engineer.{story.id}", steer="start with the tests")
    assert out["ok"], out
    assert ("steer", "start with the tests") in _inbox_texts(board, f"engineer.{story.id}")


def test_no_steer_posts_nothing(board, monkeypatch):
    owner, epic, arch, story = _rig(board)
    out, _ = _spawn(board, arch, monkeypatch, {"ok": True, "value": {}}, role="engineer", ticket_id=story.id)
    assert out["ok"] and _inbox_texts(board, f"engineer.{story.id}") == []


def test_a_refused_spawn_leaves_no_steer_behind(board, monkeypatch):
    owner, epic, arch, story = _rig(board)
    me = f"engineer.{story.id}"
    out, _ = _spawn(board, arch, monkeypatch, {"ok": True, "value": {}}, role="engineer", ticket_id=story.id,
                    model="zz-not-a-model", steer="build task 1")
    assert out["ok"] is False and out["error"]["code"] == "invalid", out
    assert _inbox_texts(board, me) == []


@pytest.mark.parametrize("state", ["alive", "parked"])
def test_a_spawn_the_pool_would_refuse_leaves_no_steer_behind(board, monkeypatch, state):
    owner, epic, arch, story = _rig(board)
    me = f"engineer.{story.id}"

    def pool(fn, args):
        return {"ok": True, "value": {"state": state}} if fn == "liveness" else {"ok": True, "value": {}}

    out, calls = _spawn(board, arch, monkeypatch, pool, role="engineer", ticket_id=story.id, steer="build task 1")
    assert out["ok"] is False and out["error"]["code"] == "conflict", out
    assert _inbox_texts(board, me) == [] and not any(fn == "spawn" for fn, _ in calls)


def test_a_retried_spawn_posts_the_steer_once(board, monkeypatch):
    owner, epic, arch, story = _rig(board)
    for _ in range(2):
        out, _ = _spawn(board, arch, monkeypatch, {"ok": True, "value": {}}, role="engineer", ticket_id=story.id,
                        steer="build task 1")
        assert out["ok"], out
    assert _inbox_texts(board, f"engineer.{story.id}") == [("steer", "build task 1")]


# ----------------------------------------------------------------------------- teammate default role
def test_teammate_create_defaults_to_guest_never_owner():
    from edp8.bundles import TeammateArgs
    seen: dict = {}

    class _C:
        participant = "owner"

        def teammate_create(self, handle, role="guest", admin=False):
            seen.update(handle=handle, role=role, admin=admin)
            return {"ok": True, "value": {}}

    set_client(_C())
    out = ALL_TOOLS["teammate"].handler(TeammateArgs(action="create", handle="@carol"))
    assert out["ok"] and seen == {"handle": "carol", "role": "guest", "admin": False}
    import inspect
    assert inspect.signature(BoardClient.teammate_create).parameters["role"].default == "guest"


# ----------------------------------------------------------------------------- G4
def test_spawning_onto_a_parked_seat_says_resume_or_reap(board, monkeypatch):
    owner, epic, arch, story = _rig(board)

    def pool(fn, args):
        if fn == "spawn":
            return {"ok": False, "error": "handle lock held by sid-1"}
        if fn == "liveness":
            return {"ok": True, "value": {"state": "parked"}}
        return {"ok": True, "value": {}}

    out, calls = _spawn(board, arch, monkeypatch, pool, role="engineer", ticket_id=story.id)
    assert out["ok"] is False and "parked (resumable)" in out["error"]["message"]
    assert f"resume(participant_id='engineer.{story.id}')" in out["hint"]
    assert "reap it, then spawn again with a steer" in out["hint"]
    assert not any(fn == "reap" for fn, _ in calls)  # a parked seat is never reaped for the caller


def test_spawning_onto_an_alive_seat_still_says_message_it(board, monkeypatch):
    owner, epic, arch, story = _rig(board)

    def pool(fn, args):
        if fn == "spawn":
            return {"ok": False, "error": "handle lock held by sid-1"}
        return {"ok": True, "value": {"state": "alive"}}

    out, _ = _spawn(board, arch, monkeypatch, pool, role="engineer", ticket_id=story.id)
    assert out["ok"] is False and "already staffed" in out["error"]["message"]
    assert "message the seat" in out["hint"]
