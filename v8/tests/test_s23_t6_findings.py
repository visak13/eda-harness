"""S23-T6 (t-5b432d6bd0): the T5 re-audit's findings N1-N5 (report-36481f7a4e), each as a regression.

N1 topic_research keeps the fetched page and reads on by offset, every reply <= the page cap.
N2 write tools reply with a compact receipt (clipped body + byte count + the read call), never the body sent.
N3 no bounded tool's final reply exceeds its advertised cap (participants enriched reach AFTER fitting).
N4 harvest_cost's no-log error names the roots it searched and never says "pass since".
N5 is the audit's scoring (scripts/tool_audit.py scores); its test is test_zero_ok_calls_is_not_measured.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from test_tool_contract import call, rig  # noqa: F401 — fixtures
from test_topics import ADMIN, OWNER, _topic, board, client, dns, pool, tokens  # noqa: F401 — fixtures

from edp8 import tool_paging
from edp8.bundles import ALL_TOOLS

TAIL = "TAIL_FACT_7391"


def _bytes(out: dict) -> int:
    """What the seat receives: compact UTF-8 JSON, as the audit measures it (T1/T5)."""
    return len(json.dumps(out, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"))


# ----------------------------------------------------------------------------- N1
@pytest.fixture
def long_page(monkeypatch):
    from edp8 import topics
    words = " ".join(f"sentence {i} about fixtures and arrange-act-assert." for i in range(300))
    page = f"<html><body><p>{words}</p><p>{TAIL} is the last fact.</p></body></html>".encode()
    assert len(page) > 15_000
    monkeypatch.setattr(topics, "FETCH", lambda url: (200, page, None) if "python-testing" in url else (404, b"", None))
    return page


def test_research_tail_is_readable_through_the_named_continuation(client, board, long_page):
    t = _topic(client)["topic"]
    url = "https://www.skills.sh/wshobson/agents/python-testing-patterns"
    out = client.post(f"/v1/topics/{t['id']}/research", json={"url": url}, headers=OWNER).json()
    assert out["ok"], out
    v = out["value"]
    assert v["truncated"] and v["receipt"]["status"] == 200 and TAIL not in v["text"]
    assert _bytes(out) <= 8_000, _bytes(out)
    assert "read to the end before you distil" in v["next"]
    text, pages = v["text"], 1
    while v["next_offset"] is not None:
        call = f"offset={v['next_offset']})"
        assert v["next"].startswith(f"topic_research(topic_id='{t['id']}', url='{url}', ") and call in v["next"]
        out = client.post(f"/v1/topics/{t['id']}/research", json={"url": url, "offset": v["next_offset"]},
                          headers=OWNER).json()
        assert out["ok"] and _bytes(out) <= 8_000, out
        v = out["value"]
        assert "receipt" not in v  # a continuation reads the kept text: no refetch, no second receipt
        text += v["text"]
        pages += 1
    assert pages > 1 and TAIL in text and len(text) == v["total_chars"]
    assert "the whole page is read" in v["next"]
    fetched = [e for e in client.get(f"/v1/topics/{t['id']}", headers=OWNER).json()["value"]["fetches"]]
    assert len(fetched) == 1


def test_research_offset_needs_a_kept_page(client, board, long_page):
    t = _topic(client)["topic"]
    out = client.post(f"/v1/topics/{t['id']}/research",
                      json={"url": "https://www.skills.sh/never/fetched", "offset": 10}, headers=OWNER).json()
    assert not out["ok"] and out["error"]["code"] == "not_found"
    assert "fetches it first" in json.dumps(out)


def test_research_tool_advertises_offset():
    assert "offset" in ALL_TOOLS["topic_research"].input_schema["properties"]


def test_topic_propose_reply_records_the_ui_only_exemption(client, board, tokens, long_page):
    t = _topic(client)["topic"]
    url = "https://www.skills.sh/wshobson/agents/python-testing-patterns"
    assert client.post(f"/v1/topics/{t['id']}/research", json={"url": url}, headers=OWNER).json()["ok"]
    board.run_pending_pairings()
    sme = f"sme.{t['id']}"
    secret = json.loads(tokens.read_text(encoding="utf-8"))["agents"][sme]
    out = client.post(f"/v1/topics/{t['id']}/proposals", headers={"X-Participant": sme, "X-Token": secret},
                      json={"title": "AAA", "body_md": "- tests follow AAA", "source_url": url}).json()
    assert out["ok"], out
    assert "human UI-only by design (owner uses the browser UI only, m-0213457e52)" in out["hint"]


# ----------------------------------------------------------------------------- N2
BIG = "# Body\n\n" + ("A long paragraph of report prose. " * 420)  # ~14 KB, like the T5 probe's 13,750 B


def _write_calls(rig) -> dict[str, tuple[str, dict]]:
    e = rig["epic"]
    story = rig["owner"]._request("POST", "/v1/tickets", json={"kind": "story", "work_type": "feature",
                                                               "title": "S", "parent_id": e})["value"]["id"]
    return {
        "doc_create": ("owner", {"doc_type": "note", "title": "big", "body_md": BIG, "scope": e}),
        "message_send": ("owner", {"ticket_id": e, "kind": "note", "text": BIG}),
        "ticket_create": ("architect", {"kind": "task", "work_type": "chore", "title": "t", "parent_id": story,
                                        "description": BIG}),
        "ticket_update": ("architect", {"ticket_id": story, "description": BIG}),
        "criterion_create": ("architect", {"ticket_id": story, "text": BIG, "check": "command"}),
        "record_decision": ("owner", {"scope": e, "text": "one line", "detail": BIG[:1000]}),
        "record_claim": ("owner", {"scope": e, "text": BIG[:600]}),
        "record_lesson": ("owner", {"domain": "tools", "topic": "echo", "text": BIG[:600]}),
    }


@pytest.mark.parametrize("name", ["doc_create", "message_send", "ticket_create", "ticket_update", "criterion_create",
                                  "record_decision", "record_claim", "record_lesson"])
def test_write_tools_reply_with_a_compact_receipt(rig, name):
    arch = rig["seat"]("architect", "architect")
    who, args = _write_calls(rig)[name]
    out = call(arch if who == "architect" else rig["owner"], name, **args)
    assert out["ok"], out
    v = out["value"]
    assert v.get("id"), v
    assert _bytes(out) < 2_500, (name, _bytes(out))
    echo = v["echo"]
    assert all(n > 240 for n in echo["bytes"].values()) and echo["read"].endswith(")")
    assert v["id"] in echo["read"] or v.get("ticket_id", "-") in echo["read"], echo
    for field in echo["bytes"]:
        assert v[field].endswith("chars)"), (name, field)


def test_receipt_read_call_returns_the_whole_body(rig):
    out = call(rig["owner"], "message_send", ticket_id=rig["epic"], kind="note", text=BIG)
    v = out["value"]
    assert v["echo"]["read"] == f"message_read(id='{v['id']}')" and isinstance(v["seq"], int)
    whole = call(rig["owner"], "message_read", id=v["id"])["value"]["text"]
    assert whole == BIG
    d = call(rig["owner"], "doc_create", doc_type="note", title="big", body_md=BIG, scope=rig["epic"])["value"]
    assert d["version"] == 1 and d["echo"]["bytes"]["body_md"] == len(BIG.encode())
    assert call(rig["owner"], "doc_read", id=d["id"])["value"]["body_md"] == BIG


def test_short_bodies_are_untouched(rig):
    v = call(rig["owner"], "message_send", ticket_id=rig["epic"], kind="note", text="short")["value"]
    assert v["text"] == "short" and "echo" not in v


def test_write_receipts_leave_out_unset_fields_the_read_returns(rig):
    """S23 qa (report-bcef24a36a): a receipt carries what the write set; null/[]/{} fields are left out and the
    named read still returns every field of the row, so no fact is lost and no write grows bytes."""
    v = call(rig["owner"], "message_send", ticket_id=rig["epic"], kind="note", text="short")["value"]
    assert isinstance(v["seq"], int) and not [f for f, x in v.items() if x is None or x == [] or x == {}], v
    full = call(rig["owner"], "message_read", id=v["id"])["value"]
    assert all(full[f] == x for f, x in v.items() if f in full)  # what the receipt shows matches the row
    assert all(x is None or x == [] or x == {} for f, x in full.items() if f not in v)  # only unset fields left out
    d = call(rig["owner"], "doc_create", doc_type="note", title="n", body_md="v1", scope=rig["epic"])["value"]
    assert "source_url" not in d and d["version"] == 1


def test_doc_update_defaults_to_a_receipt(rig):
    d = call(rig["owner"], "doc_create", doc_type="note", title="n", body_md="v1", scope=rig["epic"])["value"]
    out = call(rig["owner"], "doc_update", id=d["id"], body_md=BIG)
    assert out["ok"] and _bytes(out) < 600, out
    v = out["value"]  # S23 qa (report-bcef24a36a): the size sits behind read_ref, not in the receipt
    assert v["version"] == 2 and "bytes" not in v and v["read_ref"] == {"tool": "doc_read", "id": d["id"], "version": 2}
    assert call(rig["owner"], "doc_read", id=d["id"])["value"]["body_md"] == BIG  # the named read loses nothing
    assert ALL_TOOLS["doc_update"].input_schema["properties"]["compact"] == {"default": True, "type": "boolean"}
    full = call(rig["owner"], "doc_update", id=d["id"], body_md=BIG + "!", compact=False)["value"]
    assert full["body_md"] == BIG + "!"  # the kept compatibility flag still returns the doc


# ----------------------------------------------------------------------------- N3
def _fill(rig) -> None:
    """Rows big enough that limit=100 overflows 8 KB on every bounded list tool."""
    o, e = rig["owner"], rig["epic"]
    for i in range(110):
        rig["seat"]("engineer", f"engineer.t-{i:04d}-{'x' * 40}")
    for i in range(110):
        o._request("POST", "/v1/tickets", json={"kind": "story", "work_type": "feature", "parent_id": e,
                                                "title": f"story {i} " + "t" * 70})
        o._request("POST", "/v1/docs", json={"doc_type": "note", "title": f"doc {i} " + "d" * 80,
                                             "body_md": "b", "scope": e})
        o.message_send(ticket_id=e, kind="note", text=f"m{i} " + "y" * 300)


BOUNDED = {"participants": {}, "ticket_query": {}, "doc_query": {}, "link_query": {},
           "message_query": {"since_seq": 0}, "events_query": {"since": 0}, "session_query": {}}


def test_bounded_list_tools_are_the_advertised_ones():
    """Every tool that advertises a ≤8 KB page is measured above (topic_research: by the N1 continuation test)."""
    advertised = {n for n, t in ALL_TOOLS.items() if "≤8 KB" in t.description} - {"topic_research"}
    assert advertised <= set(BOUNDED), advertised - set(BOUNDED)


@pytest.mark.parametrize("limit", [None, 100])
@pytest.mark.parametrize("name", sorted(BOUNDED))
def test_no_bounded_tool_reply_exceeds_its_cap(rig, name, limit):
    _fill(rig)
    args = {**BOUNDED[name], **({"limit": limit} if limit else {})}
    if name == "message_query":
        args["ticket_id"] = rig["epic"]
    out = call(rig["owner"], name, **args)
    assert out["ok"], out
    cap = tool_paging.page_cap()
    assert _bytes(out) <= cap, (name, limit, _bytes(out), cap)
    page = out["value"].get("page") or {}
    if page.get("cap_b"):
        assert page["cap_b"] == cap


def test_participants_cursor_resumes_after_the_rows_shown(rig):
    _fill(rig)
    seen, cursor = [], None
    while True:
        out = call(rig["owner"], "participants", limit=100, **({"cursor": cursor} if cursor else {}))
        assert _bytes(out) <= tool_paging.page_cap()
        rows = out["value"]["items"]
        assert all("reach" in r for r in rows)
        seen += [r["id"] for r in rows]
        cursor = out["value"]["next_cursor"]
        if not cursor:
            break
    whole = [r["id"] for r in rig["owner"].participants()["value"]]
    assert seen == whole


# ----------------------------------------------------------------------------- N4
def test_harvest_no_log_names_the_roots_and_not_since(tmp_path, monkeypatch):
    from edp8 import harvest_cost as hc
    a, b = tmp_path / "claude", tmp_path / "codex"
    a.mkdir(), b.mkdir()
    monkeypatch.setenv("EDP8_HARVEST_LOG_ROOTS", f"{a}{__import__('os').pathsep}{b}")
    with pytest.raises(hc.NoLog) as e:
        hc.compute("qa.nobody", since="2026-09-27T00:00:00Z")
    assert str(a) in str(e.value) and str(b) in str(e.value)


def test_harvest_route_hint_for_a_missing_log_never_says_since(rig, tmp_path, monkeypatch):
    monkeypatch.setenv("EDP8_HARVEST_LOG_ROOTS", str(tmp_path))
    out = call(rig["owner"], "harvest_cost", participant_id="qa.nobody", since="2026-09-27T00:00:00Z")
    assert not out["ok"] and out["error"]["code"] == "not_found"
    assert str(tmp_path) in out["error"]["message"] and "since" not in out.get("hint", "") + \
        str(out["error"].get("hint", ""))


# ----------------------------------------------------------------------------- N5 (the audit's scoring)
def test_zero_ok_calls_is_not_measured():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import tool_audit

    class A:
        calls = [{"task": "coverage", "role": "sme", "tool": "topic_research", "args": {"topic_id": "x"},
                  "ok": False, "error_code": "not_found", "result_id": None, "error": "ticket 'x' does not exist",
                  "hint": "", "bytes_out": 94, "max_line_bytes": 94, "duration_ms": 1}]
    row = tool_audit.scores(A())["topic_research"]["standards"]
    for std in ("3_clear_output", "6_token_efficient"):
        assert row[std] == "not_measured" and "0 of 1 calls succeeded" in row[f"{std}_reason"], row
    m = tool_audit.matrix_summary({"topic_research": {"standards": row}})
    assert "topic_research.3_clear_output" in m["not_measured"] and not m["unexplained"]


def test_describe_schema_drops_only_generated_titles():
    """S23 qa (report-bcef24a36a): describe's schema leaves out pydantic's generated titles, which restate their
    key; every property, type, default, enum and $ref stays, and a hand-written title is kept."""
    from edp8.bundles import _lean_schema
    from edp8.schemas import Message, Session

    for model in (Session, Message):
        full = model.model_json_schema()
        lean = _lean_schema(full)

        def strip(node):
            if isinstance(node, list):
                return [strip(x) for x in node]
            return {k: strip(v) for k, v in node.items() if k != "title"} if isinstance(node, dict) else node
        assert strip(lean) == strip(full)  # nothing but titles differs
        assert all("title" not in p for p in lean["properties"].values()), lean["properties"]
        assert len(json.dumps(lean)) < len(json.dumps(full))
    custom = {"properties": {"a_b": {"title": "Something else", "type": "string"}}}
    assert _lean_schema(custom) == custom
