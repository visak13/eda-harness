"""epic-91fcd3b370 S4 (s-18d9baa73c, c-e12fe2d0b6): a structured code anchor on board messages.

POST /v1/messages takes `code_context`, validates it server-side (a 400 naming the field), keeps it
through the store, and every agent read (context, context_delta, message_read) renders it as
`path:Lx-y @sha7[dirty]` / `@no-git` plus the fenced snippet within the byte caps. The MCP
message_send tool carries the arg through to the board.
"""

from __future__ import annotations

import hashlib
import json
import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

from edp8.board import Board
from edp8.bundles import ALL_TOOLS, set_client
from edp8.client import BoardClient
from edp8.schemas import ANCHOR_SNIPPET_CAP_B, SNIPPET_MAX_B, CodeAnchor, CodeContext, Message
from edp8.service import create_app
from edp8.store import Store

ADMIN = {"X-Admin": "t"}
OWNER = {"X-Participant": "owner"}
ENG = {"X-Participant": "eng"}
SHA = "0123456789abcdef0123456789abcdef01234567"


def anchor(**over):
    cc = {"repo_root": "C:/Projects/Learning/eda-base3/v8", "path": "src/edp8/board.py", "line_start": 10,
          "line_end": 12, "commit": SHA, "dirty": False, "snippet": "def f():\n    return 1\n"}
    cc.update(over)
    if "snippet_sha" not in over:
        cc["snippet_sha"] = hashlib.sha256(cc["snippet"].encode("utf-8")).hexdigest()
    return cc


@pytest.fixture
def client():
    return TestClient(create_app(Board(Store(":memory:")), admin_token="t"))


@pytest.fixture
def story(client):
    for pid, role, typ in [("owner", "owner", "human"), ("arch", "architect", "agent"),
                           ("eng", "engineer", "agent")]:
        assert client.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                           headers=ADMIN).json()["ok"]
    epic = client.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "code tab"},
                       headers=OWNER).json()["value"]
    return client.post("/v1/tickets", json={"kind": "story", "work_type": "feature", "title": "S4",
                                            "parent_id": epic["id"], "assignee": "eng"},
                       headers={"X-Participant": "arch"}).json()["value"]["id"]


def send(client, story, cc, text="why is this here?"):
    return client.post("/v1/messages", headers=OWNER,
                       json={"ticket_id": story, "to": "eng", "kind": "question", "text": text, "code_context": cc})


# ------------------------------------------------------------------------------ round trip

def test_valid_code_context_round_trips_through_message_read(client, story):
    cc = anchor(dirty=True)
    r = send(client, story, cc)
    assert r.status_code == 200, r.text
    mid = r.json()["value"]["id"]
    got = client.get(f"/v1/messages/{mid}", headers=ENG).json()["value"]
    assert got["code_context"] == cc  # message_read keeps the whole anchor intact
    assert got["code_anchor"].startswith("`src/edp8/board.py:L10-12 @0123456[dirty]`\n```\n")
    assert cc["snippet"] in got["code_anchor"]
    # the ticket page thread gets the full anchor for the code card
    page = client.get(f"/v1/tickets/{story}/page", headers=OWNER).json()["value"]
    assert page["thread"][-1]["code_context"] == cc


def test_commit_null_is_a_non_git_folder(client, story):
    cc = anchor(commit=None, repo_root="D:/scratch/notes", path="todo.md")
    r = send(client, story, cc)
    assert r.status_code == 200, r.text
    got = client.get(f"/v1/messages/{r.json()['value']['id']}", headers=ENG).json()["value"]
    assert got["code_context"]["commit"] is None
    assert got["code_anchor"].startswith("`todo.md:L10-12 @no-git`")


def test_dirty_without_commit_survives_agent_summary(client, story):
    r = send(client, story, anchor(commit=None, dirty=True))
    assert r.status_code == 200
    got = client.get(f"/v1/messages/{r.json()['value']['id']}", headers=ENG).json()["value"]
    assert "@no-git[dirty]" in got["code_anchor"]


def test_message_without_code_context_is_unchanged(client, story):
    r = client.post("/v1/messages", headers=OWNER, json={"ticket_id": story, "kind": "note", "text": "plain"})
    got = client.get(f"/v1/messages/{r.json()['value']['id']}", headers=ENG).json()["value"]
    assert got["code_context"] is None and "code_anchor" not in got


def test_snippet_at_the_cap_and_posix_root_are_accepted(client, story):
    at_cap = "é" * (SNIPPET_MAX_B // 2)  # 2 bytes each: exactly 4096 bytes
    assert send(client, story, anchor(snippet=at_cap)).status_code == 200
    assert send(client, story, anchor(repo_root="/home/me/repo")).status_code == 200


# ------------------------------------------------------------------------------ validation

@pytest.mark.parametrize("over, field", [
    ({"path": "../secrets.txt"}, "code_context.path"),
    ({"path": "src/../../etc/passwd"}, "code_context.path"),
    ({"path": "src\\edp8\\board.py"}, "code_context.path"),
    ({"path": "/abs/board.py"}, "code_context.path"),
    ({"path": "C:/abs/board.py"}, "code_context.path"),
    ({"path": "C:board.py"}, "code_context.path"),
    ({"path": "./board.py"}, "code_context.path"),
    ({"path": "src//board.py"}, "code_context.path"),
    ({"path": "src/"}, "code_context.path"),
    ({"path": "src/board.py\x00.txt"}, "code_context.path"),
    ({"line_start": 20, "line_end": 10}, "code_context.line_end"),
    ({"line_start": 10 ** 40, "line_end": 10 ** 40}, "code_context.line_start"),
    ({"path": "a/\u202eyp.exe"}, "code_context.path"),  # RTL override: renders spoofed
    ({"path": "a\u0085b"}, "code_context.path"),         # C1 NEL
    ({"path": "a\u2028b"}, "code_context.path"),         # line separator
    ({"path": "a/b::$DATA"}, "code_context.path"),       # NTFS stream
    ({"path": " a.py"}, "code_context.path"),
    ({"path": "a/b "}, "code_context.path"),
    ({"path": "a`b.py"}, "code_context.path"),           # would close the anchor's inline span
    ({"repo_root": "C:/r\n"}, "code_context.repo_root"),
    ({"lineStart": 3}, "code_context.lineStart"),         # a typo is named, not dropped
    ({"line_start": 0}, "code_context.line_start"),
    ({"commit": "not-a-sha"}, "code_context.commit"),
    ({"commit": SHA.upper()}, "code_context.commit"),
    ({"commit": SHA[:39]}, "code_context.commit"),
    ({"snippet": "x" * (SNIPPET_MAX_B + 1)}, "code_context.snippet"),
    ({"snippet": "é" * (SNIPPET_MAX_B // 2) + "a"}, "code_context.snippet"),  # 4097 bytes, 2049 chars
    ({"snippet_sha": "0" * 64}, "code_context.snippet_sha"),
    ({"repo_root": "relative/root"}, "code_context.repo_root"),
])
def test_invalid_code_context_is_a_400_naming_the_field(client, story, over, field):
    r = send(client, story, anchor(**over))
    assert r.status_code == 400, r.text
    msg = r.json()["error"]["message"]
    assert field in msg, msg
    # nothing was posted
    assert client.get("/v1/messages", headers=OWNER, params={"ticket_id": story}).json()["value"] == []


def test_non_object_code_context_is_a_400(client, story):
    for bad in ("src/a.py:L1", [1, 2], 7):
        r = send(client, story, bad)
        assert r.status_code == 400 and "code_context: must be an object" in r.json()["error"]["message"], r.text


def test_a_stored_anchor_that_later_rules_refuse_still_loads(client, story):
    """The store re-validates rows on read: the door rules must not apply there, or one tightening
    of them makes an old message, and with it its whole thread, unreadable (review finding 1)."""
    old = CodeAnchor(**anchor(path="./legacy.py"))  # accepted by 726d466, refused since 1e3195a
    m = Message(id="m-legacy", ticket_id=story, kind="note", text="old tag", created_by="owner", code_context=old)
    client.app.state.board.store.put("message", m)
    got = client.get("/v1/messages/m-legacy", headers=ENG).json()["value"]
    assert got["code_anchor"].startswith("`./legacy.py:L10-12")
    page = client.get(f"/v1/tickets/{story}/page", headers=OWNER).json()["value"]
    assert page["thread"][-1]["code_context"]["path"] == "./legacy.py"


def test_missing_field_is_named(client, story):
    cc = anchor()
    del cc["snippet_sha"]
    r = send(client, story, cc)
    assert r.status_code == 400 and "code_context.snippet_sha" in r.json()["error"]["message"]


# ------------------------------------------------------------------------------ agent rendering

def test_context_and_delta_render_the_anchor_within_the_caps(client, story):
    set_client(BoardClient(participant="eng", admin_token="t", client=client))
    ctx, dl = ALL_TOOLS["context"], ALL_TOOLS["context_delta"]
    base = ctx.handler(ctx.args_model())["value"]
    big = "\n".join(f"line {i} " + "x" * 60 for i in range(60))[:SNIPPET_MAX_B]  # ~4 KB snippet
    small = anchor(snippet="a = `b`\n```\nfence inside\n```")
    assert send(client, story, anchor(snippet=big, line_start=1, line_end=60)).status_code == 200
    assert send(client, story, small).status_code == 200

    # context(): the bounded (default) snapshot carries `code_anchor`, snippet capped, no raw snippet
    snap = ctx.handler(ctx.args_model())["value"]
    rows = [r for r in snap["tickets"][0]["thread"] if r.get("code_anchor")]
    assert len(rows) == 2
    first, second = rows
    assert first["code_anchor"].startswith("`src/edp8/board.py:L1-60 @0123456`")
    assert "snippet clipped" in first["code_anchor"] and "message_read for all" in first["code_anchor"]
    assert len(first["code_anchor"].encode()) < ANCHOR_SNIPPET_CAP_B + 300
    assert "snippet" not in first["code_context"] and first["code_context"]["repo_root"].endswith("/v8")
    # a snippet containing ``` gets a longer fence, so it cannot break out
    assert "\n````\na = `b`\n```\nfence inside\n```\n````" in second["code_anchor"]
    assert len(json.dumps(snap).encode()) < 40_000

    # context_delta(): the change rows carry the same compact anchor, inside the delta budget
    out = dl.handler(dl.args_model(cursor=base["cursor"]))["value"]
    msgs = [c for c in out["changes"] if c.get("object_type") == "message"]
    assert [m["code_anchor"].split("\n", 1)[0] for m in msgs] == [
        # the cap is in JSON-escaped bytes: 14 clipped lines' \n cost 2 each, so 1010 raw bytes fit
        "`src/edp8/board.py:L1-60 @0123456` (snippet clipped to 1010 of %d B; message_read for all)"
        % len(big.encode()),
        "`src/edp8/board.py:L10-12 @0123456`"]
    assert len(json.dumps(out).encode()) <= 12_000

    # message_read (the tool): the whole snippet
    mr = ALL_TOOLS["message_read"]
    full = mr.handler(mr.args_model(id=msgs[0]["object_id"]))["value"]
    assert big in full["code_anchor"] and "clipped" not in full["code_anchor"]


def test_clip_is_in_escaped_bytes_and_never_splits_a_code_point():
    cc = CodeContext(**anchor(snippet="é" * 600))  # each é costs 6 escaped bytes (é)
    assert cc.anchor(1023).split("\n")[2] == "é" * 170
    heavy = CodeContext(**anchor(snippet="\x01" * 1024))  # 1 UTF-8 byte, 6 escaped bytes each
    assert len(json.dumps(heavy.anchor(ANCHOR_SNIPPET_CAP_B))) < ANCHOR_SNIPPET_CAP_B + 300
    assert CodeContext(**anchor()).anchor(0).startswith("`src/edp8/board.py:L10-12 @0123456` (snippet omitted")


def test_heavy_anchor_never_drops_its_message_from_the_delta(client, story):
    set_client(BoardClient(participant="eng", admin_token="t", client=client))
    ctx, dl = ALL_TOOLS["context"], ALL_TOOLS["context_delta"]
    base = ctx.handler(ctx.args_model())["value"]
    long_path = "/".join(["d" * 50] * 19) + "/f.py"  # ~970 chars, rendered twice in the row
    r = send(client, story, anchor(snippet='"\\' * 1500, path=long_path), text="界" * 600)
    assert r.status_code == 200, r.text
    out = dl.handler(dl.args_model(cursor=base["cursor"]))["value"]
    row = next(c for c in out["changes"] if c.get("object_id") == r.json()["value"]["id"])
    assert row["object_type"] == "message" and row["read_ref"]["tool"] == "message_read"
    assert row["code_anchor"].startswith(f"`{long_path}:L10-12")


def test_tighter_context_pass_keeps_only_the_anchor_line(client, story):
    set_client(BoardClient(participant="eng", admin_token="t", client=client))
    for i in range(3):
        send(client, story, anchor(snippet=f"# {i}\n" + "\x01" * 1000), text="x" * 3000)
    from edp8.bundles import _bound_snapshot
    ctx = ALL_TOOLS["context"]
    full = ctx.handler(ctx.args_model(verbose=True))["value"]
    snap, _ = _bound_snapshot(full, thread_keep=1, thread_head=120, doc_head=120, words_head=400)  # pass 2
    rows = [r for r in snap["tickets"][0]["thread"] if r.get("code_anchor")]
    assert rows and all("\n" not in r["code_anchor"] for r in rows)
    assert rows[-1]["code_anchor"].startswith("`src/edp8/board.py:L10-12 @0123456` (snippet clipped")


# ------------------------------------------------------------------------------ MCP tool

def test_mcp_message_send_schema_accepts_code_context(client, story):
    tool = ALL_TOOLS["message_send"]
    props = tool.args_model.model_json_schema()["properties"]
    assert "code_context" in props
    set_client(BoardClient(participant="owner", admin_token="t", client=client))
    cc = anchor(commit=None)
    out = tool.handler(tool.args_model(ticket_id=story, kind="question", to="eng", text="look", code_context=cc))
    assert out["ok"], out
    got = client.get(f"/v1/messages/{out['value']['id']}", headers=ENG).json()["value"]
    assert got["code_context"] == cc
    bad = tool.handler(tool.args_model(ticket_id=story, kind="note", text="x", code_context=anchor(path="../x")))
    assert not bad["ok"] and "code_context.path" in bad["error"]["message"]
