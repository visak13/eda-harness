"""Tests for the client/bundles layer: role scoping and a scripted flow through
the tool handlers (not through the MCP transport — the handlers are the unit)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from edp8.board import Board
from edp8.bundles import ALL_TOOLS, ROLE_BUNDLES, set_client, tools_for_role
from edp8.client import BoardClient
from edp8.service import create_app
from edp8.store import Store


@pytest.fixture
def board():
    return Board(Store(":memory:"))


@pytest.fixture
def app(board):
    return create_app(board, admin_token="t")


@pytest.fixture
def raw_client(app):
    return TestClient(app)


def make_client(raw_client, participant: str | None = None) -> BoardClient:
    return BoardClient(participant=participant, admin_token="t", client=raw_client)


def register(raw_client, role: str, handle: str) -> str:
    admin = make_client(raw_client)
    resp = admin._request("POST", "/v1/participants", admin=True,
                          json={"type": "agent", "role": role, "handle": handle})
    assert resp["ok"], resp
    return resp["value"]["id"]


# ----------------------------------------------------------------------------- role scoping


def test_owner_cannot_see_doc_create():
    owner_tools = {t.name for t in tools_for_role("owner")}
    assert "doc_create" not in owner_tools
    assert "doc_read" in owner_tools
    assert "doc_query" in owner_tools


def test_engineer_sees_find():
    engineer_tools = {t.name for t in tools_for_role("engineer")}
    assert "find" in engineer_tools
    assert "ticket_create" in engineer_tools


def test_all_role_bundle_names_resolve():
    for role, names in ROLE_BUNDLES.items():
        for n in names:
            assert n in ALL_TOOLS, f"{role} lists unknown tool {n!r}"


# ----------------------------------------------------------------------------- scripted flow


def test_full_flow(raw_client, board):
    owner_id = register(raw_client, "owner", "owner1")
    architect_id = register(raw_client, "architect", "arch1")
    coordinator_id = register(raw_client, "coordinator", "coord1")
    engineer_id = register(raw_client, "engineer", "eng1")
    reviewer_id = register(raw_client, "reviewer", "rev1")

    owner_client = make_client(raw_client, owner_id)
    architect_client = make_client(raw_client, architect_id)
    coordinator_client = make_client(raw_client, coordinator_id)
    engineer_client = make_client(raw_client, engineer_id)
    reviewer_client = make_client(raw_client, reviewer_id)

    def use(client):
        set_client(client)

    # owner: ticket_create epic
    use(owner_client)
    resp = ALL_TOOLS["ticket_create"].handler(
        ALL_TOOLS["ticket_create"].args_model(kind="epic", work_type="feature", title="Build the thing"))
    assert resp["ok"], resp
    epic_id = resp["value"]["id"]

    # architect: doc_create design + criterion_create + ticket_update designed
    use(architect_client)
    doc_resp = ALL_TOOLS["doc_create"].handler(
        ALL_TOOLS["doc_create"].args_model(doc_type="design", title="Design", body_md="the plan", scope=epic_id))
    assert doc_resp["ok"], doc_resp
    design_id = doc_resp["value"]["id"]

    upd = ALL_TOOLS["ticket_update"].handler(
        ALL_TOOLS["ticket_update"].args_model(id=epic_id, design_ref=design_id))
    assert upd["ok"], upd

    crit_resp = ALL_TOOLS["criterion_create"].handler(
        ALL_TOOLS["criterion_create"].args_model(ticket_id=epic_id, text="it works", check="verdict",
                                                 checked_by="qa"))
    assert crit_resp["ok"], crit_resp

    designed = ALL_TOOLS["ticket_update"].handler(
        ALL_TOOLS["ticket_update"].args_model(id=epic_id, status="designed"))
    assert designed["ok"], designed
    assert designed["value"]["status"] == "designed"

    # owner: sign-off
    use(owner_client)
    signed = ALL_TOOLS["ticket_update"].handler(
        ALL_TOOLS["ticket_update"].args_model(id=epic_id, status="signed_off"))
    assert signed["ok"], signed
    assert signed["value"]["status"] == "signed_off"

    # coordinator: board shows it, then marks it ready
    use(coordinator_client)
    board_resp = ALL_TOOLS["board"].handler(ALL_TOOLS["board"].args_model(epic_id=epic_id))
    assert board_resp["ok"], board_resp
    assert board_resp["value"]["epic"]["id"] == epic_id

    ready = ALL_TOOLS["ticket_update"].handler(
        ALL_TOOLS["ticket_update"].args_model(id=epic_id, status="ready"))
    assert ready["ok"], ready
    assert ready["value"]["status"] == "ready"

    # engineer: report + criterion_update evidence + in_review
    use(engineer_client)
    assign = ALL_TOOLS["ticket_update"].handler(
        ALL_TOOLS["ticket_update"].args_model(id=epic_id, assignee=engineer_id, status="in_progress"))
    assert assign["ok"], assign

    report_resp = ALL_TOOLS["doc_create"].handler(
        ALL_TOOLS["doc_create"].args_model(doc_type="report", title="Evidence", body_md="ran the checks",
                                           scope=epic_id))
    assert report_resp["ok"], report_resp
    report_id = report_resp["value"]["id"]

    crit_id = crit_resp["value"]["id"]
    ev = ALL_TOOLS["criterion_update"].handler(
        ALL_TOOLS["criterion_update"].args_model(id=crit_id, evidence_ref=report_id))
    assert ev["ok"], ev

    in_review = ALL_TOOLS["ticket_update"].handler(
        ALL_TOOLS["ticket_update"].args_model(id=epic_id, status="in_review"))
    assert in_review["ok"], in_review

    # reviewer: verdict + done  (checked_by was qa; use owner to close as owner is also a checker)
    use(reviewer_client)
    bad_verdict = ALL_TOOLS["criterion_update"].handler(
        ALL_TOOLS["criterion_update"].args_model(id=crit_id, verdict="pass"))
    assert bad_verdict["ok"] is False  # checked_by=qa, reviewer cannot verdict it
    assert bad_verdict["error"]["code"] == "scope"

    qa_id = register(raw_client, "qa", "qa1")
    qa_client = make_client(raw_client, qa_id)
    use(qa_client)
    verdict = ALL_TOOLS["criterion_update"].handler(
        ALL_TOOLS["criterion_update"].args_model(id=crit_id, verdict="pass"))
    assert verdict["ok"], verdict

    done = ALL_TOOLS["ticket_update"].handler(
        ALL_TOOLS["ticket_update"].args_model(id=epic_id, status="done"))
    assert done["ok"], done
    assert done["value"]["status"] == "done"

    # close
    use(coordinator_client)
    close_resp = ALL_TOOLS["close"].handler(ALL_TOOLS["close"].args_model(epic_id=epic_id))
    assert close_resp["ok"], close_resp
    assert "disarm" in close_resp["value"]


def test_error_envelope_passes_through(raw_client):
    owner_id = register(raw_client, "owner", "owner2")
    use_client = make_client(raw_client, owner_id)
    set_client(use_client)
    resp = ALL_TOOLS["ticket_read"].handler(ALL_TOOLS["ticket_read"].args_model(id="nope-1"))
    assert resp["ok"] is False
    assert resp["error"]["code"] == "not_found"
    assert "hint" in resp


def test_pool_unavailable_when_adapter_missing(raw_client, monkeypatch):
    monkeypatch.setenv("EDP_POOL_URL", "http://127.0.0.1:1")  # nothing listens here
    owner_id = register(raw_client, "owner", "owner3")
    set_client(make_client(raw_client, owner_id))
    resp = ALL_TOOLS["spawn"].handler(
        ALL_TOOLS["spawn"].args_model(role="engineer", participant_id="eng-x"))
    assert resp["ok"] is False
    assert resp["error"]["code"] == "unavailable"


def test_consult_unavailable(raw_client, monkeypatch):
    import edp8.consult as consult_mod

    def fake_consult(purpose, question, context="", files=None, timeout_s=600, write_dir=None):
        return {"ok": False, "error": {"code": "unavailable", "message": "could not launch 'codex': not found"},
                "hint": "check EDP8_CODEX_BIN and that `codex` is on PATH"}

    monkeypatch.setattr(consult_mod, "consult", fake_consult)

    owner_id = register(raw_client, "owner", "owner4")
    set_client(make_client(raw_client, owner_id))
    resp = ALL_TOOLS["consult"].handler(
        ALL_TOOLS["consult"].args_model(question="thoughts?"))
    assert resp["ok"] is False
    assert resp["error"]["code"] == "unavailable"


def test_spawn_with_ticket_id_registers_and_assigns(raw_client, monkeypatch):
    import edp8.bundles as bundles_mod

    def fake_pool_call(fn_name, kwargs):
        assert fn_name == "spawn"
        return {"ok": True, "value": {"session_id": "sess-1"}}

    monkeypatch.setattr(bundles_mod, "_pool_call", fake_pool_call)

    coordinator_id = register(raw_client, "coordinator", "coord-spawn")
    architect_id = register(raw_client, "architect", "arch-spawn")

    coordinator_client = make_client(raw_client, coordinator_id)
    architect_client = make_client(raw_client, architect_id)

    set_client(coordinator_client)
    epic_resp = ALL_TOOLS["ticket_create"].handler(
        ALL_TOOLS["ticket_create"].args_model(kind="epic", work_type="feature", title="Spawn target epic"))
    assert epic_resp["ok"], epic_resp
    epic_id = epic_resp["value"]["id"]

    set_client(architect_client)
    story_resp = ALL_TOOLS["ticket_create"].handler(
        ALL_TOOLS["ticket_create"].args_model(kind="story", work_type="feature", title="Spawn target story",
                                              parent_id=epic_id))
    assert story_resp["ok"], story_resp
    story_id = story_resp["value"]["id"]

    set_client(coordinator_client)
    spawn_resp = ALL_TOOLS["spawn"].handler(
        ALL_TOOLS["spawn"].args_model(role="engineer", ticket_id=story_id))
    assert spawn_resp["ok"], spawn_resp
    expected_pid = f"engineer.{story_id}"
    assert spawn_resp["value"]["participant_id"] == expected_pid

    got = coordinator_client.participant_get(expected_pid)
    assert got["ok"], got

    ticket_after = coordinator_client.ticket_read(story_id)
    assert ticket_after["ok"], ticket_after
    assert ticket_after["value"]["assignee"] == expected_pid


def test_spawn_without_ticket_or_participant_id_is_schema_error(raw_client):
    coordinator_id = register(raw_client, "coordinator", "coord-spawn2")
    set_client(make_client(raw_client, coordinator_id))
    resp = ALL_TOOLS["spawn"].handler(ALL_TOOLS["spawn"].args_model(role="engineer"))
    assert resp["ok"] is False
    assert resp["error"]["code"] == "schema"


def test_consult_posts_answer_to_thread(raw_client, monkeypatch):
    import edp8.consult as consult_mod

    def fake_consult(purpose, question, context="", files=None, timeout_s=600, write_dir=None):
        return {"ok": True,
                "value": {"answer": "looks solid, one gap: no timeout test", "model": "gpt-5.6-sol",
                          "elapsed_s": 1.23, "run_id": "fake-run", "log": "C:/tmp/fake-run.jsonl"},
                "hint": ""}

    monkeypatch.setattr(consult_mod, "consult", fake_consult)

    owner_id = register(raw_client, "owner", "owner5")
    client = make_client(raw_client, owner_id)
    set_client(client)
    resp = ALL_TOOLS["ticket_create"].handler(
        ALL_TOOLS["ticket_create"].args_model(kind="epic", work_type="feature", title="Consult target"))
    assert resp["ok"], resp
    ticket_id = resp["value"]["id"]

    consult_resp = ALL_TOOLS["consult"].handler(
        ALL_TOOLS["consult"].args_model(question="thoughts?", purpose="adversary", ticket_id=ticket_id))
    assert consult_resp["ok"], consult_resp
    assert consult_resp["value"]["answer"] == "looks solid, one gap: no timeout test"

    thread = client.message_query(ticket_id=ticket_id)
    assert thread["ok"], thread
    texts = [m["text"] for m in thread["value"]]
    assert any("consultant[adversary]:" in t and "looks solid" in t for t in texts)


def test_owner_bundle_can_kick_off():
    from edp8.bundles import ROLE_BUNDLES
    assert "ticket_create" in ROLE_BUNDLES["owner"], "owner must originate epics (pain 2026-08-24)"
    assert "spawn" in ROLE_BUNDLES["owner"], "owner must be able to start the coordinator"
