"""S3 — parity oracle: Claude-side capture from a real session JSONL, normaliser, diff engine."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
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


def test_cli_list_cases(tmp_path):
    result = subprocess.run(
        [sys.executable, str(Path(po.__file__).resolve()), "--list-cases"],
        cwd=tmp_path, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    assert result.stdout == "".join(f"{name}\n" for name, _ in po.CASES)
    assert result.stderr == ""
    assert list(tmp_path.iterdir()) == []


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


def test_wording_equivalence_collapses_claude_and_our_texts():
    """Owner m-2d7ef9243d: the seat speaks our words; the oracle exempts wording only (guides/harness-parity/wording.json)."""
    pairs = [
        ("Monitor started (task bfgghodgn, timeout 60000ms). You will be notified on each event. Keep working — do not poll "
         "or sleep. Events may arrive while you are waiting for the user — an event is not their reply.",
         "Watch armed (task bfgghodgn; stops after 60000ms). Each event reaches you as a notification while you carry on; "
         "no polling, no sleeping. A notification is a background event and never the user's reply, even one that lands "
         "while you wait for them."),
        ("Cancelled job 64de3444.", "Job 64de3444 cancelled."),
        ("Task bfgghodgn not found", "No such task: bfgghodgn"),
        ("[6 events suppressed — output rate too high. Consider using TaskStop to restart this monitor with a more selective filter.]",
         "[6 events dropped: this watch emits faster than the limit. Stop it with TaskStop and re-arm it with a narrower filter.]"),
    ]
    for claude, ours in pairs:
        assert po.canon(claude) == po.canon(ours), (po.canon(claude), po.canon(ours))
    assert po.canon(pairs[0][0]) == "<W:MONITOR_STARTED_TIMEOUT 60000>"
    # a number or structure change is NOT exempt
    assert po.canon("Watch armed (task bfgghodgn; stops after 5000ms). Each event reaches you as a notification while you carry on; "
                    "no polling, no sleeping. A notification is a background event and never the user's reply, even one that lands "
                    "while you wait for them.") != po.canon(pairs[0][0])


def test_codex_live_trace_has_zero_diffs_against_claude():
    """s-10a2b1f9ec c-661956fad0: the live codex app-server run (2026-09-22, gpt-6-astra, codex-cli 0.156.0) passes
    every case the Pi seat passes; capture_codex re-derives the stored trace from the trimmed raw mirror."""
    ref = Path(__file__).resolve().parents[1] / "tests" / "pi_ext" / "oracle_traces"
    claude = json.loads((ref / "claude_trace_final.json").read_text(encoding="utf-8"))
    pi = json.loads((ref / "pi_trace_final.json").read_text(encoding="utf-8"))
    codex = po.capture_codex(ref / "codex_raw" / "codex-seat.cases.jsonl")
    assert [po.project(e) for e in po.case_only(codex)] == \
        [po.project(e) for e in po.case_only(json.loads((ref / "codex_trace_final.json").read_text(encoding="utf-8")))]
    assert po.diff(claude, pi) == [] and po.diff(claude, codex) == []
    att = [e for e in codex if e["kind"] == "notification_attached"]
    assert {e["attached_to"] for e in att} == {"bash", "Monitor", "TaskStop"}  # steer-after-command case included
    assert any(e["kind"] == "cron_fire" and e["text"] == "ORACLE-ONESHOT" for e in codex)


def test_capture_codex_shapes():
    import tempfile
    rows = [
        {"ts": 1, "dir": "out", "msg": {"method": "turn/start", "params": {"input": [{"text": "You are running a parity probe. x"}]}}},
        {"ts": 2, "dir": "in", "msg": {"id": 7, "method": "item/tool/call", "params": {"tool": "Monitor", "arguments": {"command": "c"}}}},
        {"ts": 3, "dir": "out", "msg": {"id": 7, "result": {"contentItems": [{"type": "inputText", "text": "Watch armed (task abcdefghi).\n\n<system-reminder>\nA\n</system-reminder>"}], "success": True}}},
        {"ts": 4, "dir": "in", "msg": {"method": "item/started", "params": {"item": {"type": "commandExecution"}}}},
        {"ts": 5, "dir": "out", "msg": {"method": "turn/steer", "params": {"input": [{"text": "<system-reminder>\nB\n</system-reminder>\n\n<system-reminder>\nC\n</system-reminder>"}]}}},
        {"ts": 6, "dir": "out", "msg": {"method": "turn/start", "params": {"input": [{"text": "<system-reminder>\nD\n</system-reminder>\n<system-reminder>\nE\n</system-reminder>"}]}}},
        {"ts": 7, "dir": "out", "msg": {"method": "turn/start", "params": {"input": [{"text": "ORACLE-X"}]}}},
    ]
    # every steer / start is ACCEPTED (its response has `result`), except one refused steer, which must not count
    for r in rows:
        if r["msg"].get("method") in ("turn/start", "turn/steer"):
            r["msg"]["id"] = r["ts"]
    rows += [{"ts": 9, "dir": "in", "msg": {"id": r["ts"], "result": {}}} for r in list(rows)
             if r["msg"].get("method") in ("turn/start", "turn/steer")]
    rows += [{"ts": 10, "dir": "in", "msg": {"method": "item/started", "params": {"item": {"type": "commandExecution"}}}},
             {"ts": 11, "dir": "out", "msg": {"id": 99, "method": "turn/steer", "params": {"input": [{"text": "<system-reminder>\nLOST\n</system-reminder>"}]}}},
             {"ts": 12, "dir": "in", "msg": {"id": 99, "error": {"message": "no active turn"}}}]
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "m.jsonl"
        p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        tr = po.capture_codex(p)
    assert not any("LOST" in e.get("text", "") for e in tr)
    assert [(e["kind"], e.get("attached_to")) for e in tr] == [
        ("tool_use", None), ("tool_result", None), ("notification_attached", "Monitor"),
        ("notification_attached", "bash"), ("notification_attached", "bash"),
        ("notification_standalone", None), ("notification_standalone", None), ("cron_fire", None)]
    assert tr[1]["text"] == "Watch armed (task abcdefghi)." and tr[2]["text"] == "<system-reminder>\nA\n</system-reminder>"
    assert tr[4]["text"] == "<system-reminder>\nC\n</system-reminder>" and tr[6]["text"].endswith("E\n</system-reminder>")
