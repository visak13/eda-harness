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
import re

import pytest
from fastapi.testclient import TestClient

from edp8 import broker_adapter, tool_idem
from edp8.board import Board
from edp8.bundles import ALL_TOOLS, CreateArgs, PageArgs, _object_index, invoke, set_client
from edp8.client import BoardClient
from edp8.service import create_app
from edp8.store import Store
from edp8.tool_contracts import CREATE_EXEMPT, IDEMPOTENT_CREATES, OBJECT_SKILLS, tool_objects

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


# T3 F2: a tool is create-shaped by its name or by an action that makes a record; each is idempotent or exempt
_CREATE_NAME = re.compile(r"_create$|_propose$|^propose_|^record_|_send$|^spawn$|_upload$|_open$|_research$")
_CREATE_ACTIONS = {"create", "file", "duplicate", "add"}


def _create_shaped(name: str) -> bool:
    actions = ALL_TOOLS[name].input_schema.get("properties", {}).get("action", {}).get("enum", [])
    return bool(_CREATE_NAME.search(name)) or bool(_CREATE_ACTIONS & set(actions))


@pytest.mark.parametrize("name", sorted(n for n in ALL_TOOLS if _create_shaped(n)))
def test_every_create_tool_is_idempotent_or_exempt_with_a_reason(name):
    if name in IDEMPOTENT_CREATES:
        assert issubclass(ALL_TOOLS[name].args_model, CreateArgs), f"{name}: listed idempotent, takes no key"
        assert "idempotency_key" in ALL_TOOLS[name].input_schema["properties"], name
    else:
        assert len(CREATE_EXEMPT.get(name, "")) > 20, f"{name}: creates without idempotency and no exempt reason"


def test_idempotent_and_exempt_lists_name_real_tools_once():
    assert set(IDEMPOTENT_CREATES) <= set(ALL_TOOLS) and set(CREATE_EXEMPT) <= set(ALL_TOOLS)
    assert not set(IDEMPOTENT_CREATES) & set(CREATE_EXEMPT)
    keyed = {n for n, t in ALL_TOOLS.items() if issubclass(t.args_model, CreateArgs)}
    assert keyed == set(IDEMPOTENT_CREATES), keyed ^ set(IDEMPOTENT_CREATES)


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


# T3 F2: every idempotent create, keyed: the same key + args replays the first record, a different body under the
# key is a conflict, and the key holds after the tool process forgets it (an MCP-proxy restart) and after a board
# restart on the same DB. topic_propose/propose_fix need a Library topic and a help thread; their client call is
# redirected to a plain POST so the test proves the tool forwards the key, which is all their wiring adds.
def _create_args(rig, name: str, tag: str) -> dict:
    e = rig["epic"]
    return {
        "ticket_create": {"kind": "epic", "work_type": "feature", "title": f"idem {tag}"},
        "doc_create": {"doc_type": "note", "title": f"idem {tag}", "body_md": "b", "scope": e},
        "artifact_create": {"form": "url", "uri": f"https://example.com/{tag}", "ticket_id": e},
        "criterion_create": {"ticket_id": e, "text": f"idem {tag}", "check": "command"},
        "message_send": {"ticket_id": e, "kind": "note", "text": f"idem {tag}"},
        "record_decision": {"scope": e, "text": f"idem {tag}"},
        "record_claim": {"scope": e, "text": f"idem {tag}"},
        "record_lesson": {"domain": "tools", "topic": "idem", "text": f"idem {tag}"},
        "topic_propose": {"topic_id": e, "title": f"idem {tag}", "body_md": "b", "source_url": "https://x"},
        "propose_fix": {"topic_id": e, "action": {"kind": "gate.open"}, "effect": f"idem {tag}"},
    }[name]


def _redirect_topic_calls(monkeypatch, epic: str):
    def post(self, *a, **k):
        return self._request("POST", "/v1/messages", json={"ticket_id": epic, "kind": "note", "text": str(a[1:3])})
    monkeypatch.setattr(BoardClient, "topic_propose", post)
    monkeypatch.setattr(BoardClient, "propose_fix", post)


def _rid(out: dict) -> str:
    v = out["value"]
    return v.get("id") or v.get("record", {}).get("id") or json.dumps(v, sort_keys=True, default=str)[:200]


@pytest.mark.parametrize("name", IDEMPOTENT_CREATES)
def test_every_idempotent_create_replays_by_key_across_restarts(rig, monkeypatch, name):
    _redirect_topic_calls(monkeypatch, rig["epic"])
    o = rig["seat"]("architect", "architect") if name == "criterion_create" else rig["owner"]
    first = call(o, name, **_create_args(rig, name, "a"), idempotency_key=f"{name}-k")
    assert first["ok"], first
    again = call(o, name, **_create_args(rig, name, "a"), idempotency_key=f"{name}-k")
    assert again["ok"] and _rid(again) == _rid(first) and again["value"].get("replay") is True, again
    clash = call(o, name, **_create_args(rig, name, "b"), idempotency_key=f"{name}-k")
    assert not clash["ok"] and clash["error"]["code"] == "conflict", clash
    tool_idem.reset()  # the MCP proxy restarted: the key is the board's, not the process's
    after = call(o, name, **_create_args(rig, name, "a"), idempotency_key=f"{name}-k")
    assert after["ok"] and _rid(after) == _rid(first) and after["value"].get("replay") is True, after
    fresh = call(o, name, **_create_args(rig, name, "a"), idempotency_key=f"{name}-k2")
    assert fresh["ok"] and _rid(fresh) != _rid(first), "a new key must make a deliberate twin"


def test_a_key_survives_a_board_restart_and_is_per_seat(rig, tmp_path):
    store = Store(str(tmp_path / "idem.db"))
    raw = TestClient(create_app(Board(store), admin_token="t"))
    admin = BoardClient(admin_token="t", client=raw)
    for h in ("owner", "owner2"):
        assert admin._request("POST", "/v1/participants", admin=True,
                              json={"type": "human", "role": "owner", "handle": h, "id": h})["ok"]
    o = BoardClient(participant="owner", admin_token="t", client=raw)
    first = call(o, "ticket_create", kind="epic", work_type="feature", title="r", idempotency_key="k")
    raw2 = TestClient(create_app(Board(store), admin_token="t"))  # a board restart on the same DB
    tool_idem.reset()
    o2 = BoardClient(participant="owner", admin_token="t", client=raw2)
    again = call(o2, "ticket_create", kind="epic", work_type="feature", title="r", idempotency_key="k")
    assert again["value"]["id"] == first["value"]["id"] and again["value"]["replay"] is True
    other = BoardClient(participant="owner2", admin_token="t", client=raw2)
    theirs = call(other, "ticket_create", kind="epic", work_type="feature", title="r", idempotency_key="k")
    assert theirs["ok"] and theirs["value"]["id"] != first["value"]["id"], "one seat's key replayed for another"


def test_a_refused_create_is_not_kept(rig):
    o = rig["owner"]
    bad = call(o, "message_send", ticket_id="t-missing", kind="note", text="x", idempotency_key="kk")
    assert not bad["ok"]
    good = call(o, "message_send", ticket_id=rig["epic"], kind="note", text="x", idempotency_key="kk")
    assert good["ok"] and not good["value"].get("replay"), good


def test_the_key_goes_only_on_the_first_post():
    from edp8.client import _IDEM_KEY, idempotency_key
    sent = []

    class Fake:
        def request(self, method, path, **kw):
            sent.append(kw["headers"].get("Idempotency-Key"))
            return type("R", (), {"json": lambda self: {"ok": True, "value": {}}})()

    c = BoardClient(participant="p", admin_token="t", client=Fake())  # type: ignore[arg-type]
    with idempotency_key("k"):
        c._request("GET", "/v1/whoami")
        c._request("POST", "/v1/a")
        c._request("POST", "/v1/b")
    assert sent == [None, "k", None] and _IDEM_KEY.get() is None


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


# T3 F4: participants(type=human) lists the people, through REST, still paged
def test_participants_type_filter(rig):
    rig["seat"]("engineer", "engineer.t-y")
    humans = call(rig["owner"], "participants", type="human")
    assert humans["ok"] and {r["type"] for r in humans["value"]["items"]} == {"human"}, humans
    agents = call(rig["owner"], "participants", type="agent")["value"]["items"]
    assert [r["id"] for r in agents] == ["engineer.t-y"]
    assert "next_cursor" in humans["value"]
    rest = rig["owner"].participants(type="human")["value"]
    assert [r["id"] for r in rest] == [r["id"] for r in humans["value"]["items"]]
    assert not call(rig["owner"], "participants", type="robot")["ok"]


# T3 F1 without the fleet DB: under a small page cap, a seat that follows the hint's since value sees every row
@pytest.mark.parametrize("tool,since_arg", [("message_query", "since_seq"), ("events_query", "since")])
def test_following_the_hint_under_a_small_cap_loses_nothing(rig, monkeypatch, tool, since_arg):
    monkeypatch.setenv("EDP8_TOOL_PAGE_B", "2000")
    o = rig["owner"]
    for i in range(30):
        assert o.message_send(ticket_id=rig["epic"], kind="note", text=f"m{i} " + "x" * 200)["ok"]
    args = {"ticket_id": rig["epic"]} if tool == "message_query" else {"subject_id": rig["epic"]}
    whole = (o.message_query(ticket_id=rig["epic"], since_seq=0, limit=1000)["value"] if tool == "message_query"
             else o.events_query(subject_id=rig["epic"], since=0, limit=1000)["value"])
    got, since, pages = [], 0, 0
    while True:
        out = call(o, tool, **args, **{since_arg: since}, limit=100)
        items = out["value"]["items"]
        if not items:
            break
        pages += 1
        got += [r["id"] for r in items]
        since = int(re.search(rf"{since_arg}=(\d+)", out["hint"]).group(1))
        assert since == out["value"]["last_seq"], out["hint"]
    assert pages > 1, "the cap never cut a page: the test proves nothing"
    assert got == [r["id"] for r in whole]
