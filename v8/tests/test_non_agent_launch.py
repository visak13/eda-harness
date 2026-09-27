"""Owner m-da9a2ae62f (t-cd4712c855): "ensure that human role is non-agent and our app complies with that.
no way anyone can launch the owner role."

Every launch path refuses a person's role (owner, expert, human, or a role a workflow marks human), and a
handle that names one: the board's participant registry, REST spawn / seat-token / resume, the MCP `spawn`
tool, the board's pairing queue (which also starts the Help seat), the workflow editor (validation and Add
role), the MCP proxy (an agent shell never acts as a person) and the codex / pi seat runners. The pool's own
refusal is in edp-pool/tests/test_non_agent_spawn.py and the SPA's in SpawnSeatForm / Design vitest. A
person's own actions still work: the owner answers a gate over REST with their token.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import edp8.bundles as bundles_mod
from edp8 import mcp_server, pool_adapter, workflow as wflow, workflow_design as wd
from edp8.board import Board, BoardError
from edp8.bundles import ALL_TOOLS, set_client
from edp8.client import BoardClient
from edp8.schemas import SpawnRole
from edp8.service import create_app
from edp8.store import Store
from edp_contracts.roles import NON_AGENT_ROLES, RETIRED_ROLES

ADMIN = {"X-Admin": "t"}
PERSON = ("owner", "expert", "human")


def _app(tmp_path, monkeypatch, tokens: dict | None = None):
    if tokens is None:
        monkeypatch.setenv("EDP8_TOKENS", str(tmp_path / "absent-tokens.json"))
    else:
        f = tmp_path / "tokens.json"
        f.write_text(json.dumps(tokens), encoding="utf-8")
        monkeypatch.setenv("EDP8_TOKENS", str(f))
    board = Board(Store(":memory:"))
    return board, TestClient(create_app(board, admin_token="t"))


def _register(c, pid, role, typ="agent", headers=ADMIN):
    r = c.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid}, headers=headers)
    return r


@pytest.fixture
def rig(tmp_path, monkeypatch):
    board, c = _app(tmp_path, monkeypatch)
    assert _register(c, "owner", "owner", "human").json()["ok"]
    oh = {"X-Participant": "owner"}
    epic = c.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "E"}, headers=oh).json()
    epic = epic["value"]["id"]
    arch = f"architect.{epic}"
    assert _register(c, arch, "architect").json()["ok"]
    return {"board": board, "c": c, "oh": oh, "epic": epic, "arch": arch}


def test_the_reserved_set_is_the_built_in_people():
    assert {"owner", "expert", "human"} == set(NON_AGENT_ROLES)
    assert not NON_AGENT_ROLES & {r.value for r in SpawnRole}  # the spawn tool's enum never offers one


# ---------------------------------------------------------------- board registry

def test_board_never_registers_an_agent_under_a_person_role_or_handle(rig):
    board = rig["board"]
    for role in PERSON:
        with pytest.raises(BoardError):
            board.participant_create("agent", role, f"{role}.x", id_=f"{role}.x")
    with pytest.raises(BoardError) as e:  # an agent role cannot hide behind a person's handle either
        board.participant_create("agent", "engineer", "owner.seat", id_="owner.seat")
    assert e.value.code == "scope" and "person" in e.value.message
    # the person themselves registers as a human, as before
    assert board.participant_create("human", "expert", "ada").type == "human"


def test_rest_registry_refuses_an_agent_owner(rig):
    r = _register(rig["c"], "owner.bot", "owner")
    assert r.json()["ok"] is False and "person" in r.text


# ---------------------------------------------------------------- REST: spawn, seat-token, resume

def test_rest_spawn_refuses_every_person_role_and_handle(rig, monkeypatch):
    c, oh, epic = rig["c"], rig["oh"], rig["epic"]
    calls = []
    monkeypatch.setattr(pool_adapter, "reachable", lambda: True)
    monkeypatch.setattr(pool_adapter, "spawn", lambda *a, **k: calls.append((a, k)) or {"ok": True, "value": {}})
    for role in PERSON:
        r = c.post("/v1/sessions/spawn", json={"role": role, "participant_id": f"{role}.{epic}", "ticket_id": epic},
                   headers=oh)
        assert r.status_code == 400 and "person" in r.json()["error"]["message"], (role, r.text)
    r = c.post("/v1/sessions/spawn", json={"role": "engineer", "participant_id": "owner", "ticket_id": epic},
               headers=oh)
    assert r.status_code == 400 and "person" in r.text
    assert calls == []  # the pool was never asked


def test_rest_seat_token_and_resume_refuse_a_person(rig, monkeypatch):
    c, oh, epic = rig["c"], rig["oh"], rig["epic"]
    resumed = []
    monkeypatch.setattr(pool_adapter, "reachable", lambda: True)
    monkeypatch.setattr(pool_adapter, "resume", lambda pid, **k: resumed.append(pid) or {"ok": True, "value": {}})
    r = c.post("/v1/sessions/seat-token", json={"participant_id": "owner", "ticket_id": epic}, headers=oh)
    assert r.status_code == 400 and "person" in r.text
    for pid in ("owner", f"expert.{epic}"):
        r = c.post("/v1/sessions/resume", json={"participant_id": pid, "ticket_id": epic}, headers=oh)
        assert r.status_code == 400 and "person" in r.text, r.text
    assert resumed == []


# ---------------------------------------------------------------- MCP spawn tool

def test_mcp_spawn_tool_refuses_a_person(rig, monkeypatch):
    c, epic, arch = rig["c"], rig["epic"], rig["arch"]
    calls = []
    monkeypatch.setattr(bundles_mod, "_pool_call", lambda fn, kw: calls.append((fn, kw)) or {"ok": True, "value": {}})
    set_client(BoardClient(participant=arch, admin_token="t", client=c))
    args = ALL_TOOLS["spawn"].args_model
    for role in PERSON:
        with pytest.raises(ValidationError):  # the schema does not even offer it
            args(role=role, ticket_id=epic)
    out = ALL_TOOLS["spawn"].handler(args(role="engineer", participant_id="owner.helper", ticket_id=epic))
    assert out["ok"] is False and out["error"]["code"] == "scope" and "person" in out["error"]["message"]
    assert [fn for fn, _ in calls if fn == "spawn"] == []


# ---------------------------------------------------------------- the board's pairing queue (qa, Help)

def test_pairing_spawn_drops_a_person_role_without_calling_the_pool(rig):
    board, epic = rig["board"], rig["epic"]
    spawned = []

    class Pool:
        def spawn(self, role, pid, **kw):
            spawned.append((role, pid))
            return {"ok": True, "value": {}}

    board._pool_adapter = lambda: Pool()
    for role in PERSON:
        assert board._spawn_seat(role, f"{role}.{epic}", epic) is True  # dropped from the queue, never retried
    assert board._spawn_seat("doctor", "owner.help", epic) is True  # a Help seat cannot borrow a person's handle
    assert spawned == [] and board.store.get("participant", "owner.help") is None


# ---------------------------------------------------------------- workflow editor

def _standard() -> dict:
    return wflow.BUILTIN_BUILDERS[wflow.STANDARD_ID]().model_dump(by_alias=True)


def test_validation_refuses_a_person_role_as_an_agent():
    body = _standard()
    owner = next(r for r in body["roles"] if r["id"] == "owner")
    owner["human"] = False
    codes = {p["code"] for p in wflow.validate(body)}
    assert "non_agent_role" in codes
    body = _standard()
    body["roles"].append({**wd.role_from_template("builder", "helper"), "id": "human", "human": False})
    assert "non_agent_role" in {p["code"] for p in wflow.validate(body)}


def test_a_legacy_definition_marking_owner_spawnable_still_spawns_no_owner():
    body = _standard()
    for r in body["roles"]:
        if r["id"] == "owner":
            r.update(spawnable=True, human=False)
    wf = wflow.Workflow(wflow.WorkflowDef.model_validate(body))
    assert not NON_AGENT_ROLES & wf.spawnable and "engineer" in wf.spawnable


def test_add_role_refuses_a_person_or_removed_role_id():
    for rid in sorted(NON_AGENT_ROLES | RETIRED_ROLES):
        with pytest.raises(wflow.WorkflowError):
            wd.role_from_template("checker", rid)
    assert wd.role_from_template("checker", "auditor")["spawnable"] is True


# ---------------------------------------------------------------- MCP proxy: an agent shell never acts as a person

def test_mcp_proxy_refuses_a_person_identity_from_an_agent_shell(monkeypatch):
    monkeypatch.setattr(mcp_server, "_caller_role", lambda url, adm, p, tok: {"owner": "owner", "ada": "expert"}.get(p, "engineer"))
    refused = mcp_server._agent_shell_as_human("http://b", None, "owner", "sess-1", "tok", "whoami")
    assert refused and json.loads(refused)["error"]["code"] == "forbidden"
    assert mcp_server._agent_shell_as_human("http://b", None, "ada", "sess-1", "tok", "inbox")  # by board role
    # a person's own client carries no pool session: unaffected (the board still authorises every call)
    assert mcp_server._agent_shell_as_human("http://b", None, "owner", None, "tok", "whoami") is None
    # a seat is a seat
    assert mcp_server._agent_shell_as_human("http://b", None, "engineer.s-1", "sess-2", "t", "whoami") is None


# ---------------------------------------------------------------- codex / pi seat runners

@pytest.mark.parametrize("mod", ["edp8.codex_seat.run", "edp8.pi_seat.run"])
@pytest.mark.parametrize("env", [{}, {"EDP_ROLE": "owner"}, {"EDP_ROLE": "engineer", "EDP_HANDLE": "owner"}])
def test_seat_runners_refuse_an_unset_or_person_role(mod, env, monkeypatch, capsys):
    import importlib
    m = importlib.import_module(mod)
    monkeypatch.setattr(m.settings, "environ_copy", lambda: dict(env))
    assert m.main([]) == 2
    assert "refused" in capsys.readouterr().err


# ---------------------------------------------------------------- the person's own path still works

def test_the_owner_still_answers_a_gate_over_rest_with_their_token(tmp_path, monkeypatch):
    board, c = _app(tmp_path, monkeypatch, {"owner": "ownersecret", "agents": {}})
    oh = {"X-Participant": "owner", "X-Token": "ownersecret"}
    assert _register(c, "owner", "owner", "human").json()["ok"]
    epic = c.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "E"}, headers=oh).json()
    epic = epic["value"]["id"]
    arch = f"architect.{epic}"
    assert _register(c, arch, "architect").json()["ok"]
    tok = c.post("/v1/sessions/seat-token", json={"participant_id": arch, "ticket_id": epic},
                 headers=oh).json()["value"]["env"]["EDP8_TOKEN"]
    ah = {"X-Participant": arch, "X-Token": tok}
    assert c.patch(f"/v1/tickets/{epic}", json={"assignee": arch}, headers=oh).json()["ok"]
    assert c.post("/v1/criteria", json={"ticket_id": epic, "text": "c", "check": "command"}, headers=ah).json()["ok"]
    d = c.post("/v1/docs", json={"doc_type": "design", "title": "d", "body_md": "x", "scope": epic},
               headers=ah).json()["value"]["id"]
    assert c.patch(f"/v1/tickets/{epic}", json={"design_ref": d}, headers=ah).json()["ok"]
    r = c.post(f"/v1/gates/{epic}/design_signoff/open", json={"note": "please sign"}, headers=ah)
    assert r.json()["ok"], r.text
    r = c.post(f"/v1/gates/{epic}/design_signoff/answer", json={"answer": "signed"}, headers=oh)
    assert r.json()["ok"], r.text
