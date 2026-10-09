"""S15 (p-c98f480b, p-60fe5eac + dup p-18e1cfb3, p-787dec07): harvest_cost finds the seat logs of the INSTALLED pool
and answers a bad log or a bad `since` with a JSON error, never a plain-text 500.

Every case runs on a fixture tree under tmp_path; no real seat log is read.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from edp8 import harvest_cost as hc
from edp8.board import Board
from edp8.service import create_app
from edp8.store import Store

QA = "qa.epic-fixture01"
CODEX_QA = "qa.epic-fixture02"
ADMIN = {"X-Admin": "t"}
QA_HEAD = {"X-Participant": QA, "X-Admin": "t"}


def _claude_rows(participant: str, *, with_stamp: bool = True) -> list[dict]:
    """A Claude transcript: the whoami result naming the participant, a harvest Skill call, one lesson, close_self."""
    whoami = {"ok": True, "value": {"participant": {"id": participant, "role": "qa"}}}

    def asst(ts, mid, tools=()):
        content = [{"type": "tool_use", "name": n, "input": i} for n, i in tools] or [{"type": "text", "text": "x"}]
        row = {"type": "assistant", "message": {"id": mid, "content": content,
                                                "usage": {"input_tokens": 10, "cache_creation_input_tokens": 100,
                                                          "cache_read_input_tokens": 1000, "output_tokens": 5}}}
        if with_stamp:
            row["timestamp"] = ts
        return row
    return [{"type": "user", "timestamp": "2026-09-24T09:59:00Z",
             "message": {"content": [{"type": "tool_result", "content": json.dumps(whoami)}]}},
            asst("2026-09-24T10:01:00Z", "m1", [("Skill", {"skill": "harvest"})]),
            asst("2026-09-24T10:02:00Z", "m2", [("mcp__edp8__record_lesson", {})]),
            asst("2026-09-24T10:03:00Z", "m3", [("mcp__edp8__close_self", {})])]


def _write(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def _codex_rows() -> list[dict]:
    def usage(ts, inp, out):
        return {"ts": ts, "msg": {"method": "thread/tokenUsage/updated", "params": {"threadId": "t1", "tokenUsage": {
            "total": {"inputTokens": inp, "cachedInputTokens": 0, "outputTokens": out, "reasoningOutputTokens": 0,
                      "totalTokens": inp + out}}}}}

    def item(ts, **it):
        return {"ts": ts, "msg": {"method": "item/started", "params": {"item": it}}}
    return [usage(5, 1000, 50),
            item(10, type="commandExecution", command="Get-Content .claude/skills/harvest/SKILL.md"),
            item(11, type="mcpToolCall", tool="record_lesson", arguments={}),
            usage(12, 1600, 90),
            item(13, type="mcpToolCall", tool="close_self", arguments={}),
            usage(20, 9000, 900)]


@pytest.fixture
def host(tmp_path, monkeypatch):
    """An installed-style host: <tmp>/data/{claude-pool,logs,agent-home}, nothing under the old repo layout."""
    data = tmp_path / "data"
    for name in ("EDP8_HARVEST_LOG_ROOTS", "EDP_HOME", "EDP8_HOME", "EDP_CLAUDE_CONFIG_DIR", "EDP_POOL_SHELL_LOG_DIR",
                 "EDP8_BIND", "EDP8_TOKENS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("EDP_CONFIG_DIR", str(tmp_path / "config"))  # an installed host's config.toml (public_url) must not leak in
    monkeypatch.setenv("EDP8_DATA", str(data))
    monkeypatch.setenv("EDP_AGENT_HOME", str(data / "agent-home"))
    monkeypatch.setenv("EDP_CLAUDE_CONFIG_DIR", str(data / "claude-pool"))
    monkeypatch.setenv("EDP_POOL_SHELL_LOG_DIR", str(data / "logs"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "userhome"))
    monkeypatch.setenv("HOME", str(tmp_path / "userhome"))
    return {"tmp": tmp_path, "data": data}


# ----------------------------------------------------------------------------- where the logs live
def test_claude_transcript_under_the_installed_pool_projects_is_found(host):
    log = _write(host["data"] / "claude-pool" / "projects" / "C--Users-x-data-agent-home" / "abc.jsonl", _claude_rows(QA))
    out = hc.compute(QA)
    assert out["seat"] == "claude" and out["log"] == log.name
    assert out["window"] == {"start": "2026-09-24T10:01:00Z", "end": "2026-09-24T10:03:00Z"}
    assert out["tokens"]["calls"] == 3 and out["tokens"]["output_tokens"] == 15


def test_claude_transcript_under_the_old_edp_pool_layout_is_found(host, monkeypatch):
    old_v8 = host["tmp"] / "old" / "v8"
    monkeypatch.setenv("EDP_AGENT_HOME", str(old_v8))
    monkeypatch.setenv("EDP_CLAUDE_CONFIG_DIR", str(host["tmp"] / "elsewhere"))
    _write(host["tmp"] / "old" / "edp-pool" / ".claude-pool" / "projects" / "k" / "old.jsonl", _claude_rows(QA))
    assert hc.compute(QA)["seat"] == "claude"


def test_claude_transcript_in_the_users_own_claude_store_is_found(host):
    _write(host["tmp"] / "userhome" / ".claude" / "projects" / "k" / "u.jsonl", _claude_rows(QA))
    assert hc.compute(QA)["seat"] == "claude"


def test_codex_seat_mirror_under_the_installed_shell_logs_is_found(host):
    _write(host["data"] / "logs" / "codex" / f"codex-seat.{CODEX_QA}.jsonl", _codex_rows())
    out = hc.compute(CODEX_QA)
    assert out["seat"] == "codex" and out["log"] == f"codex-seat.{CODEX_QA}.jsonl"
    assert (out["tokens"]["inputTokens"], out["tokens"]["outputTokens"]) == (600, 40)


def test_codex_seat_mirror_in_the_platform_log_dir_is_found(host, monkeypatch):
    logs = host["tmp"] / "platform-logs"
    monkeypatch.setenv("EDP_POOL_SHELL_LOG_DIR", str(host["tmp"] / "unused"))
    monkeypatch.setattr(hc.settings, "logs_dir", lambda: logs)
    _write(logs / "codex" / f"codex-seat.{CODEX_QA}.jsonl", _codex_rows())
    assert hc.compute(CODEX_QA)["seat"] == "codex"


def test_the_newest_log_wins_across_roots(host):
    old = _write(host["data"] / "claude-pool" / "projects" / "k" / "old.jsonl", _claude_rows(QA))
    new = _write(host["data"] / "claude-pool" / "projects" / "k" / "new.jsonl", _claude_rows(QA))
    os.utime(old, (1, 1))
    assert hc.compute(QA)["log"] == new.name


def test_no_log_names_every_root_it_searched(host):
    with pytest.raises(hc.NoLog) as e:
        hc.compute("qa.nobody")
    text = str(e.value)
    for root in (host["data"] / "claude-pool" / "projects", host["data"] / "logs", host["tmp"] / "userhome" / ".claude" / "projects"):
        assert str(root) in text, (root, text)


def test_explicit_log_roots_still_override_every_default(host, monkeypatch):
    _write(host["data"] / "claude-pool" / "projects" / "k" / "a.jsonl", _claude_rows(QA))
    only = host["tmp"] / "only"
    only.mkdir()
    monkeypatch.setenv("EDP8_HARVEST_LOG_ROOTS", str(only))
    with pytest.raises(hc.NoLog) as e:
        hc.compute(QA)
    assert str(only) in str(e.value) and "claude-pool" not in str(e.value)


# ----------------------------------------------------------------------------- the route never answers a plain-text 500
@pytest.fixture
def api(host):
    board = Board(Store(":memory:"))
    tc = TestClient(create_app(board, admin_token="t"), raise_server_exceptions=False)
    assert tc.post("/v1/participants", json={"type": "agent", "role": "qa", "handle": QA, "id": QA},
                   headers=ADMIN).json()["ok"]
    return tc


def _get(api, **params):
    return api.get("/v1/harvest/cost", params={"participant_id": QA, **params}, headers=QA_HEAD)


def test_route_serves_the_installed_claude_transcript(api, host):
    _write(host["data"] / "claude-pool" / "projects" / "k" / "a.jsonl", _claude_rows(QA))
    r = _get(api)
    assert r.status_code == 200 and r.json()["value"]["tokens"]["calls"] == 3, r.text


def test_route_missing_log_is_json_not_found_with_the_roots(api, host):
    r = _get(api)
    body = r.json()
    assert r.status_code == 404 and body["error"]["code"] == "not_found"
    assert str(host["data"] / "claude-pool" / "projects") in body["error"]["message"]


@pytest.mark.parametrize("since", ["yesterday", "2026-13-45T99:00:00Z", "10:00"])
def test_route_bad_since_is_a_json_400(api, host, since):
    _write(host["data"] / "claude-pool" / "projects" / "k" / "a.jsonl", _claude_rows(QA))
    r = _get(api, since=since)
    assert r.headers["content-type"].startswith("application/json"), r.text
    body = r.json()
    assert r.status_code == 400 and not body["ok"] and "since" in body["error"]["message"], body


def test_route_log_rows_without_timestamps_do_not_crash(api, host):
    _write(host["data"] / "claude-pool" / "projects" / "k" / "a.jsonl", _claude_rows(QA, with_stamp=False))
    r = _get(api, since="2026-09-24T10:00:00Z")
    assert r.headers["content-type"].startswith("application/json"), r.text
    assert r.status_code == 200 and r.json()["value"]["tokens"]["calls"] == 0, r.text


def test_route_log_rows_with_a_garbled_timestamp_do_not_crash(api, host):
    rows = _claude_rows(QA)
    rows[2]["timestamp"] = "not-a-time"
    _write(host["data"] / "claude-pool" / "projects" / "k" / "a.jsonl", rows)
    r = _get(api)
    assert r.headers["content-type"].startswith("application/json"), r.text
    assert r.status_code == 200, r.text


def test_route_unreadable_log_is_a_json_error(api, host, monkeypatch):
    log = _write(host["data"] / "claude-pool" / "projects" / "k" / "a.jsonl", _claude_rows(QA))
    real = Path.read_text

    def boom(self, *a, **kw):
        if self == log:
            raise PermissionError("locked by the seat")
        return real(self, *a, **kw)
    monkeypatch.setattr(Path, "read_text", boom)
    r = _get(api)
    assert r.headers["content-type"].startswith("application/json"), r.text
    assert not r.json()["ok"]
