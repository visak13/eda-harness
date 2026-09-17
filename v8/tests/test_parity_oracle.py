"""S3 — parity oracle: Claude-side capture from a real session JSONL, normaliser, diff engine."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("parity_oracle", Path(__file__).resolve().parents[1] / "scripts" / "parity_oracle.py")
po = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(po)

SESSION = Path(r"C:\Projects\Learning\eda-base3\edp-pool\.claude-pool\projects\C--Projects-Learning-eda-base3-v8\7edf0320-390f-496d-8427-c2b1ef4aff80.jsonl")


def test_normalise_ids_paths_times():
    s = ("Monitor started (task bfgghodgn, persistent — runs until TaskStop). <task-id>bneh42buc</task-id> "
         "Scheduled recurring job b2c55175 (Every 30 minutes). Cancelled job 64de3444. toolu_01X1bkSj9My6iJtNpfVuicQL "
         r"C:\Users\x\AppData\Local\Temp\claude\p\s\tasks\bneh42buc.output 2026-09-14T15:25:12.371Z")
    n = po.normalise(s)
    assert "bfgghodgn" not in n and "bneh42buc" not in n and "b2c55175" not in n and "64de3444" not in n
    assert "toolu_01" not in n and "<output-file>" in n and "<ts>" in n
    assert n.startswith("Monitor started (task <task-id>, persistent")


@pytest.mark.skipif(not SESSION.is_file(), reason="reference session JSONL not on this host")
def test_capture_claude_reference_session():
    tr = po.capture_claude(SESSION)
    kinds = {e["kind"] for e in tr}
    assert {"tool_use", "tool_result", "notification_standalone", "notification_attached", "cron_fire"} <= kinds
    uses = [e for e in tr if e["kind"] == "tool_use"]
    assert {e["tool"] for e in uses} == set(po.PARITY_TOOLS)
    res = [e for e in tr if e["kind"] == "tool_result" and e["tool"] == "CronDelete"]
    assert res and po.normalise(res[0]["text"]) == "Cancelled job <job-id>."
    fires = [e for e in tr if e["kind"] == "cron_fire"]
    assert fires and all(e["meta"]["isMeta"] for e in fires)
    att = [e for e in tr if e["kind"] == "notification_attached"]
    assert att and all(e["text"].startswith("<system-reminder>\n[SYSTEM NOTIFICATION - NOT USER INPUT]") for e in att)


def test_diff_zero_on_identical_and_reports_change():
    a = [{"kind": "tool_result", "tool": "CronDelete", "text": "Cancelled job 64de3444."}]
    b = [{"kind": "tool_result", "tool": "CronDelete", "text": "Cancelled job 1a2b3c4d."}]
    assert po.diff(a, b) == []
    c = [{"kind": "tool_result", "tool": "CronDelete", "text": "Canceled job 1a2b3c4d."}]
    assert any(line.startswith("+") and "Canceled" in line for line in po.diff(a, c))


def test_cli_cases_and_both(capsys, tmp_path):
    assert po.main(["--cases"]) == 0
    assert "cron_expiry_accelerated" in capsys.readouterr().out
    # --both without a Claude reference cannot compare anything → 2 (never a silent pass)
    assert po.main(["--both", "--claude-ref", str(tmp_path / "missing.json")]) == 2


def test_diff_refuses_empty_and_keeps_errors_and_receiving_tool():
    # qa A6: two empty traces are a failure, not a pass
    assert po.diff([], []) and po.diff([], [])[0].startswith("EMPTY TRACE")
    ok = [{"kind": "tool_result", "tool": "CronList", "text": "No cron jobs scheduled."}]
    err = [{"kind": "tool_result", "tool": "CronList", "text": "INTERNAL ERROR: scheduler unavailable"}]
    assert any("INTERNAL ERROR" in ln for ln in po.diff(ok, err))
    flagged = [{"kind": "tool_result", "tool": "CronList", "text": "No cron jobs scheduled.", "is_error": True}]
    assert any("[error]" in ln for ln in po.diff(ok, flagged))
    # an attached notification names the tool result that carried it
    mon = {"kind": "tool_result", "tool": "Monitor", "text": "Monitor started (task abcdefghi, timeout 300000ms)."}
    a = [mon, {"kind": "notification_attached", "text": "<task-id>abcdefghi</task-id>", "attached_to": "Bash"}]
    b = [mon, {"kind": "notification_attached", "text": "<task-id>abcdefghi</task-id>", "attached_to": "bash"}]
    c = [mon, {"kind": "notification_attached", "text": "<task-id>abcdefghi</task-id>", "attached_to": "Monitor"}]
    assert po.diff(a, b) == []  # Bash vs bash is the harness's naming, not a delivery difference
    assert any("to=monitor" in ln for ln in po.diff(a, c))


def test_stored_reference_traces_carry_identity():
    ref = Path(__file__).resolve().parents[1] / "tests" / "pi_ext" / "oracle_traces"
    for name in ("claude_trace_final.json", "pi_trace_final.json"):
        trace = json.loads((ref / name).read_text(encoding="utf-8"))
        att = [e for e in trace if e["kind"] == "notification_attached"]
        assert att and all(e.get("attached_to") for e in att), name
