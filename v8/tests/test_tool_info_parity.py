"""S23 no-information-loss (owner m-891b9f42bd, criterion c-2c16f5ebf0): the tool refactor keeps every fact.

1. Description facts: tests/data/s23_tool_facts_before.json snapshots every tool at the pre-S23 HEAD (what,
   when, returns, fields, required fields, enum values, roles). Each fact must survive: its words in the new
   description, the advertised schema or the describe() contract of the tool's objects; every field, enum
   value and role still there. Moving a fact is fine, deleting it is not.
2. Paging parity: each bounded list tool paged to the end equals the unbounded REST result — verbose pages
   row for row, default pages the same ids, with the full-read call named in the page.
3. Truncation is visible: a capped page names the call that continues it and the call that returns full rows.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from edp8 import broker_adapter
from edp8.board import Board
from edp8.bundles import ALL_TOOLS, ROLE_BUNDLES, enum_fields, invoke, set_client
from edp8.client import BoardClient
from edp8.schemas import DESCRIBE
from edp8.service import create_app
from edp8.store import Store
from edp8.tool_contracts import LOCAL_OBJECTS, tool_objects

HERE = Path(__file__).resolve().parent
FACTS = json.loads((HERE / "data" / "s23_tool_facts_before.json").read_text(encoding="utf-8"))["tools"]
FLEET_DB = HERE.parent / ".data" / "edp8.db"
_STOP = set("the a an and or of to for in on by with its it is be as at from your you this that when what then "
            "not no one each any".split())


def _words(text: str) -> set[str]:
    return {w.lower() for w in re.findall(r"[A-Za-z_][A-Za-z_0-9]{3,}|\d+", text)} - _STOP


def _corpus(name: str) -> set[str]:
    tool = ALL_TOOLS[name]
    text = tool.description + " " + json.dumps(tool.input_schema)
    for obj in tool_objects(name):
        text += " " + str(DESCRIBE.get(obj, "")) + " " + json.dumps(LOCAL_OBJECTS.get(obj, {}))
    return _words(text)


# ----------------------------------------------------------------------------- 1. description facts


@pytest.mark.parametrize("name", sorted(FACTS))
def test_every_pre_s23_fact_survives(name):
    before = FACTS[name]
    assert name in ALL_TOOLS, f"{name} was removed"
    tool = ALL_TOOLS[name]
    lost = _words(" ".join((before["what"], before["when"], before["returns"]))) - _corpus(name)
    assert not lost, f"{name}: description facts deleted: {sorted(lost)}"
    fields = set(tool.args_model.model_fields)
    assert set(before["fields"]) <= fields, f"{name}: fields dropped {set(before['fields']) - fields}"
    now = enum_fields(tool.args_model)
    for field, values in before["enums"].items():
        assert set(values) <= set(now.get(field, [])), f"{name}.{field}: enum values dropped"
    roles = {r for r, names in ROLE_BUNDLES.items() if name in names}
    assert set(before["roles"]) <= roles, f"{name}: roles lost it: {set(before['roles']) - roles}"


# ----------------------------------------------------------------------------- 2. paging parity


@pytest.fixture(scope="module")
def fleet(tmp_path_factory):
    """A read-only online backup of the fleet DB (never the file itself); skipped where there is none."""
    if not FLEET_DB.is_file():
        pytest.skip("no fleet DB on this host")
    copy = tmp_path_factory.mktemp("parity") / "edp8.db"
    src = sqlite3.connect(f"file:{FLEET_DB.as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(copy)
    src.backup(dst)
    dst.close()
    src.close()
    mp = pytest.MonkeyPatch()
    mp.setattr(broker_adapter, "publish", lambda *a, **k: True)
    mp.setenv("EDP8_UPLOAD_SWEEP", "0")
    mp.setenv("EDP8_EMBEDDER", "none")
    mp.delenv("EDP_POOL_URL", raising=False)
    mp.delenv("EDP8_PUBLIC_URL", raising=False)  # a seat shell carries the fleet's; this board is local
    tokens = copy.parent / "tokens.json"  # private: the fleet token file is never read or written
    tokens.write_text(json.dumps({"parity.owner": "parity-secret", "agents": {}}), encoding="utf-8")
    mp.setenv("EDP8_TOKENS", str(tokens))
    board = Board(Store(str(copy)))
    raw = TestClient(create_app(board, admin_token="t"))
    admin = BoardClient(admin_token="t", client=raw)
    made = admin._request("POST", "/v1/participants", admin=True,
                          json={"type": "human", "role": "owner", "handle": "parity.owner", "id": "parity.owner"})
    assert made["ok"], made
    yield {"client": BoardClient(participant="parity.owner", token="parity-secret", admin_token="t", client=raw),
           "board": board}
    mp.undo()


def _page_all(client: BoardClient, tool: str, args: dict, *, verbose: bool) -> tuple[list, list[dict]]:
    set_client(client)
    items, pages, cursor = [], [], None
    for _ in range(2_000):
        call = {**args, "verbose": verbose, "limit": 100, **({"cursor": cursor} if cursor else {})}
        out = invoke(ALL_TOOLS[tool], call, seat="parity.owner")
        assert out["ok"], (tool, out)
        pages.append(out["value"])
        items += out["value"]["items"]
        cursor = out["value"]["next_cursor"]
        if not cursor:
            return items, pages
    raise AssertionError(f"{tool} never ended")


def _chunks(rows: list, pages: list[dict]) -> list[list]:
    out, at = [], 0
    for page in pages:
        out.append(rows[at:at + len(page["items"])])
        at += len(page["items"])
    return out


def _ids(rows: list) -> list:
    return [r.get("id") if isinstance(r, dict) else r for r in rows]


# (tool, tool args, the pre-S23 unbounded REST read, id key) — the REST read is what the tool returned whole
CASES = [
    ("ticket_query", {}, lambda c: c.ticket_query(), "id"),
    ("doc_query", {}, lambda c: c.doc_query(), "id"),
    ("participants", {}, lambda c: c.participants(), "id"),
]


@pytest.mark.parametrize("tool,args,unbounded,key", CASES, ids=[c[0] for c in CASES])
def test_pages_together_equal_the_unbounded_result(fleet, tool, args, unbounded, key):
    client = fleet["client"]
    whole = unbounded(client)
    assert whole["ok"], whole
    rows = whole["value"]
    full, _ = _page_all(client, tool, args, verbose=True)
    if tool == "participants":  # the tool adds `reach` to every row (as it did before S23, then for all rows)
        assert all("reach" in r for r in full)
        full = [{k: v for k, v in r.items() if k != "reach"} for r in full]
    assert full == rows, f"{tool}: verbose pages differ from the unbounded rows"
    compact, pages = _page_all(client, tool, args, verbose=False)
    assert _ids(compact) == [r[key] for r in rows], f"{tool}: default pages lost or reordered records"
    for page, rows_on_page in zip(pages, _chunks(rows, pages)):
        cut = any(item != {k: v for k, v in row.items() if v not in (None, "", [], {})}
                  for item, row in zip(page["items"], rows_on_page))
        if cut:  # a compacted or clipped row: the page names the call that returns it whole
            assert page["page"]["full_rows"], f"{tool}: a compacted page names no full-read call"
        if page["next_cursor"]:
            assert "cursor=next_cursor" in page["page"]["continue"], f"{tool}: a capped page names no continuation"


def test_link_and_session_pages_equal_the_unbounded_result(fleet):
    client = fleet["client"]
    epic = next(t for t in client.ticket_query()["value"] if t.get("kind") == "epic")
    whole = client.link_query(from_id=epic["id"])["value"] + client.link_query(to_id=epic["id"])["value"]
    got = (_page_all(client, "link_query", {"from_id": epic["id"]}, verbose=True)[0]
           + _page_all(client, "link_query", {"to_id": epic["id"]}, verbose=True)[0])
    assert got == whole
    seat = next(p["id"] for p in client.participants()["value"] if p.get("type") == "agent")
    rows = client.session_query(participant_id=seat)["value"]
    paged, _ = _page_all(client, "session_query", {"participant_id": seat}, verbose=True)
    assert sorted(_ids(paged)) == sorted(_ids(rows))


def test_message_pages_cover_the_whole_thread(fleet):
    client, board = fleet["client"], fleet["board"]
    counts = {}
    for m in board.store.query("message", {}):
        counts[m.ticket_id] = counts.get(m.ticket_id, 0) + 1
    ticket = max(counts, key=counts.get)
    whole = [m.id for m in sorted(board.store.query("message", {"ticket_id": ticket}), key=lambda m: m.created_at)]
    got, pages = _page_all(client, "message_query", {"ticket_id": ticket, "since_seq": 0}, verbose=False)
    assert _ids(got) == whole, "message_query pages lost or reordered messages"
    for row in got:
        for field, value in row.items():
            if isinstance(value, str) and value.endswith("chars)"):
                assert "message_read" in pages[0]["page"]["full_rows"], "a clipped body names no full read"


def test_event_pages_equal_the_unbounded_result(fleet):
    client, board = fleet["client"], fleet["board"]
    counts = {}
    for e in board.store.query("event", {}):
        counts[e.subject_id] = counts.get(e.subject_id, 0) + 1
    subject = max((s for s in counts if s), key=counts.get)
    whole = client.events_query(subject_id=subject, since=0, limit=100_000)["value"]
    got, _ = _page_all(client, "events_query", {"subject_id": subject}, verbose=True)
    assert got == whole, "events_query pages lost, altered or reordered events"
    compact, pages = _page_all(client, "events_query", {"subject_id": subject}, verbose=False)
    assert _ids(compact) == _ids(whole), "default event pages lost or reordered events"
    for page in pages:
        if any(str(r.get("data", "")).endswith("chars)") for r in page["items"]):
            assert page["page"].get("full_rows"), "a clipped event page names no full read"


def test_context_verbose_is_the_unbounded_snapshot_and_default_names_every_cut(fleet):
    client = fleet["client"]
    set_client(client)
    epic = next(t for t in client.ticket_query()["value"] if t.get("kind") == "epic")
    whole = client.context(ticket_id=epic["id"])["value"]
    full = invoke(ALL_TOOLS["context"], {"ticket_id": epic["id"], "verbose": True}, seat="parity.owner")["value"]
    # the cursor is minted per call (it carries the read's position), every other field must match
    assert {k: v for k, v in full.items() if k != "cursor"} == {k: v for k, v in whole.items() if k != "cursor"},         "context(verbose=True) differs from the pre-S23 unbounded snapshot"
    bounded = invoke(ALL_TOOLS["context"], {"ticket_id": epic["id"]}, seat="parity.owner")["value"]
    if {k: v for k, v in bounded.items() if k != "cursor"} != {k: v for k, v in whole.items() if k != "cursor"}:  # anything cut is named, with the exact call that returns the whole snapshot
        assert bounded["omitted"]["full_snapshot"] == "context(verbose=True)", bounded.get("omitted")
