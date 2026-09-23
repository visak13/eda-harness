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


def test_knowledge_tools_available_to_every_role():
    for role in ROLE_BUNDLES:
        names = {t.name for t in tools_for_role(role)}
        for kt in ("record_decision", "record_claim", "lookup"):
            assert kt in names, f"{role} is missing {kt}"


def test_close_self_stays_last_for_doers():
    # inserting the knowledge tools must not displace the closing triplet's terminal close_self
    for role in ("engineer", "sme", "qa", "adversary"):
        assert ROLE_BUNDLES[role][-1] == "close_self", role


def test_record_and_lookup_through_tools(raw_client, board):
    owner_id = register(raw_client, "owner", "own1")
    register(raw_client, "architect", "arch1")
    engineer_id = register(raw_client, "engineer", "eng1")

    owner_client = make_client(raw_client, owner_id)
    epic = owner_client._request("POST", "/v1/tickets",
                                 json={"kind": "epic", "work_type": "feature", "title": "Epic one"})
    epic_id = epic["value"]["id"]

    eng = make_client(raw_client, engineer_id)
    set_client(eng)
    old = ALL_TOOLS["record_decision"].handler(
        ALL_TOOLS["record_decision"].args_model(scope=epic_id, text="any https host accepted"))
    assert old["ok"], old
    new = ALL_TOOLS["record_decision"].handler(
        ALL_TOOLS["record_decision"].args_model(scope=epic_id, text="allow-list hosts only",
                                                replaces=[old["value"]["id"]]))
    assert new["ok"], new
    refused = ALL_TOOLS["record_decision"].handler(  # binding is architect/owner-only (m-1637080c9a)
        ALL_TOOLS["record_decision"].args_model(scope=epic_id, text="engineer binding", binding=True))
    assert not refused["ok"] and refused["error"]["code"] == "forbidden", refused
    out = ALL_TOOLS["lookup"].handler(ALL_TOOLS["lookup"].args_model(scope=epic_id, question="hosts"))
    assert out["ok"], out
    ids = [r["id"] for r in out["value"]["records"]]
    assert new["value"]["id"] in ids and old["value"]["id"] not in ids
    assert out["value"]["receipt"]["cap"] == {"records": 40, "bytes": 16000}


# ----------------------------------------------------------------------------- scripted flow


def test_full_flow(raw_client, board):
    owner_id = register(raw_client, "owner", "owner1")
    architect_id = register(raw_client, "architect", "arch1")
    coordinator_id = register(raw_client, "coordinator", "coord1")
    engineer_id = register(raw_client, "engineer", "eng1")
    adversary_id = register(raw_client, "adversary", "adv1")

    owner_client = make_client(raw_client, owner_id)
    architect_client = make_client(raw_client, architect_id)
    coordinator_client = make_client(raw_client, coordinator_id)
    engineer_client = make_client(raw_client, engineer_id)
    adversary_client = make_client(raw_client, adversary_id)

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

    # a non-checker (adversary) cannot verdict; qa can (S-ROLES: reviewer retired)
    use(adversary_client)
    bad_verdict = ALL_TOOLS["criterion_update"].handler(
        ALL_TOOLS["criterion_update"].args_model(id=crit_id, verdict="pass"))
    assert bad_verdict["ok"] is False  # checked_by=qa, an adversary cannot verdict it
    assert bad_verdict["error"]["code"] == "scope"

    qa_id = register(raw_client, "qa", "qa1")
    qa_client = make_client(raw_client, qa_id)
    use(qa_client)
    verdict = ALL_TOOLS["criterion_update"].handler(
        ALL_TOOLS["criterion_update"].args_model(id=crit_id, verdict="pass"))
    assert verdict["ok"], verdict
    # §14 ruling m-fb5296bfbd: the MCP path may omit evidence_version, but the board defaults it to
    # the evidence doc's CURRENT version and records it — no verdict signs a doc without a version.
    assert verdict["value"]["evidence_version"] == 1

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

    def fake_consult(purpose, question, context="", files=None, timeout_s=600, write_dir=None, **kw):
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

    set_client(coordinator_client)  # S-ADV finding 2: the tool binds the caller like REST — a retired
    refused = ALL_TOOLS["spawn"].handler(  # coordinator (or any engineer) is refused, the epic's architect spawns
        ALL_TOOLS["spawn"].args_model(role="engineer", ticket_id=story_id))
    assert not refused["ok"] and "pool control plane" in refused["error"]["message"], refused
    set_client(architect_client)
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

    def fake_consult(purpose, question, context="", files=None, timeout_s=600, write_dir=None, **kw):
        return {"ok": True,
                "value": {"answer": "looks solid, one gap: no timeout test", "model": "gpt-6-astra",
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


def test_consult_refuses_every_model_but_astra(monkeypatch, tmp_path):
    """Owner ruling 2026-09-10: gpt-5.6-sol is retired — the bridge refuses it (and any other name,
    including an EDP8_SOL_MODEL override) before codex is launched."""
    import edp8.consult as consult_mod
    launched = []
    monkeypatch.setattr(consult_mod, "_resolve_bin", lambda: launched.append("bin") or "codex")
    monkeypatch.setenv("EDP8_SOL_LOG_DIR", str(tmp_path))
    out = consult_mod.consult("second_opinion", "q", model="gpt-5.6-sol")
    assert out["ok"] is False and out["error"]["code"] == "model_retired"
    monkeypatch.setenv("EDP8_SOL_MODEL", "gpt-5.6-sol")
    out = consult_mod.consult("second_opinion", "q")
    assert out["ok"] is False and out["error"]["code"] == "model_retired"
    assert "gpt-6-astra" in out["error"]["message"]

