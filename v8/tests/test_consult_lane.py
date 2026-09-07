"""The consult LANE (2026-09-06): single-flight, RAM gate, quota block, answer recovery."""

from __future__ import annotations

import json
import threading
import time

import pytest

from edp8 import consult


@pytest.fixture
def sol_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP8_SOL_LOG_DIR", str(tmp_path))
    return tmp_path


def test_quota_note_and_block(sol_dir, monkeypatch):
    monkeypatch.setenv("EDP8_CONSULT_QUOTA_BACKOFF_S", "120")
    assert consult.note_quota("all good\nfinal answer") is None
    rec = consult.note_quota("error: You've hit your usage limit. Try again at 3:45 PM.\n")
    assert rec and rec["try_again"] == "3:45 PM" and "usage limit" in rec["evidence"]
    blk = consult.quota_block()
    assert blk and blk["blocked_until"] == rec["blocked_until"]
    notes = consult.advisory()  # advisory, never a refusal
    assert any("usage/rate cap" in n and "3:45 PM" in n for n in notes)
    # an expired block is no note
    (sol_dir / "quota.json").write_text(json.dumps({**rec, "blocked_until": "2020-01-01T00:00:00Z"}), encoding="utf-8")
    assert consult.quota_block() is None and not any("cap" in n for n in consult.advisory())


def test_low_ram_is_a_note_not_a_gate(sol_dir, monkeypatch):
    monkeypatch.setattr(consult, "free_mb", lambda: 700)
    notes = consult.advisory()
    assert any("700 MB free" in n for n in notes)
    monkeypatch.setattr(consult, "free_mb", lambda: 5000)
    assert consult.advisory() == []


def test_preflight_tool_is_advisory_and_idempotent(monkeypatch):
    from edp8.bundles import ALL_TOOLS, ROLE_BUNDLES
    from edp8 import pool_adapter
    monkeypatch.setattr(pool_adapter, "sessions", lambda: {"ok": True, "value": [
        {"session_id": "a", "handle": "engineer.s1", "state": "active"}]})
    monkeypatch.setattr(pool_adapter, "capacity", lambda: {"ok": True, "value": {"max_total_shells": 10}})
    t = ALL_TOOLS["preflight"]
    one = t.handler(t.args_model()); two = t.handler(t.args_model())
    assert one["ok"] and one["value"]["host"]["free_mb"] > 0 and one["value"]["seats"]["live"] == 1
    assert one["value"]["seats"]["caps"] == {"max_total_shells": 10} and "advisory" in one["value"]
    assert one["value"]["seats"] == two["value"]["seats"] and "never a gate" in one["hint"]
    assert all("preflight" in b for b in ROLE_BUNDLES.values())


def test_recover_answer_takes_last_agent_message():
    raw = "\n".join([
        "plain text line",
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "first"}}),
        json.dumps({"type": "item.completed", "item": {"type": "command_execution", "command": "ls"}}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "FINAL"}}),
    ])
    assert consult.recover_answer(raw) == "FINAL"


def test_consult_status_recovers_from_manifest_or_log(sol_dir):
    rid = "20260906T000000Z-abcdef01"
    (sol_dir / f"{rid}.manifest.json").write_text(json.dumps({"status": "ok", "thread_id": "t1", "answer": "A"}),
                                                  encoding="utf-8")
    out = consult.consult_status(rid)
    assert out["ok"] and out["value"]["status"] == "ok" and out["value"]["answer"] == "A"
    rid2 = "20260906T000001Z-abcdef02"  # timed out client-side: log only
    (sol_dir / f"{rid2}.jsonl").write_text(
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "late"}}), encoding="utf-8")
    out2 = consult.consult_status(rid2)
    assert out2["ok"] and out2["value"]["recovered"] and out2["value"]["answer"] == "late"
    assert "lane" in out2["value"]
    missing = consult.consult_status("nope")
    assert missing["ok"] is False and missing["error"]["code"] == "not_found"


def test_lane_serialises_and_reports_queue(sol_dir, monkeypatch):
    """Two callers: the second waits for the first and sees queued_behind=1."""
    order: list[str] = []

    def fake_locked(purpose, question, **kw):
        order.append(f"start:{question}")
        time.sleep(0.3)
        order.append(f"end:{question}")
        return {"ok": True, "value": {"answer": "x", "queued_behind": kw["queued_behind"]}, "hint": ""}

    monkeypatch.setattr(consult, "_consult_locked", fake_locked)
    monkeypatch.setattr(consult, "_resolve_bin", lambda: "codex")
    results: dict[str, dict] = {}

    def go(q):
        results[q] = consult.consult("second_opinion", q)

    t1 = threading.Thread(target=go, args=("one",)); t1.start()
    time.sleep(0.05)
    t2 = threading.Thread(target=go, args=("two",)); t2.start()
    t1.join(); t2.join()
    assert order == ["start:one", "end:one", "start:two", "end:two"]
    assert results["one"]["value"]["queued_behind"] == 0 and results["two"]["value"]["queued_behind"] == 1
    assert consult.lane_status()["in_flight"] is None
