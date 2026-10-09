"""S14 (s-f5192222b1): board<->pool liveness and feed/wake delivery, proven on a private board.

Every board here is an in-memory Store behind a TestClient; the pool is a stub at the pool_adapter seam
(never the fleet pool at :9301). One test per behaviour, each tied to the pains it covers.
"""

from __future__ import annotations

import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import json

import pytest
from fastapi.testclient import TestClient

from edp8 import pool_adapter
from edp8.board import Board
from edp8.schemas import EventKind, SessionState
from edp8.service import create_app
from edp8.store import Store

ADMIN = {"X-Admin": "t"}
OWNER = {"X-Participant": "owner"}


def _rig(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP8_TOKENS", str(tmp_path / "absent-tokens.json"))
    board = Board(Store(":memory:"))
    c = TestClient(create_app(board, admin_token="t"))
    assert c.post("/v1/participants", json={"type": "human", "role": "owner", "handle": "owner", "id": "owner"},
                  headers=ADMIN).json()["ok"]
    epic = c.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "E"},
                  headers=OWNER).json()["value"]["id"]
    arch = f"architect.{epic}"
    assert c.post("/v1/participants", json={"type": "agent", "role": "architect", "handle": arch, "id": arch},
                  headers=ADMIN).json()["ok"]
    return board, c, epic, arch


class _Mirror:
    """A pool stub whose session rows are what a real pool lists: spawn records its env, like the pool's
    spawn_settings, and sync_sessions mirrors the rows into the board over the TestClient."""

    def __init__(self, monkeypatch, c):
        self.rows: list[dict] = []
        self.spawns: list[dict] = []
        self.liveness: dict[str, dict] = {}
        self.c = c
        monkeypatch.setattr(pool_adapter, "reachable", lambda *a, **k: True)
        monkeypatch.setattr(pool_adapter, "spawn", self._spawn)
        monkeypatch.setattr(pool_adapter, "sessions", lambda: {"ok": True, "value": list(self.rows)})
        monkeypatch.setattr(pool_adapter, "reap", lambda pid: {"ok": True, "value": {"reaped": pid}})
        monkeypatch.setattr(pool_adapter.httpx, "Client", lambda *a, **k: self._http())

    def _spawn(self, role, participant_id, **kw):
        self.spawns.append({"role": role, "participant_id": participant_id, **kw})
        self.rows.append({"session_id": f"sess-{len(self.rows)}", "handle": participant_id, "state": "active",
                          "spawn_settings": {"env": dict(kw.get("env") or {})}})
        return {"ok": True, "value": {"session_id": self.rows[-1]["session_id"]}}

    def _http(self):
        mirror = self

        class _R:
            def __init__(self, status=200, data=None):
                self.status_code, self._d, self.content, self.text = status, data, b"{}", ""

            def json(self):
                return self._d

        class _C:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def get(self, url):
                pid = url.rsplit("/", 1)[1]
                return _R(200, mirror.liveness.get(pid, {"state": "alive"}))

            def put(self, url, json=None, headers=None):
                path = "/" + url.split("/", 3)[3]
                return mirror.c.put(path, json=json, headers=headers)

        return _C()

    def sync(self):
        out = pool_adapter.sync_sessions(board_url="http://testserver", admin_token="t")
        assert out["ok"], out
        return out


def _sessions(c, participant_id):
    return c.get("/v1/sessions", params={"participant_id": participant_id}, headers=OWNER).json()["value"]


# --------------------------------------------------------------- spawn identity (p-a05affa0)

def test_rest_spawn_with_a_custom_participant_id_keeps_the_spawn_ticket_so_the_architect_can_reap(
        tmp_path, monkeypatch):
    board, c, epic, arch = _rig(tmp_path, monkeypatch)
    mirror = _Mirror(monkeypatch, c)
    story = c.post("/v1/tickets", json={"kind": "story", "work_type": "review", "title": "R", "parent_id": epic},
                   headers=OWNER).json()["value"]["id"]
    custom = f"adversary.{story}-r2"  # the handle suffix names NO ticket: "<story>-r2"
    assert c.post("/v1/participants", json={"type": "agent", "role": "adversary", "handle": custom, "id": custom},
                  headers=ADMIN).json()["ok"]
    r = c.post("/v1/sessions/spawn", json={"role": "adversary", "participant_id": custom, "ticket_id": story},
               headers=OWNER)
    assert r.json()["ok"], r.text
    # the spawn names its ticket to the pool, so the pool row (and the mirror) carry it
    assert mirror.spawns[0]["env"]["EDP_SPAWN_TICKET"] == story
    mirror.sync()
    rows = _sessions(c, custom)
    assert [x["ticket_id"] for x in rows] == [story], rows
    # the architect reaps the seat with only its participant_id: the epic resolves through the session row
    arch_h = {"X-Participant": arch}
    r = c.post("/v1/sessions/reap", json={"participant_id": custom}, headers=arch_h)
    assert r.status_code == 200 and r.json()["ok"], r.text


# --------------------------------------------------------------- force quit (owner m-e2edc8d256)

class _CountingPool:
    def __init__(self):
        self.spawns: list[tuple[str, str]] = []

    def spawn(self, role, participant_id, **kw):
        self.spawns.append((role, participant_id))
        return {"ok": True, "participant_id": participant_id}


def _qa_ready_epic(b, owner, epic):
    """Every story in_review and a qa-checked line pending (written straight to the store); the epic then moves on."""
    from edp8.schemas import Check, Criterion, TicketKind, TicketStatus, WorkType
    from edp8.store import new_id
    story = b.store.get("ticket", b.ticket_create(owner, kind=TicketKind.story, work_type=WorkType.feature, title="S",
                                                  parent_id=epic.id).id)
    b.store.put("ticket", story.model_copy(update={"status": TicketStatus.in_review}))
    b.store.put("criterion", Criterion(id=new_id("c"), ticket_id=story.id, text="c", check=Check.command,
                                       checked_by="qa", created_by=owner.id))
    b.store.put("ticket", b.ticket(epic.id).model_copy(update={"status": TicketStatus.in_progress}))
    b._advance_epic_phase(b.ticket(epic.id), TicketStatus.in_review, trigger="every story released")


def _hints(b, subject, hint):
    return [e for e in b.store.query("event", {"subject_id": subject, "kind": EventKind.board_hint}, limit=100)
            if e.data.get("hint") == hint]


def test_a_qa_ready_epic_spawns_no_seat_on_any_tick_or_restart_and_hints_the_architect_once(tmp_path):
    from edp8.schemas import Role, TicketKind, TicketStatus, WorkType
    db = str(tmp_path / "board.db")
    pool1 = _CountingPool()
    b = Board(Store(db), pool=pool1, free_mb=lambda: 4096)
    owner = b.participant_create("human", Role.owner, "owner")
    epic = b.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    arch = b.participant_create("agent", Role.architect, f"architect.{epic.id}", id_=f"architect.{epic.id}")
    _qa_ready_epic(b, owner, epic)
    assert b.ticket(epic.id).status == TicketStatus.in_review
    for _ in range(3):  # pool-watch ticks
        assert b.run_pending_pairings()["spawned"] == []
    assert pool1.spawns == [] and b.open_gates(epic.id) == []
    got = _hints(b, epic.id, "qa_available")
    assert len(got) == 1 and got[0].data["text"] == "epic moved to in_review, qa now available for review"
    assert [r.value for r in b._architect_listener_reasons(got[0], b.participant(arch.id))] == ["architect_listener"]
    pool2 = _CountingPool()
    b2 = Board(Store(db), pool=pool2, free_mb=lambda: 4096)  # a restart stages and asks nothing either
    for _ in range(3):
        assert b2.run_pending_pairings()["spawned"] == []
    assert pool2.spawns == [] and len(_hints(b2, epic.id, "qa_available")) == 1
    from edp8.schemas import MessageKind
    assert not [m for m in b2.store.query("message", {"ticket_id": epic.id}, limit=-1) if m.kind == MessageKind.question]


def test_a_new_requirement_story_reopens_an_in_review_epic(tmp_path):
    from edp8.schemas import Role, TicketKind, TicketStatus, WorkType
    b = Board(Store(str(tmp_path / "board.db")), pool=_CountingPool(), free_mb=lambda: 4096)
    owner = b.participant_create("human", Role.owner, "owner")
    epic = b.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    _qa_ready_epic(b, owner, epic)
    s2 = b.ticket_create(owner, kind=TicketKind.story, work_type=WorkType.feature, title="S2", parent_id=epic.id)
    b.store.put("ticket", b.ticket(s2.id).model_copy(update={"status": TicketStatus.in_progress}))
    b._after_status(b.ticket(s2.id))
    assert b.ticket(epic.id).status == TicketStatus.in_progress


def test_restarts_with_help_threads_open_post_no_board_ask_and_spawn_nothing(tmp_path):
    from edp8 import help as help_threads
    from edp8.schemas import MessageKind, Role, TicketKind, WorkType
    db = str(tmp_path / "board.db")
    b = Board(Store(db), pool=_CountingPool(), free_mb=lambda: 4096)
    owner = b.participant_create("human", Role.owner, "owner")
    epic = b.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    b.participant_create("agent", Role.architect, f"architect.{epic.id}", id_=f"architect.{epic.id}")
    _qa_ready_epic(b, owner, epic)
    bob = b.participant_create("human", Role.owner, "bob")
    helps = [help_threads.ask(b, bob, f"seats keep dying {i}")["topic"]["id"] for i in range(2)]
    for _ in range(2):
        pool = _CountingPool()
        nb = Board(Store(db), pool=pool, free_mb=lambda: 4096)
        for _ in range(3):
            assert nb.run_pending_pairings()["spawned"] == []
        assert pool.spawns == []
    board_asks = [m for t in [epic.id, *helps] for m in nb.store.query("message", {"ticket_id": t}, limit=-1)
                  if m.kind == MessageKind.question and m.created_by == "board"]
    assert board_asks == []


# --------------------------------------------------------------- liveness mirror (p-fcb439ac, p-ed42a7ed)

def _agent(c, pid, role):
    assert c.post("/v1/participants", json={"type": "agent", "role": role, "handle": pid, "id": pid},
                  headers=ADMIN).json()["ok"]


def _deaths(board, subject):
    return board.store.query("event", {"subject_id": subject, "kind": EventKind.shell_dead}, limit=100)


def test_a_missed_probe_never_kills_a_live_seat_and_every_death_carries_a_reason(tmp_path, monkeypatch):
    board, c, epic, arch = _rig(tmp_path, monkeypatch)
    mirror = _Mirror(monkeypatch, c)
    qa = f"qa.{epic}"
    _agent(c, qa, "qa")
    mirror.rows.append({"session_id": "s-qa", "handle": qa, "state": "active"})
    mirror.sync()
    assert board.seat_state(qa) == "alive"
    # the pool did not answer the probe: the seat stays alive, the staleness is stamped, nothing is raised
    mirror.liveness[qa] = {"state": "unknown"}
    assert mirror.sync()["value"]["stale"] == 1
    row = board.store.get("session", "s-qa")
    assert row.state == SessionState.alive and row.presence_stale_since
    assert _deaths(board, epic) == []
    # a positive "dead" with no reason anywhere still lands with a reason, on the row and on the event
    mirror.liveness[qa] = {"state": "dead"}
    mirror.sync()
    assert board.seat_state(qa) == "dead"
    deaths = _deaths(board, epic)
    assert len(deaths) == 1 and deaths[0].data["reason"], deaths
    # a terminal pool row is mirrored dead with the reason the pool recorded, verbatim
    eng = f"engineer.{epic}"
    _agent(c, eng, "engineer")
    mirror.rows.append({"session_id": "s-eng", "handle": eng, "state": "done", "dead_reason": "closed by self: done"})
    mirror.sync()
    assert board.store.get("session", "s-eng").reason == "closed by self: done"
    # and one with no reason at all is still not blank
    sme = f"sme.{epic}"
    _agent(c, sme, "sme")
    mirror.rows.append({"session_id": "s-sme", "handle": sme, "state": "done"})
    mirror.sync()
    assert board.store.get("session", "s-sme").reason
    # a re-mirror of a long-dead row raises no second death
    n = len(_deaths(board, epic))
    mirror.sync()
    assert len(_deaths(board, epic)) == n


def test_a_clean_close_or_an_interrupted_seat_pages_nobody_but_a_crash_pages_owner_and_architect(
        tmp_path, monkeypatch):
    board, c, epic, arch = _rig(tmp_path, monkeypatch)
    owner, architect = board.store.get("participant", "owner"), board.store.get("participant", arch)
    story = c.post("/v1/tickets", json={"kind": "story", "work_type": "feature", "title": "S", "parent_id": epic},
                   headers=OWNER).json()["value"]["id"]

    board.session_upsert(id_="s-arch", participant_id=arch, ticket_id=epic, pool_id="p",
                         state=SessionState.alive)  # a live architect heals; with none the owner would hear

    def die(sid, pid, reason):
        board.session_upsert(id_=sid, participant_id=pid, ticket_id=story, pool_id="p",
                             state=SessionState.alive)
        board.session_upsert(id_=sid, participant_id=pid, ticket_id=story, pool_id="p",
                             state=SessionState.dead, reason=reason)
        return _deaths(board, story)[-1]

    for reason in ("closed by self: done", "interrupted: the pool stopped while this seat was live"):
        ev = die(f"s-{len(reason)}", f"engineer.{story}", reason)
        assert ev.data["clean"] is True
        # design-63db8a7d42 F: the owner is never paged; the architect hears every pool event (it decides on healing)
        assert not board.relevant(ev, owner) and board.relevant(ev, architect), reason
    ev = die("s-crash", f"engineer.{story}","process exited without close_self (exit unknown)")
    assert ev.data["clean"] is False
    assert board.relevant(ev, architect) and not board.relevant(ev, owner)


# --------------------------------------------------------------- spawned checker's plate and steer (p-95f72389, p-517dc669)

def test_a_directed_steer_reaches_a_spawned_checker_before_and_after_it_boots(tmp_path, monkeypatch):
    from edp8.schemas import MessageKind
    board, c, epic, arch = _rig(tmp_path, monkeypatch)
    story = c.post("/v1/tickets", json={"kind": "story", "work_type": "feature", "title": "S", "parent_id": epic},
                   headers=OWNER).json()["value"]["id"]
    eng = f"engineer.{story}"
    _agent(c, eng, "engineer")
    board.ticket_update(board.store.get("participant", "owner"), story, assignee=eng)
    rev = f"adversary.{story}"
    _agent(c, rev, "adversary")
    checker, architect = board.store.get("participant", rev), board.store.get("participant", arch)
    # the steer is sent while the checker shell is still booting (no session yet), on an in_progress story
    cursor = board.store.max_seq()
    steer = board.message_send(architect, ticket_id=story, to=rev, kind=MessageKind.steer, text="check c-1 only")
    # the story is on its plate although it is assigned to the engineer and not in review
    assert story in [t.id for t in board.my_tickets(checker)]
    # the steer is waiting in its inbox when it asks (whoami -> subscribe race)
    assert [a["id"] for a in board.inbox(checker)] == [steer.id]
    # and its feed carries the steer, tagged as addressed to it, replayed from a cursor taken before it was sent
    got = [e for _, e in board.replay(checker, cursor) if e.data.get("message") == steer.id]
    assert len(got) == 1 and board.why(got[0], checker) == "addressed to you"
    # a sibling checker on another story is not woken by it
    other = c.post("/v1/tickets", json={"kind": "story", "work_type": "feature", "title": "S2", "parent_id": epic},
                   headers=OWNER).json()["value"]["id"]
    _agent(c, f"adversary.{other}", "adversary")
    assert not board.relevant(got[0], board.store.get("participant", f"adversary.{other}"))


# --------------------------------------------------------------- Windows monitor command (p-6fd6edcf)

def test_subscribe_monitor_cmd_is_bash_safe_with_a_windows_python_path(monkeypatch):
    import shlex
    import sys

    from edp8 import bundles

    class _C:
        participant = "engineer.s-1"
        base_url = "http://127.0.0.1:9400"

        def listening(self):
            return {"ok": False}

    monkeypatch.setattr(bundles, "get_client", lambda: _C())
    monkeypatch.setattr(sys, "executable", "C:\\Users\\a b\\AppData\\Local\\Programs\\Python\\Python312\\python.exe")
    cmd = bundles._subscribe(bundles.SubscribeArgs())["value"]["monitor_cmd"]
    assert "\\" not in cmd, cmd  # bash eats backslashes: exit 127 on a Windows seat
    argv = shlex.split(cmd)  # how the Monitor tool's bash reads it
    assert argv[0] == "C:/Users/a b/AppData/Local/Programs/Python/Python312/python.exe"
    assert argv[1:4] == ["-m", "edp8.feed_driver", "--participant"] and argv[4] == "engineer.s-1"


# --------------------------------------------------------------- owner feed not flooded (p-c5d18cd3)

def test_the_owner_is_not_flooded_by_other_epics_or_by_asks_from_closed_seats(tmp_path, monkeypatch):
    from edp8.schemas import MessageKind
    board, c, epic, arch = _rig(tmp_path, monkeypatch)
    assert c.post("/v1/participants", json={"type": "human", "role": "owner", "handle": "owner2", "id": "owner2"},
                  headers=ADMIN).json()["ok"]
    epic2 = c.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "E2"},
                   headers={"X-Participant": "owner2"}).json()["value"]["id"]
    owner, owner2 = board.store.get("participant", "owner"), board.store.get("participant", "owner2")
    seat2 = f"engineer.{epic2}"
    _agent(c, seat2, "engineer")
    seat2_p = board.store.get("participant", seat2)
    # a question that another owner's epic addresses to the owner ROLE never reaches this owner's feed
    cursor = board.store.max_seq()
    q2 = board.message_send(seat2_p, ticket_id=epic2, to="owner", kind=MessageKind.question, text="which way?")
    ev2 = next(e for _, e in board.replay(owner2, cursor) if e.data.get("message") == q2.id)
    assert board.relevant(ev2, owner2) and not board.relevant(ev2, owner)
    assert [a["id"] for a in board.inbox(owner)] == []
    # an ask from a seat that has since closed is resolved: it leaves the inbox rather than piling up
    seat1 = f"engineer.{epic}"
    _agent(c, seat1, "engineer")
    board.session_upsert(id_="s1", participant_id=seat1, ticket_id=epic, pool_id="p", state=SessionState.alive)
    q1 = board.message_send(board.store.get("participant", seat1), ticket_id=epic, to="owner",
                            kind=MessageKind.question, text="may I?")
    assert [a["id"] for a in board.inbox(owner)] == [q1.id]
    board.session_upsert(id_="s1", participant_id=seat1, ticket_id=epic, pool_id="p", state=SessionState.dead,
                         reason="closed by self: done")
    assert board.inbox(owner) == []
