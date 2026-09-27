"""One bounded S23-T5 usability pass. Private in-memory board; no fleet writes/network.
Run: .venv/Scripts/python.exe docs/evidence/s23-t5/repro.py
External research is a deterministic page fixture; real tool/client/route code runs.
"""
import json
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
private = Path(tempfile.mkdtemp(prefix="edp-s23-t5-repro-"))
for key in list(os.environ):
    if key.startswith(("EDP_", "EDP8_")):
        del os.environ[key]
os.environ.update(EDP8_HOME=str(private), EDP8_DATA=str(private),
                  EDP8_UPLOAD_SWEEP="0", EDP8_EMBEDDER="none", EDP8_RSI="0")
sys.path.insert(0, str(ROOT / "src"))
from fastapi.testclient import TestClient
from edp8 import broker_adapter, tool_idem, topics
from edp8.board import Board
from edp8.bundles import ALL_TOOLS, ROLE_BUNDLES, bind_request, invoke
from edp8.client import BoardClient
from edp8.schemas import Ticket, TicketKind, TicketStatus, WorkType
from edp8.service import create_app
from edp8.store import Store

broker_adapter.publish = lambda *a, **k: True
board = Board(Store(":memory:"))
raw = TestClient(create_app(board, admin_token="private-test"))
admin = BoardClient(admin_token="private-test", client=raw)
clients = {}
results = {}

def seat(role, handle, typ="agent"):
    r = admin.participant_create(typ, role, handle, id=handle)
    assert r["ok"], r
    c = BoardClient(participant=handle, admin_token="private-test", client=raw)
    clients[handle] = c
    return c

def call(c, name, **args):
    with bind_request(c, session_id="private-repro"):
        return invoke(ALL_TOOLS[name], args, seat=c.participant)

def size(r):
    return len(json.dumps(r, ensure_ascii=False, default=str, separators=(",", ":")).encode())

def good(r):
    assert r.get("ok"), r
    return r["value"]

owner = seat("owner", "owner", "human")
arch = seat("architect", "architect")
epic = good(call(owner, "ticket_create", kind="epic", work_type="feature", title="Private usability audit"))["id"]
sme = seat("sme", "sme.topic-repro")
doctor = seat("doctor", "doctor.topic-help")
for tid, who, tags in [("topic-repro", sme, []), ("topic-help", doctor, ["help"])]:
    board.store.put("ticket", Ticket(id=tid, kind=TicketKind.topic, work_type=WorkType.knowledge,
        title="Private topic fixture", status=TicketStatus.in_progress, assignee=who.participant,
        tags=tags, topic_config={"seed_url": None, "allowlist": [], "tags_set_by": "owner"}))

# Real research endpoint, deterministic already-allowed source, no external requests.
url = "https://skills.sh/a/b/c"
source = ("Source paragraph with ordinary prose. " * 400) + "TAIL_FACT_7391"
topics.fetch = lambda u, hosts: (u, 200, source.encode())
research = call(sme, "topic_research", topic_id="topic-repro", url=url)
rv = good(research)
repeat = good(call(sme, "topic_research", topic_id="topic-repro", url=url))
offset = call(sme, "topic_research", topic_id="topic-repro", url=url, offset=12000)
results["research_tail"] = {"source_chars": len(source), "returned_chars": len(rv["text"]),
    "bytes": size(research), "truncated": rv["truncated"], "tail_visible": "TAIL_FACT_7391" in rv["text"],
    "repeat_same_prefix": repeat["text"] == rv["text"], "response_keys": sorted(rv),
    "offset_attempt": offset, "next": rv["next"]}
assert rv["truncated"] and "TAIL_FACT_7391" not in rv["text"] and not offset["ok"]

# All ten creates hit their real endpoints, including proposal routes omitted by audit.
creates = {
 "ticket_create": (owner, dict(kind="epic", work_type="feature", title="Keyed epic")),
 "doc_create": (arch, dict(doc_type="note", title="Keyed note", body_md="b", scope=epic)),
 "artifact_create": (arch, dict(form="url", uri="https://example.com/a", ticket_id=epic)),
 "criterion_create": (arch, dict(ticket_id=epic, text="Measured check", check="command")),
 "message_send": (owner, dict(ticket_id=epic, kind="note", text="Keyed note")),
 "record_decision": (owner, dict(scope=epic, text="Measured ruling")),
 "record_claim": (owner, dict(scope=epic, text="Measured claim")),
 "record_lesson": (arch, dict(domain="tools", topic="audit", text="Measured lesson")),
 "topic_propose": (sme, dict(topic_id="topic-repro", title="Keyed proposal", body_md="b", source_url=url)),
 "propose_fix": (doctor, dict(topic_id="topic-help", action=dict(kind="gate.open", ticket_id=epic,
     gate="scope", note="Private inert proposal"), effect="Show a scope gate for review")),
}
results["keyed_creates"] = {}
for name, (c, args) in creates.items():
    first = good(call(c, name, **args, idempotency_key=name))
    tool_idem.reset()
    second = good(call(c, name, **args, idempotency_key=name))
    def rid(v):
        return v.get("id") or v.get("doc", {}).get("id") or v.get("record", {}).get("id")
    assert rid(first) and rid(first) == rid(second) and second.get("replay") is True, (name, first, second)
    results["keyed_creates"][name] = {"same_id": True, "replay": True, "bytes_first": size(first)}

# Full-body echo, at an ordinary report/message size, not an adversarial payload.
body = "A report sentence with evidence and a measured result.\n" * 250
doc = call(arch, "doc_create", doc_type="note", title="Long report", body_md=body, scope=epic)
msg = call(owner, "message_send", ticket_id=epic, kind="note", text=body)
results["echo"] = {"input_body_bytes": len(body.encode()), "doc_create_bytes": size(doc),
    "message_send_bytes": size(msg), "doc_body_identical": good(doc)["body_md"] == body,
    "message_body_identical": good(msg)["text"] == body}

# Human filter closure plus cap after reach enrichment. Realistic long seat handles.
for i in range(65):
    seat("engineer", f"engineer.ticket-{i:03d}-component-validation-round")
humans = call(owner, "participants", type="human")
assert all(p["type"] == "human" for p in good(humans)["items"])
roster = call(owner, "participants", limit=100)
default_roster = call(owner, "participants")
results["participants"] = {"human_count": len(good(humans)["items"]), "filtered_bytes": size(humans),
    "limit100_bytes": size(roster), "limit100_rows": len(good(roster)["items"]),
    "default_bytes": size(default_roster), "default_rows": len(good(default_roster)["items"]),
    "page": good(roster)["page"]}

# Every seq-paged tool: hints and cursors independently consume the same complete fixture.
for i in range(35):
    good(call(owner, "message_send", ticket_id=epic, kind="note", text=f"row {i}: " + "ordinary text " * 30))
results["seq_parity"] = {}
for name, fixed, since_name in [("message_query", {"ticket_id": epic}, "since_seq"),
                                 ("events_query", {"subject_id": epic}, "since")]:
    collections = {}
    for mode in ("hint", "cursor"):
        ids, count = [], 0
        args = {**fixed, since_name: 0}
        for _ in range(200):
            r = call(owner, name, **args)
            v = good(r)
            ids += [x["id"] for x in v["items"]]
            count += 1
            if not v["next_cursor"]:
                break
            if mode == "hint":
                s = int(re.search(r"last_seq=(\d+)", r["hint"])[1])
                assert s == v["last_seq"]
                args = {**fixed, since_name: s}
            else:
                args = {**fixed, since_name: 0, "cursor": v["next_cursor"]}
        else:
            raise AssertionError("continuation failed to terminate")
        collections[mode] = (ids, count)
    expected = good(owner.message_query(ticket_id=epic, since_seq=0, limit=1000)) if name == "message_query" else good(owner.events_query(subject_id=epic, since=0, limit=1000))
    assert collections["hint"][0] == collections["cursor"][0] == [x["id"] for x in expected]
    results["seq_parity"][name] = {"rows": len(expected), "hint_pages": collections["hint"][1],
                                    "cursor_pages": collections["cursor"][1], "exact": True}

# Completeness: owner cannot finish the otherwise normal knowledge-proposal lifecycle with tools.
results["approval_surface"] = {"owner_tools": sorted(ROLE_BUNDLES["owner"]),
    "candidate_tools": [n for n in ALL_TOOLS if any(s in n for s in ("approve", "reject", "proposal"))],
    "proposal_hint": call(sme, "topic_propose", **creates["topic_propose"][1], idempotency_key="proposal-next")["hint"]}
OUT.joinpath("repro-results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
print(json.dumps(results, indent=2))
