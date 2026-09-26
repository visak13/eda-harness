"""S4 (s-733de6e29f, design-e963c656f5 §4.11, R5): harness choice and the Fable adversary fallback.

Criterion c-26d7518deb: with codex not selected the adversary resolves to Fable (claude-fable-5-1), and
the board refuses an adversary spawn on Fable — REST spawn, the MCP spawn tool (via seat-token) and the
auto-pairing path — until a human has recorded the risk acknowledgement. Every models.json and board DB
here is a tmp_path file (EDP8_HOME / EDP_AGENT_HOME monkeypatched), never the fleet's.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

from edp8 import harness, pool_adapter, seat_choice
from edp8.board import Board
from edp8.bundles import ALL_TOOLS, set_client
from edp8.client import BoardClient
from edp8.schemas import Role, TicketKind, WorkType
from edp8.service import create_app
from edp8.store import Store

ADMIN = {"X-Admin": "t"}
OWNER = {"X-Participant": "owner"}
TABLE = {"architect": ["claude-fable-5-1", "gpt-6-astra"], "engineer": ["claude-opus-5-5", "gpt-6-sol"],
         "qa": ["claude-fable-5-1", "gpt-6-astra"], "adversary": ["gpt-6-astra"], "sme": ["claude-opus-5-5"]}
SEATS = {"astra": {"model": "openai-codex/gpt-6-astra", "harness": "pi"},
         "astra-codex": {"model": "gpt-6-astra", "harness": "codex"}}


def _home(tmp_path, monkeypatch, harnesses=None):
    from edp8.model_catalog import migrate
    reg = migrate({"seats": SEATS, "role_models": TABLE})
    if harnesses is not None:
        monkeypatch.setenv("EDP_HARNESSES", ",".join(harnesses))
    (tmp_path / "models.json").write_text(json.dumps(reg), encoding="utf-8")
    monkeypatch.setenv("EDP8_HOME", str(tmp_path))
    monkeypatch.setenv("EDP_AGENT_HOME", str(tmp_path))  # models.json resolves in the agent home (S1)
    return tmp_path


# ----------------------------------------------------------------------------- pure selection

def test_harness_of_names_each_harness():
    assert harness.harness_of("gpt-6-astra") is None and harness.harness_of("codex/gpt-6-sol") is None
    assert harness.harness_of("openai-codex/gpt-6-astra") is None and harness.harness_of("openai/gpt-6") is None
    assert harness.harness_of("claude-fable-5-1") is None
    assert harness.harness_of("my-model", {"my-model": {"harness": "pi"}}) == "pi"
    assert harness.harness_of("astra", SEATS) == "pi" and harness.harness_of("astra-codex", SEATS) == "codex"


def test_absent_or_invalid_selection_is_every_harness(monkeypatch):
    assert harness.selected({}) == harness.HARNESSES
    assert harness.selected({"harnesses": "codex"}) == harness.HARNESSES
    assert harness.validate(["pi"]) and harness.selected({"harnesses": ["pi"]}) == harness.HARNESSES
    monkeypatch.setenv("EDP_HARNESSES", "claude,pi")
    assert harness.selected({"harnesses": ["codex"]}) == ("claude", "pi")


def test_all_harnesses_keep_todays_catalog(tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch)
    assert seat_choice.catalog(home) == TABLE


def test_without_codex_the_adversary_resolves_to_fable_and_gpt_ids_drop(tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch, ["claude", "pi"])
    cat = seat_choice.catalog(home)
    assert cat["adversary"] == [harness.FABLE]
    assert cat["engineer"] == ["claude-opus-5-5"] and "gpt-6-astra" not in cat["qa"]
    assert seat_choice.resolve(None, None, [], home, role="adversary").model == harness.FABLE
    assert seat_choice.unknown_model("adversary", "gpt-6-astra", home)  # a codex id is no longer offered


def test_codex_only_keeps_gpt_ids_and_the_codex_adversary(tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch, ["codex"])
    cat = seat_choice.catalog(home)
    assert cat["adversary"] == ["gpt-6-astra"] and cat["engineer"] == ["gpt-6-sol"] and "sme" not in cat


# ----------------------------------------------------------------------------- the acknowledgement gate

@pytest.fixture
def rig(tmp_path, monkeypatch):
    (tmp_path / "home").mkdir()
    (tmp_path / "db").mkdir()
    home = _home(tmp_path / "home", monkeypatch, ["claude", "pi"])
    board = Board(Store(str(tmp_path / "db" / "edp8.db")))
    client = TestClient(create_app(board, admin_token="t"))
    for pid, role, typ in (("owner", "owner", "human"), ("arch", "architect", "agent")):
        r = client.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid}, headers=ADMIN)
        assert r.json()["ok"], r.text
    r = client.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "E"}, headers=OWNER)
    calls: list[dict] = []

    def fake(role, participant_id, **kw):
        calls.append({"role": role, "participant_id": participant_id, **kw})
        return {"ok": True, "value": {"session_id": f"sess-{len(calls)}"}, "hint": ""}

    monkeypatch.setattr(pool_adapter, "spawn", fake)
    monkeypatch.setattr(pool_adapter, "reachable", lambda: True)
    return {"board": board, "client": client, "epic": r.json()["value"]["id"], "calls": calls, "home": home,
            "ack": tmp_path / "db" / harness.ACK_FILE}


def _spawn_adversary(client, epic):
    return client.post("/v1/sessions/spawn", json={"role": "adversary", "participant_id": f"adversary.{epic}",
                                                   "ticket_id": epic}, headers=OWNER)


def test_rest_spawn_refuses_fable_adversary_until_a_human_acknowledges(rig):
    client, epic, calls = rig["client"], rig["epic"], rig["calls"]
    state = client.get("/v1/harness", headers=OWNER).json()["value"]
    assert state["harnesses"] == ["claude", "pi"] and state["adversary_model"] == harness.FABLE
    assert state["fable_ack"] is None and "declined or softened" in state["notice"]
    r = _spawn_adversary(client, epic)
    assert not r.json()["ok"] and "acknowledges the risk" in r.text and calls == []
    # an agent cannot acknowledge for the human
    r = client.post("/v1/harness/fable-ack", headers={"X-Participant": "arch"})
    assert not r.json()["ok"] and not rig["ack"].exists()
    r = client.post("/v1/harness/fable-ack", headers=OWNER)
    assert r.json()["ok"], r.text
    assert json.loads(rig["ack"].read_text(encoding="utf-8"))["by"] == "owner"
    r = _spawn_adversary(client, epic)
    assert r.json()["ok"], r.text
    assert calls[-1]["model"] == harness.FABLE
    assert client.get("/v1/harness", headers=OWNER).json()["value"]["fable_ack"]["by"] == "owner"


def test_the_gate_is_only_for_an_adversary_on_fable(rig):
    client, epic, calls = rig["client"], rig["epic"], rig["calls"]
    r = client.post("/v1/sessions/spawn", json={"role": "qa", "participant_id": f"qa.{epic}", "ticket_id": epic},
                    headers=OWNER)
    assert r.json()["ok"] and calls[-1]["model"] == harness.FABLE  # qa on Fable is not gated


def test_mcp_spawn_tool_is_refused_through_seat_token(rig, monkeypatch):
    import edp8.bundles as bundles_mod
    client, epic = rig["client"], rig["epic"]
    seen: list[dict] = []
    monkeypatch.setattr(bundles_mod, "_pool_call", lambda fn, kw: seen.append(kw) or {"ok": True, "value": {}})
    set_client(BoardClient(participant="owner", admin_token="t", client=client))
    args = ALL_TOOLS["spawn"].args_model(role="adversary", ticket_id=epic, assign=False)
    out = ALL_TOOLS["spawn"].handler(args)
    assert not out["ok"] and "acknowledges the risk" in json.dumps(out) and seen == []
    client.post("/v1/harness/fable-ack", headers=OWNER)
    out = ALL_TOOLS["spawn"].handler(args)
    assert out["ok"], out
    assert seen[-1]["model"] == harness.FABLE


def test_auto_pairing_holds_a_fable_adversary_until_acknowledged(tmp_path, monkeypatch):
    (tmp_path / "home").mkdir()
    _home(tmp_path / "home", monkeypatch, ["claude"])

    class StubPool:
        calls: list[dict] = []

        def spawn(self, role, participant_id, **kw):
            self.calls.append({"role": role, **kw})
            return {"ok": True}

    pool = StubPool()
    board = Board(Store(str(tmp_path / "edp8.db")), pool=pool, free_mb=lambda: 4096)
    owner = board.participant_create("human", Role.owner, "owner")
    epic = board.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    assert board._spawn_seat("adversary", f"adversary.{epic.id}", epic.id) is False and pool.calls == []
    harness.write_ack(tmp_path / harness.ACK_FILE, "owner")
    assert board._spawn_seat("adversary", f"adversary.{epic.id}", epic.id) is True
    assert pool.calls[-1]["model"] == harness.FABLE


def test_codex_selected_never_gates(rig, monkeypatch):
    _home(rig["home"], monkeypatch, ["claude", "codex"])
    r = _spawn_adversary(rig["client"], rig["epic"])
    assert r.json()["ok"] and rig["calls"][-1]["model"] == "gpt-6-astra"


def test_pi_seat_guide_ships():
    from pathlib import Path
    guide = (Path(__file__).resolve().parents[1] / "guides" / "pi-seat.md").read_text(encoding="utf-8")
    for must in ("harness", "/login", "models.json", "EDP_PI_ROLES", "claude-fable-5-1"):
        assert must in guide
