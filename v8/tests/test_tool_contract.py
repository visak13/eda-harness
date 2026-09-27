"""S23 tool standards (t-0f43dff835, report-e517e9e87e): the contract every MCP tool keeps.

For EVERY tool: the description names its linked objects (and their skills), each enum arg with a pointer to
describe('enums'); every required field is described; the args model forbids extra fields; every linked
object has a describe() entry; every list tool is bounded (PageArgs: limit/cursor/verbose) and returns
next_cursor. Then the behaviours the audit found missing: the nearest-arg error, the pain tool, idempotent
creates, artifact_read content, and a context_delta cursor key that survives a board restart.
"""

from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient

from edp8 import broker_adapter, tool_idem
from edp8.board import Board
from edp8.bundles import ALL_TOOLS, PageArgs, _object_index, invoke, set_client
from edp8.client import BoardClient
from edp8.service import create_app
from edp8.store import Store
from edp8.tool_contracts import OBJECT_SKILLS, tool_objects

LIST_TOOLS = ("ticket_query", "doc_query", "session_query", "link_query", "participants", "message_query",
              "events_query")


# ----------------------------------------------------------------------------- static contract, every tool


@pytest.mark.parametrize("name", sorted(ALL_TOOLS))
def test_description_names_objects_skills_and_enums(name):
    tool = ALL_TOOLS[name]
    desc = tool.description
    objs = tool_objects(name)
    assert objs, f"{name}: no linked object in tool_contracts.TOOL_OBJECTS"
    assert "Objects: " + ", ".join(objs) in desc, f"{name}: objects clause missing"
    for o in objs:
        for skill in OBJECT_SKILLS.get(o, ()):
            assert skill in desc, f"{name}: skill {skill} for {o} not named"
    props = tool.input_schema.get("properties", {})
    enum_args = [f for f, node in props.items() if node.get("enum")]
    if enum_args:
        assert "describe('enums')" in desc, name
        for f in enum_args:
            assert f in desc.split("Enums: ", 1)[-1], f"{name}: enum arg {f} not named"


@pytest.mark.parametrize("name", sorted(ALL_TOOLS))
def test_required_fields_are_described(name):
    tool = ALL_TOOLS[name]
    props = tool.input_schema.get("properties", {})
    for f in tool.input_schema.get("required", []):
        assert props[f].get("description"), f"{name}.{f}: required but undescribed"


@pytest.mark.parametrize("name", sorted(ALL_TOOLS))
def test_args_forbid_extra(name):
    assert ALL_TOOLS[name].args_model.model_config.get("extra") == "forbid", name


@pytest.mark.parametrize("name", sorted(ALL_TOOLS))
def test_every_linked_object_has_a_describe_entry(name):
    index = set(_object_index())
    for o in tool_objects(name):
        assert o in index, f"{name}: object {o!r} has no describe() entry"


@pytest.mark.parametrize("name", LIST_TOOLS)
def test_list_tools_are_bounded(name):
    tool = ALL_TOOLS[name]
    assert issubclass(tool.args_model, PageArgs), name
    assert {"limit", "cursor", "verbose"} <= set(tool.input_schema["properties"]), name
    assert "next_cursor" in tool.description, name


def test_describe_covers_gate_topic_workflow_and_the_new_objects():
    index = set(_object_index())
    assert {"gate", "topic", "workflow", "pain", "service", "teammate", "cost"} <= index


# ----------------------------------------------------------------------------- behaviour on a board


@pytest.fixture
def rig(monkeypatch, tmp_path):
    monkeypatch.setattr(broker_adapter, "publish", lambda *a, **k: True)
    monkeypatch.setenv("EDP8_DATA", str(tmp_path))
    monkeypatch.setenv("EDP8_UPLOAD_SWEEP", "0")
    monkeypatch.setenv("EDP8_PAIN_FILE", str(tmp_path / "pain-points.jsonl"))
    tool_idem.reset()
    raw = TestClient(create_app(Board(Store(":memory:")), admin_token="t"))
    admin = BoardClient(admin_token="t", client=raw)

    def seat(role: str, handle: str, type_: str = "agent") -> BoardClient:
        r = admin._request("POST", "/v1/participants", admin=True,
                           json={"type": type_, "role": role, "handle": handle, "id": handle})
        assert r["ok"], r
        return BoardClient(participant=handle, admin_token="t", client=raw)

    owner = seat("owner", "owner", "human")
    epic = owner._request("POST", "/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "E"})
    return {"raw": raw, "seat": seat, "owner": owner, "epic": epic["value"]["id"]}


def call(client: BoardClient, name: str, **kw):
    set_client(client)
    return invoke(ALL_TOOLS[name], kw, seat=client.participant)


def test_unknown_arg_names_the_nearest_field(rig):
    out = call(rig["owner"], "ticket_read", ticket_idd=rig["epic"])
    assert not out["ok"]
    assert "ticket_idd" in out["error"]["message"] and "ticket_id" in out["error"]["message"]


def test_pain_file_query_read_resolve(rig):
    eng = rig["seat"]("engineer", "engineer.t-x")
    miss = call(eng, "pain", action="file", area="tools", symptom="s", expected="e", evidence="ev")
    assert not miss["ok"] and miss["error"]["field"] == "severity"
    filed = call(eng, "pain", action="file", severity="low", area="tools", symptom="ticket_query too big",
                 expected="bounded", evidence="audit")
    assert filed["ok"], filed
    pid = filed["value"]["id"]
    rows = call(eng, "pain", action="query", q="too big")["value"]["items"]
    assert [r["id"] for r in rows] == [pid]
    assert call(eng, "pain", action="read", id=pid)["value"]["status"] == "open"
    refused = call(eng, "pain", action="resolve", id=pid, status="fixed")
    assert not refused["ok"]
    doc = rig["seat"]("doctor", "doctor")
    assert call(doc, "pain", action="resolve", id=pid, status="fixed")["ok"]
    assert call(eng, "pain", action="query", q="too big")["value"]["items"] == []


def test_create_is_idempotent_by_key_and_by_same_input(rig):
    o = rig["owner"]
    a = call(o, "ticket_create", kind="epic", work_type="feature", title="idem", idempotency_key="k1")
    b = call(o, "ticket_create", kind="epic", work_type="feature", title="idem", idempotency_key="k1")
    assert a["ok"] and b["ok"] and a["value"]["id"] == b["value"]["id"]
    assert b["value"].get("replay") is True
    clash = call(o, "ticket_create", kind="epic", work_type="feature", title="other", idempotency_key="k1")
    assert not clash["ok"] and clash["error"]["code"] == "conflict"
    c = call(o, "ticket_create", kind="epic", work_type="feature", title="auto")
    d = call(o, "ticket_create", kind="epic", work_type="feature", title="auto")
    assert c["value"]["id"] == d["value"]["id"]


def _upload(rig, data: bytes, name: str, ctype: str) -> str:
    r = rig["raw"].post("/v1/artifacts/upload", files={"file": (name, io.BytesIO(data), ctype)},
                        data={"note": "n"}, headers={"X-Participant": "owner"}).json()
    assert r["ok"], r
    return r["value"]["id"]


def test_artifact_read_returns_text_inline_with_continuation(rig):
    body = ("line of text\n" * 1000).encode()
    aid = _upload(rig, body, "notes.txt", "text/plain")
    first = call(rig["owner"], "artifact_read", id=aid)
    c = first["value"]["content"]
    assert c["kind"] == "text" and c["text"] and c["next_offset"] == len(c["text"].encode())
    got, off = c["text"], c["next_offset"]
    while off is not None:
        nxt = call(rig["owner"], "artifact_read", id=aid, offset=off)["value"]["content"]
        got += nxt["text"]
        off = nxt.get("next_offset")
    assert got.encode() == body


def test_artifact_read_image_becomes_an_image_block(rig):
    from edp8.mcp_server import _as_content
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    aid = _upload(rig, png, "shot.png", "image/png")
    out = call(rig["owner"], "artifact_read", id=aid)
    assert out["value"]["content"]["kind"] == "image"
    res = _as_content(out)
    kinds = [b.type for b in res.content]
    assert kinds == ["text", "image"]
    assert "base64" not in res.content[0].text and res.content[1].mime_type == "image/png"
    assert json.loads(res.structured_content["result"])["value"]["content"]["bytes"] == len(png)


def test_context_cursor_key_survives_restart(tmp_path):
    from edp8.context_delta import cursor_key
    db = tmp_path / "edp8.db"
    assert cursor_key(db) == cursor_key(db)
    assert cursor_key(":memory:") != cursor_key(":memory:")
