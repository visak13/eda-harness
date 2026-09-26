"""S19 Help agent + diagnostics (design-e963c656f5 §4.14(e).5, story s-d8a2452ae9).

- c-77bbea9ee3: the doctor's bundle has no write tool; with three planted faults (pool stopped, a gate no
  human can answer, a saturated cap) the health tools and why_stuck name each root cause; the
  troubleshooting guides cover every failure class.
- c-190f5c6276: a proposed fix is an admin approval card carrying the exact action; nothing changes before
  Approve; Approve runs it once through the S5 route and posts the result back; Reject runs nothing; Ask
  for help (POST /v1/help) and `heronry doctor --agent` open the doctor on a help thread.

Private in-process boards only: the pool, the supervisor and the service table are faked.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from admin_support import ADMIN_H, BOB_H, make_env
from edp8 import control, doctor, fixes, pool_adapter, topics
from edp8.admin import services as admin_services
from edp8.board import BoardError
from edp8.bundles import ALL_TOOLS, READ_ONLY_ROLES, ROLE_BUNDLES, tools_for_role
from edp8.schemas import EventKind, TicketKind, WorkType

V8 = Path(__file__).resolve().parents[1]

#: every tool the doctor may hold: reads, its thread's messages, propose_fix (inert until an admin approves)
#: and the kernel's communication tools (architect ruling m-ec43dddf3e (1))
DOCTOR_ALLOWED = {
    "whoami", "preflight", "subscribe", "resume_self", "context", "context_delta", "describe", "describe_objects",
    "get_guide", "ticket_read", "ticket_query", "criterion_query", "doc_read", "doc_query", "message_send",
    "message_query", "message_read", "gates", "participants", "events_query", "board", "find", "lookup",
    "doctor_health", "doctor_pool", "doctor_feed_lag", "doctor_dead_mail", "why_stuck", "workflow_check",
    "doctor_pains", "doctor_logs", "propose_fix", "inbox", "record_status", "close_self",
}
#: a tool whose name says it writes (create/update/edit/answer/open/spawn/record/withdraw/…)
_WRITE_NAME = re.compile(r"(create|update|edit|upload|answer|open|spawn|reap|record_(?!status)|withdraw|set_|"
                         r"close_(?!self)|delete|link|assign|publish|research|repin)")

FAILURE_CLASSES = ("service-down", "mcp-401", "pool-port-exhaustion", "stuck-ticket", "feed-lag",
                   "broker-dead-mail", "harness-login", "update-failed", "caps-saturated")


# ----------------------------------------------------------------------------- c-77bbea9ee3 (a): read-only bundle
def test_doctor_bundle_is_exactly_the_read_only_allow_list():
    names = [t.name for t in tools_for_role("doctor")]
    assert set(names) == DOCTOR_ALLOWED, sorted(set(names) ^ DOCTOR_ALLOWED)
    assert names[-1] == "close_self"
    assert "doctor" in READ_ONLY_ROLES
    # no tool outside the communication kernel and propose_fix carries a write-shaped name
    writes = {n for n in names if _WRITE_NAME.search(n)} - {"message_send", "propose_fix"}
    assert writes == set(), writes
    for n in ROLE_BUNDLES["doctor"]:
        assert n in ALL_TOOLS


def test_doctor_seat_spawns_without_shell_or_edit_tools():
    from edp8.board import DOCTOR_DISALLOWED_TOOLS, Board
    from edp8.store import Store
    DISALLOWED_TOOLS_ENV = "EDP_SEAT_DISALLOWED_TOOLS"  # edp_pool.spawner turns it into --disallowedTools
    for tool in ("Bash", "PowerShell", "Edit", "Write"):
        assert tool in DOCTOR_DISALLOWED_TOOLS.split(",")
    b = Board(Store(":memory:"))
    assert b.seat_spawn_spec(None, "doctor")["env"].get(DISALLOWED_TOOLS_ENV) == DOCTOR_DISALLOWED_TOOLS
    assert DISALLOWED_TOOLS_ENV not in b.seat_spawn_spec(None, "engineer")["env"]


def test_doctor_is_a_standard_workflow_role_with_a_card():
    from edp8.workflow import build_standard, validate
    wf = build_standard()
    assert {r.id: r.spawnable for r in wf.roles}.get("doctor") is True
    assert [p for p in validate(wf) if p["severity"] == "error"] == []
    card = (V8 / ".claude" / "commands" / "doctor.md").read_text(encoding="utf-8")
    for c in FAILURE_CLASSES:
        assert f"troubleshooting-{c}" in card, c


# ----------------------------------------------------------------------------- c-77bbea9ee3 (c): guides
def test_troubleshooting_guides_cover_every_failure_class():
    causes = set()
    src = (V8 / "src" / "edp8" / "doctor.py").read_text(encoding="utf-8")
    causes |= set(re.findall(r'guide="([a-z0-9-]+)"', src))
    assert causes <= set(FAILURE_CLASSES), causes - set(FAILURE_CLASSES)
    for c in FAILURE_CLASSES:
        p = V8 / "guides" / f"troubleshooting-{c}.md"
        assert p.is_file(), p
        text = p.read_text(encoding="utf-8")
        for part in ("**Symptom.**", "**Evidence.**", "**Verify.**"):
            assert part in text, (c, part)
        assert "<!-- roles: doctor -->" in text
    # ruling m-ec43dddf3e (2): pins never change, said once where a workflow fix comes up
    for c in ("stuck-ticket", "update-failed"):
        assert "A workflow pin never changes" in (V8 / "guides" / f"troubleshooting-{c}.md").read_text(encoding="utf-8")


# ----------------------------------------------------------------------------- c-77bbea9ee3 (b): planted faults
def _fake_services(monkeypatch, pool_state: str = "running"):
    rows = [{"service": s, "state": "running", "health": "up"} for s in ("board", "broker", "mcp", "bridge")]
    rows.append({"service": "pool", "state": pool_state, "health": "up" if pool_state == "running" else pool_state})
    monkeypatch.setattr(admin_services, "status",
                        lambda: {"services": rows, "supervisor": {"running": True, "control": True}})


def _fake_pool(monkeypatch, *, up: bool, limits: dict | None = None):
    monkeypatch.setattr(pool_adapter, "reachable", lambda timeout=2.0: up)
    monkeypatch.setattr(pool_adapter, "sessions", lambda: {"ok": up, "value": []})
    monkeypatch.setattr(pool_adapter, "_get", lambda path, params=None: {"ok": limits is not None, "value": limits})
    monkeypatch.setattr(pool_adapter, "_post", lambda path, body=None, timeout=90.0: pytest.fail(f"pool POST {path}"))


def _owner(env):
    return env.board.store.get("participant", "owner")


def _epic(env, title: str):
    return env.board.ticket_create(_owner(env), kind=TicketKind.epic, work_type=WorkType.feature, title=title,
                                   description="d")


def _codes(out: dict) -> set[str]:
    return {c["code"] for c in out["causes"]}


def test_three_planted_faults_are_each_named(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    c = env.client

    # fault 1: the pool is stopped
    _fake_services(monkeypatch, pool_state="stopped")
    _fake_pool(monkeypatch, up=False)
    h = c.get("/v1/doctor/health", headers=ADMIN_H).json()["value"]
    assert {"service_down", "pool_unreachable"} <= _codes(h)
    down = next(x for x in h["causes"] if x["code"] == "service_down")
    assert "pool" in down["what"] and down["guide"] == "troubleshooting-service-down"
    assert _codes(c.get("/v1/doctor/pool", headers=ADMIN_H).json()["value"]) == {"pool_unreachable"}

    # fault 2: a gate no human can answer (design sign-off open on an epic with no design)
    stuck = _epic(env, "an epic whose sign-off nobody can give")
    env.board._emit(stuck.id, EventKind.gate_opened, {"gate": "design_signoff", "note": "please sign off"})
    w = c.get(f"/v1/doctor/why-stuck/{stuck.id}", headers=ADMIN_H).json()["value"]
    g = next(x for x in w["causes"] if x["code"] == "gate_unanswerable")
    assert "design_signoff" in g["what"] and g["guide"] == "troubleshooting-stuck-ticket"
    assert set(g["evidence"]["refusals"]) == {"owner", "bob"}          # every human was asked, all refused
    assert all(g["evidence"]["refusals"].values())
    assert w["ticket"]["open_gates"][0]["answerable_by"] == []

    # fault 3: a cap is saturated while a seat this ticket needs waits
    _fake_services(monkeypatch)
    lim = {"max_total_shells": 10, "max_live_shells": 10, "max_workers": 2, "max_planners": 2, "role_caps": {},
           "usage": {"total": 4, "live": 4, "classes": {"builder": 2, "planner": 1}, "roles": {}}}
    _fake_pool(monkeypatch, up=True, limits=lim)
    waiting = _epic(env, "an epic waiting for its engineer")
    env.board._pending_pairings[f"engineer.{waiting.id}"] = {"role": "engineer", "ticket": waiting.id}
    w = c.get(f"/v1/doctor/why-stuck/{waiting.id}", headers=ADMIN_H).json()["value"]
    cap = next(x for x in w["causes"] if x["code"] == "cap_saturated")
    assert "builder class 2/2" in cap["what"] and cap["guide"] == "troubleshooting-caps-saturated"
    p = c.get("/v1/doctor/pool", headers=ADMIN_H).json()["value"]
    assert {"cap_saturated", "spawns_queued"} <= _codes(p)
    assert p["saturated"] == [{"cap": "builder class", "limit": 2, "in_use": 2}]
    # the healthy stack has no health cause
    assert _codes(c.get("/v1/doctor/health", headers=ADMIN_H).json()["value"]) == set()


def test_doctor_reads_are_for_the_doctor_and_admins_only(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    _fake_services(monkeypatch)
    _fake_pool(monkeypatch, up=True, limits=None)
    from admin_support import AGENT_H
    for path in ("health", "pool", "feed-lag", "dead-mail", "pains", "logs/board"):
        assert env.client.get(f"/v1/doctor/{path}", headers=AGENT_H).status_code == 403, path
        assert env.client.get(f"/v1/doctor/{path}", headers=ADMIN_H).status_code == 200, path


def test_feed_lag_and_dead_mail_name_their_causes(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from edp8 import settings
    from edp8.schemas import Session, SessionState
    env = make_env(tmp_path, monkeypatch)
    b = env.board
    b.store.put("session", Session(id="sess-1", participant_id="eng.x", pool_id="p-1", state=SessionState.alive))
    b._emit("t-x", EventKind.message_sent, {"to": "eng.x", "text": "ping"})
    now = datetime.now(timezone.utc).timestamp() + 600
    out = doctor.feed_lag(b, {"eng.x": now - 3600}, now=now)
    assert _codes(out) == {"feed_lag"} and out["seats"][0]["unread_addressed"] == 1
    log = Path(settings.logs_dir()) / "broker.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(json.dumps({"ts": "t", "event": "publish_no_route", "to": "ghost.seat"}) + "\n", encoding="utf-8")
    d = doctor.dead_mail(b)
    assert d["count"] == 1 and _codes(d) == {"dead_mail"} and "ghost.seat" in d["causes"][0]["what"]


# ----------------------------------------------------------------------------- c-190f5c6276: help threads
def test_ask_for_help_opens_then_resumes_a_help_thread_with_a_doctor_seat(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch)
    r = env.client.post("/v1/help", json={"text": "my seats keep dying"}, headers=BOB_H)
    assert r.status_code == 200, r.text
    v = r.json()["value"]
    tid = v["topic"]["id"]
    assert v["resumed"] is False and v["topic"]["tags"] == ["help"] and v["topic"]["created_by"] == "bob"
    assert v["seat"]["participant"] == f"doctor.{tid}" and v["url"] == f"/ui/library/topics/{tid}"
    assert env.board._pending_pairings[f"doctor.{tid}"]["role"] == "doctor"   # queued for spawn by the tick
    seat = env.board.store.get("participant", f"doctor.{tid}")
    assert seat.role.value == "doctor" and env.board.topic_of_seat(seat).id == tid
    msgs = env.board.store.query("message", {"ticket_id": tid}, limit=-1)
    assert any(m.to == f"doctor.{tid}" and m.text == "my seats keep dying" for m in msgs)
    # a second ask resumes the same thread; a help thread never lists in the Library
    v2 = env.client.post("/v1/help", json={"text": "still dying"}, headers=BOB_H).json()["value"]
    assert v2["resumed"] is True and v2["topic"]["id"] == tid
    assert tid not in {t["id"] for t in topics.list_view(env.board)}
    # the help tag is the board's, not a Library topic's
    with pytest.raises(BoardError, match="help thread"):
        topics.create(env.board, _owner(env), title="sneaky", tags=["help"])
    # agents do not ask for help here
    from admin_support import AGENT_H
    assert env.client.post("/v1/help", json={"text": "x"}, headers=AGENT_H).status_code == 403


def test_heronry_doctor_agent_opens_the_help_thread(tmp_path, monkeypatch, capsys):
    import httpx

    from edp8 import help as help_threads
    from edp8 import launcher
    from edp8.setup import doctor_cmd
    env = make_env(tmp_path, monkeypatch)
    monkeypatch.setattr(launcher, "url", lambda svc: "http://board.test")
    seen = {}

    def post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, headers=headers)
        return env.client.post(url.removeprefix("http://board.test"), json=json, headers=headers)
    monkeypatch.setattr(httpx, "post", post)
    assert doctor_cmd(["--agent", "the", "board", "is", "slow"]) == 0
    out = capsys.readouterr().out
    assert seen["url"] == "http://board.test/v1/help" and seen["headers"]["X-Participant"] == "owner"
    t = help_threads.open_thread(env.board, _owner(env))
    assert t is not None and f"opened help thread {t.id}" in out and f"doctor.{t.id}" in out
    assert f"/ui/library/topics/{t.id}" in out
    assert doctor_cmd(["--agent"]) == 0 and f"resumed help thread {t.id}" in capsys.readouterr().out


# ----------------------------------------------------------------------------- c-190f5c6276: fixes
def _doctor_env(tmp_path, monkeypatch):
    """A help thread from bob with its doctor seat holding an agent token."""
    env = make_env(tmp_path, monkeypatch)
    tid = env.client.post("/v1/help", json={"text": "seats queue forever"}, headers=BOB_H).json()["value"]["topic"]["id"]
    seat = f"doctor.{tid}"
    data = env.tokens_data()
    data["agents"][seat] = "doc-secret"
    env.tokens.write_text(json.dumps(data), encoding="utf-8")
    st = env.tokens.stat()
    os.utime(env.tokens, (st.st_atime, st.st_mtime + 5))
    return env, tid, {"X-Participant": seat, "X-Token": "doc-secret"}


def _fake_supervisor(monkeypatch):
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(control, "endpoint", lambda: (1, "tok"))

    def request(path, body=None, *, timeout=180.0):
        calls.append((path, body))
        return 200, {"service": path.split("/")[2], "state": "running"}
    monkeypatch.setattr(control, "request", request)
    return calls


def test_a_fix_is_an_admin_card_that_changes_nothing_until_approve(tmp_path, monkeypatch):
    env, tid, DOC_H = _doctor_env(tmp_path, monkeypatch)
    calls = _fake_supervisor(monkeypatch)
    c = env.client
    before_events = len(env.board.store.query("event", {"kind": "service_restarted"}, limit=-1))

    r = c.post("/v1/fixes", json={"topic_id": tid, "effect": "restart the pool process; seats are re-adopted",
                                  "action": {"kind": "service.restart", "service": "pool", "keep_seats": True}},
               headers=DOC_H)
    assert r.status_code == 200, r.text
    f = r.json()["value"]
    assert f["status"] == "proposed" and f["created_by"] == f"doctor.{tid}"
    assert f["request"] == {"method": "POST", "path": "/v1/admin/services/pool/restart",
                            "body": {"force": False, "keep_seats": True}}
    # the card shows the exact action, on the thread and in the admin's Needs you
    notes = [m.text for m in env.board.store.query("message", {"ticket_id": tid}, limit=-1) if m.created_by == "board"]
    assert any(f["id"] in n and "POST /v1/admin/services/pool/restart" in n and "keep_seats" in n for n in notes)
    needs = c.get("/v1/fixes?status=proposed", headers=ADMIN_H).json()["value"]
    assert [x["id"] for x in needs] == [f["id"]]
    # nothing changed before Approve
    assert calls == []
    assert len(env.board.store.query("event", {"kind": "service_restarted"}, limit=-1)) == before_events
    # a non-admin human and the doctor itself cannot approve
    assert c.post(f"/v1/admin/fixes/{f['id']}/approve", headers=BOB_H).status_code == 403
    assert c.post(f"/v1/admin/fixes/{f['id']}/approve", headers=DOC_H).status_code == 403
    assert calls == []

    r = c.post(f"/v1/admin/fixes/{f['id']}/approve", headers=ADMIN_H)
    assert r.status_code == 200, r.text
    v = r.json()["value"]
    assert v["fix"]["status"] == "applied" and v["fix"]["decided_by"] == "owner"
    assert v["fix"]["result"]["http_status"] == 200
    assert calls == [("/services/pool/restart", {"by": "owner", "force": False, "keep_seats": True})]  # once, exactly
    notes = [m.text for m in env.board.store.query("message", {"ticket_id": tid}, limit=-1) if m.created_by == "board"]
    assert any(n.startswith(f"[fix applied] {f['id']} approved by owner") and "HTTP 200" in n for n in notes)
    # a decided fix never runs again
    r = c.post(f"/v1/admin/fixes/{f['id']}/approve", headers=ADMIN_H)
    assert r.status_code == 409 and len(calls) == 1
    assert c.post(f"/v1/admin/fixes/{f['id']}/reject", headers=ADMIN_H).status_code == 409


def test_reject_runs_nothing_and_a_failed_route_is_recorded(tmp_path, monkeypatch):
    env, tid, DOC_H = _doctor_env(tmp_path, monkeypatch)
    calls = _fake_supervisor(monkeypatch)
    c = env.client
    f = c.post("/v1/fixes", json={"topic_id": tid, "effect": "restart the broker",
                                  "action": {"kind": "service.restart", "service": "broker"}}, headers=DOC_H).json()["value"]
    r = c.post(f"/v1/admin/fixes/{f['id']}/reject", json={"reason": "not now"}, headers=ADMIN_H)
    assert r.status_code == 200 and r.json()["value"]["status"] == "rejected"
    assert calls == []
    assert c.post(f"/v1/admin/fixes/{f['id']}/approve", headers=ADMIN_H).status_code == 409 and calls == []
    notes = [m.text for m in env.board.store.query("message", {"ticket_id": tid}, limit=-1)]
    assert any(n.startswith(f"[fix rejected] {f['id']} by owner; nothing ran. Reason: not now") for n in notes)

    # a gate answer the gate's own rules refuse: approved, run as the admin, recorded failed, posted back
    epic = _epic(env, "e")
    env.board._emit(epic.id, EventKind.gate_opened, {"gate": "design_signoff", "note": "n"})
    g = c.post("/v1/fixes", json={"topic_id": tid, "effect": "answer the sign-off",
                                  "action": {"kind": "gate.answer", "ticket_id": epic.id, "gate": "design_signoff",
                                             "answer": "approved"}}, headers=DOC_H).json()["value"]
    assert g["request"]["path"] == f"/v1/gates/{epic.id}/design_signoff/answer"
    v = c.post(f"/v1/admin/fixes/{g['id']}/approve", headers=ADMIN_H).json()["value"]
    assert v["fix"]["status"] == "failed" and v["fix"]["result"]["http_status"] >= 400
    assert env.board.open_gates(epic.id)          # the gate's rules held: still open


def test_rotate_token_result_is_redacted_on_the_thread(tmp_path, monkeypatch):
    env, tid, DOC_H = _doctor_env(tmp_path, monkeypatch)
    c = env.client
    f = c.post("/v1/fixes", json={"topic_id": tid, "effect": "bob's token leaked in a screenshot",
                                  "action": {"kind": "teammate.rotate_token", "handle": "bob"}},
               headers=DOC_H).json()["value"]
    r = c.post(f"/v1/admin/fixes/{f['id']}/approve", headers=ADMIN_H)
    assert r.status_code == 200, r.text
    new = env.tokens_data()["bob"]
    assert new != "bob-secret"
    assert new in json.dumps(r.json()["value"]["response"])            # shown once, to the approver
    stored = fixes.get(env.board, f["id"])
    assert new not in json.dumps(stored.result)
    assert all(new not in m.text for m in env.board.store.query("message", {"ticket_id": tid}, limit=-1))


@pytest.mark.parametrize("action,why", [
    ({"kind": "agent_token.revoke", "handle": "../../admin/x"}, "path"),
    ({"kind": "service.restart", "service": "code-server"}, "service"),
    ({"kind": "epic.repin", "epic_id": "epic-1", "to": "standard@2"}, "repin"),
    ({"kind": "service.restart", "service": "pool", "shell": "rm -rf /"}, "extra"),
    ({"kind": "pool.set_limits"}, "empty"),
])
def test_only_the_closed_action_set_can_be_proposed(tmp_path, monkeypatch, action, why):
    env, tid, DOC_H = _doctor_env(tmp_path, monkeypatch)
    r = env.client.post("/v1/fixes", json={"topic_id": tid, "effect": "x", "action": action}, headers=DOC_H)
    assert r.status_code == 422, (why, r.text)
    assert env.board.store.query("fix", {}, limit=-1) == []


def test_only_the_threads_doctor_proposes(tmp_path, monkeypatch):
    env, tid, DOC_H = _doctor_env(tmp_path, monkeypatch)
    body = {"topic_id": tid, "effect": "x", "action": {"kind": "service.restart", "service": "broker"}}
    assert env.client.post("/v1/fixes", json=body, headers=ADMIN_H).status_code == 403
    other = env.client.post("/v1/help", json={"text": "me too"}, headers=ADMIN_H).json()["value"]["topic"]["id"]
    assert env.client.post("/v1/fixes", json={**body, "topic_id": other}, headers=DOC_H).status_code == 403
    assert env.client.get("/v1/fixes", headers=BOB_H).status_code == 403
    assert env.client.get("/v1/fixes", headers=DOC_H).status_code == 200


def test_heronry_doctor_agent_reports_the_boards_refusal(tmp_path, monkeypatch, capsys):
    import httpx

    from edp8 import launcher
    from edp8.setup import doctor_cmd
    env = make_env(tmp_path, monkeypatch)
    monkeypatch.setattr(launcher, "url", lambda svc: "http://board.test")
    monkeypatch.setenv("EDP8_OWNER", "eng.x")          # an agent handle: the board refuses Ask for help
    data = env.tokens_data()
    data["eng.x"] = "eng-secret"
    env.tokens.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(httpx, "post", lambda url, json=None, headers=None, timeout=None:
                        env.client.post(url.removeprefix("http://board.test"), json=json, headers=headers))
    assert doctor_cmd(["--agent", "help"]) == 1
    assert "refused the help request (403)" in capsys.readouterr().err
