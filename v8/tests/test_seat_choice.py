"""epic-6a8a6020fd seat-choice (owner m-2d7ef9243d / m-3238155d2e): the epic carries the seat MODEL +
EFFORT every spawn on it inherits — stored as `seat-model:` / `seat-effort:` tags on the epic ticket
(edp8/seat_choice.py), read by the `spawn` MCP tool, POST /v1/sessions/spawn and the board's
auto-pairing; Claude effort stays capped at medium, Pi (astra) may run high."""
from __future__ import annotations

import json
import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

from edp8 import pool_adapter, seat_choice
from edp8.board import Board
from edp8.bundles import ALL_TOOLS, set_client
from edp8.client import BoardClient
from edp8.schemas import Role, TicketKind, WorkType
from edp8.service import create_app
from edp8.store import Store

ADMIN = {"X-Admin": "t"}
OWNER = {"X-Participant": "owner"}


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A models.json with the astra Pi seat, as the v8 agent home."""
    (tmp_path / "models.json").write_text(json.dumps({
        "seats": {"builder": {"model": "claude-opus-4-8", "effort": "medium"},
                  "astra": {"model": "openai-codex/gpt-6-astra", "effort": "medium", "harness": "pi",
                            "thinking": "medium", "context_window": 272000, "auto_compact": 200000}},
        "roles": {"engineer": "builder"}, "roles_openai": {"engineer": "astra"}}), encoding="utf-8")
    monkeypatch.setenv("EDP8_HOME", str(tmp_path))
    return tmp_path


# ----------------------------------------------------------------------------- pure resolution

def test_tags_roundtrip():
    tags = seat_choice.tags_for_choice("astra", "high")
    assert tags == ["seat-model:astra", "seat-effort:high"]
    assert seat_choice.choice_from_tags(["review_required", *tags]) == ("astra", "high")
    assert seat_choice.choice_from_tags([]) == (None, None)
    assert seat_choice.tags_for_choice(None, None) == []


def test_resolve_inherits_the_epic_choice_unless_the_spawn_names_its_own(home):
    tags = ["seat-model:astra", "seat-effort:high"]
    c = seat_choice.resolve(None, None, tags, home)
    assert (c.model, c.effort, c.note) == ("astra", "high", None)  # a Pi seat may run high
    c = seat_choice.resolve("builder", None, tags, home)  # explicit model wins, effort inherited…
    assert (c.model, c.effort) == ("builder", "medium")  # …and is capped: builder is a Claude seat
    assert "capped" in (c.note or "")
    c = seat_choice.resolve(None, "low", tags, home)  # explicit effort wins
    assert (c.model, c.effort) == ("astra", "low")
    c = seat_choice.resolve("openai/gpt-6-astra-fast", "high", [], home)  # an openai id is a Pi seat
    assert (c.model, c.effort) == ("openai/gpt-6-astra-fast", "high")


def test_resolve_claude_is_the_no_model_default_and_high_is_capped(home):
    c = seat_choice.resolve(None, None, ["seat-model:claude", "seat-effort:high"], home)
    assert c.model is None and c.effort == "medium" and "2026-08-04" in c.note
    c = seat_choice.resolve(None, None, [], home)  # no choice at all = pool defaults
    assert (c.model, c.effort, c.note) == (None, None, None)
    c = seat_choice.resolve(None, None, ["seat-effort:xhigh"], home)  # junk effort is dropped
    assert c.effort is None


def test_is_pi_seat_never_raises(tmp_path):
    assert not seat_choice.is_pi_seat("astra", tmp_path)  # no models.json → False, no exception
    (tmp_path / "models.json").write_text("{not json", encoding="utf-8")
    assert not seat_choice.is_pi_seat("astra", tmp_path)
    assert seat_choice.is_pi_seat("openai-codex/gpt-6-astra", None)


# ----------------------------------------------------------------------------- board rig

@pytest.fixture
def rig(home):
    board = Board(Store(":memory:"))
    app = create_app(board, admin_token="t")
    client = TestClient(app)
    for pid, role, typ in (("owner", "owner", "human"), ("arch", "architect", "agent")):
        r = client.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid}, headers=ADMIN)
        assert r.json()["ok"], r.text
    return {"board": board, "client": client}


def _epic(client, tags):
    r = client.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "E", "tags": tags},
                    headers=OWNER)
    assert r.json()["ok"], r.text
    return r.json()["value"]["id"]


def _story(client, epic_id):
    r = client.post("/v1/tickets", json={"kind": "story", "work_type": "chore", "title": "S", "parent_id": epic_id},
                    headers={"X-Participant": "arch"})
    assert r.json()["ok"], r.text
    return r.json()["value"]["id"]


def _stub_pool(monkeypatch):
    calls: list[dict] = []

    def fake(role, participant_id, **kw):
        calls.append({"role": role, "participant_id": participant_id, **kw})
        return {"ok": True, "value": {"session_id": f"sess-{len(calls)}"}, "hint": ""}

    monkeypatch.setattr(pool_adapter, "spawn", fake)
    return calls


def test_epic_creation_records_the_choice_as_tags_and_the_page_shows_it(rig):
    client = rig["client"]
    epic = _epic(client, ["seat-model:astra", "seat-effort:high"])
    got = client.get(f"/v1/tickets/{epic}", headers=OWNER).json()["value"]
    assert set(got["tags"]) >= {"seat-model:astra", "seat-effort:high"}
    page = client.get(f"/v1/epics/{epic}/page", headers=OWNER).json()["value"]
    assert page["seat_choice"] == {"model": "astra", "effort": "high", "note": None}
    assert "seat-model:astra" in page["tags"]
    # a Claude epic asking high is shown capped, so the label never promises what the seat won't do
    epic2 = _epic(client, ["seat-model:claude", "seat-effort:high"])
    page2 = client.get(f"/v1/epics/{epic2}/page", headers=OWNER).json()["value"]
    assert page2["seat_choice"]["model"] is None and page2["seat_choice"]["effort"] == "medium"
    assert "capped" in page2["seat_choice"]["note"]


def test_rest_spawn_inherits_the_epic_choice_for_a_story_seat(rig, monkeypatch):
    client = rig["client"]
    calls = _stub_pool(monkeypatch)
    epic = _epic(client, ["seat-model:astra", "seat-effort:high"])
    story = _story(client, epic)
    r = client.post("/v1/sessions/spawn", json={"role": "engineer", "participant_id": f"engineer.{story}",
                                                "ticket_id": story}, headers=OWNER)
    assert r.status_code == 200, r.text
    assert calls[-1]["model"] == "astra" and calls[-1]["effort"] == "high"
    assert r.json()["value"]["seat_choice"] == {"model": "astra", "effort": "high", "note": None}
    # every role of the epic inherits — the architect on the epic itself too
    r = client.post("/v1/sessions/spawn", json={"role": "architect", "participant_id": f"architect.{epic}",
                                                "ticket_id": epic}, headers=OWNER)
    assert r.status_code == 200 and calls[-1]["model"] == "astra" and calls[-1]["effort"] == "high"
    # the registered seat participant carries the resolved model (provenance)
    p = client.get(f"/v1/participants/architect.{epic}", headers=OWNER).json()["value"]
    assert p.get("model") == "astra"


def test_rest_spawn_body_model_and_effort_override_the_epic(rig, monkeypatch):
    client = rig["client"]
    calls = _stub_pool(monkeypatch)
    epic = _epic(client, ["seat-model:astra", "seat-effort:high"])
    r = client.post("/v1/sessions/spawn", json={"role": "qa", "participant_id": f"qa.{epic}", "ticket_id": epic,
                                                "model": "builder", "effort": "high"}, headers=OWNER)
    assert r.status_code == 200, r.text
    assert calls[-1]["model"] == "builder" and calls[-1]["effort"] == "medium"  # Claude seat: capped
    assert "capped" in r.json()["value"]["seat_choice"]["note"]
    # an epic without a choice, and no body choice: nothing is passed (the pool's role→seat default)
    plain = _epic(client, [])
    r = client.post("/v1/sessions/spawn", json={"role": "qa", "participant_id": f"qa.{plain}", "ticket_id": plain},
                    headers=OWNER)
    assert r.status_code == 200 and calls[-1]["model"] is None and calls[-1]["effort"] is None


def test_mcp_spawn_tool_inherits_the_epic_choice(rig, monkeypatch):
    import edp8.bundles as bundles_mod
    client = rig["client"]
    seen: list[dict] = []

    def fake_pool_call(fn_name, kwargs):
        assert fn_name == "spawn"
        seen.append(dict(kwargs))
        return {"ok": True, "value": {"session_id": "sess-1"}}

    monkeypatch.setattr(bundles_mod, "_pool_call", fake_pool_call)
    set_client(BoardClient(participant="owner", admin_token="t", client=client))
    epic = _epic(client, ["seat-model:astra", "seat-effort:high"])
    story = _story(client, epic)
    out = ALL_TOOLS["spawn"].handler(ALL_TOOLS["spawn"].args_model(role="engineer", ticket_id=story))
    assert out["ok"], out
    assert seen[-1]["model"] == "astra" and seen[-1]["effort"] == "high"
    assert out["value"]["seat_choice"] == {"model": "astra", "effort": "high", "note": None}
    # spawn(model=...) names its own model: the epic's effort still applies, capped for Claude
    out = ALL_TOOLS["spawn"].handler(ALL_TOOLS["spawn"].args_model(role="reviewer", ticket_id=story,
                                                                   model="builder", assign=False))
    assert out["ok"], out
    assert seen[-1]["model"] == "builder" and seen[-1]["effort"] == "medium"
    # a bare participant_id spawn (no ticket) has no epic to inherit from
    out = ALL_TOOLS["spawn"].handler(ALL_TOOLS["spawn"].args_model(role="sme", participant_id="sme.free"))
    assert out["ok"] and seen[-1]["model"] is None and seen[-1]["effort"] is None


def test_auto_pairing_spawn_inherits_the_epic_choice(home):
    class StubPool:
        def __init__(self):
            self.calls: list[dict] = []

        def spawn(self, role, participant_id, **kw):
            self.calls.append({"role": role, "participant_id": participant_id, **kw})
            return {"ok": True, "participant_id": participant_id}

    pool = StubPool()
    board = Board(Store(":memory:"), pool=pool, free_mb=lambda: 4096)
    owner = board.participant_create("human", Role.owner, "owner")
    arch = board.participant_create("agent", Role.architect, "arch")
    epic = board.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="E",
                               tags=["seat-model:astra", "seat-effort:high"])
    story = board.ticket_create(arch, kind=TicketKind.story, work_type=WorkType.feature, title="S", parent_id=epic.id)
    assert board._spawn_seat("reviewer", f"reviewer.{story.id}", story.id) is True
    assert pool.calls[-1]["model"] == "astra" and pool.calls[-1]["effort"] == "high"
    assert board.seat_choice_for(None).as_dict() == {"model": None, "effort": None, "note": None}
    assert board.seat_choice_for("t-missing").model is None
