"""S4 (s-733de6e29f, criterion c-dfd1a8dc50): the edp-terse output rule on a live codex seat, HERMETIC stack.

Reuses drill_codex_seat.py's stack (its own board + MCP proxy on free ports, scratch DB, token mode, no pool)
and runs one qa seat under a real `codex app-server` in monitor mode (the native TUI under ConPTY, so the
drill can type `/compact` into it the way an owner would). Three phases, each with one CHANGED wake (a board
question the seat must answer on the thread) and one UNCHANGED wake (a one-shot heartbeat cron fire after
which context_delta has nothing new):

    fresh     after boot
    compact   after `/compact` typed into the TUI (thread/compacted seen on the runner's connection)
    resume    after a runner crash + EDP_CODEX_RESUME=1 (thread/resume of the same thread id)

A wake's text is every agentMessage the model produced in that turn (item/completed, by turnId). Verdict:
an unchanged wake ends with ZERO text; a changed wake's final message is at most one line; every wake's
board MCP calls succeed. Everything lands in <out>/drill.json (+ the runner mirror in <out>/logs).

    edp-pool/.venv/Scripts/python.exe scripts/drill_codex_output_rule.py --out .logs/codex-output-drill
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("drill_codex_seat", HERE / "drill_codex_seat.py")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)
base.ROLE = "qa"  # qa runs read-only


def _p(r: dict) -> dict:
    return (r.get("msg") or {}).get("params") or {}


class OutputDrill(base.Drill):
    def __init__(self, out: Path, effort: str, model: str | None):
        super().__init__(out, effort, model, tui=True)
        self.log["story"] = "s-733de6e29f"
        self.wakes: list[dict] = []

    # ---------------------------------------------------------------- turn text
    def turn_of(self, pred) -> str | None:
        """The turnId that carried the first runner turn/start or turn/steer whose params satisfy `pred`
        (from its response: turn/start answers {turn: {id}}, turn/steer {turnId})."""
        rows = self.mirror()
        for n, r in enumerate(rows):
            m = r.get("msg") or {}
            if r.get("dir") == "out" and m.get("method") in ("turn/start", "turn/steer") and pred(json.dumps(m.get("params"))):
                # the response AFTER this request: a resumed runner restarts its JSON-RPC ids at 1
                for q in rows[n + 1:]:
                    qm = q.get("msg") or {}
                    if q.get("dir") == "in" and qm.get("id") == m.get("id") and "result" in qm:
                        res = qm["result"] or {}
                        return res.get("turnId") or (res.get("turn") or {}).get("id")
        return None

    def idle(self) -> bool:
        """No turn in flight: every turn/started has its turn/completed."""
        started, done = set(), set()
        for r in self.mirror():
            m = r.get("msg") or {}
            if r.get("dir") == "in" and m.get("method") in ("turn/started", "turn/completed"):
                (started if m["method"] == "turn/started" else done).add((_p(r).get("turn") or {}).get("id"))
        return bool(started) and started <= done

    def settle(self) -> None:
        """Wait for the seat to go idle (so the next wake is its own turn, not a steer into a running one)."""
        self.wait_for(lambda: self.idle() and (time.sleep(8) or self.idle()), 600, poll=3.0)

    def turn_done(self, turn_id: str) -> bool:
        return any(r.get("dir") == "in" and (r.get("msg") or {}).get("method") == "turn/completed"
                   and (_p(r).get("turn") or {}).get("id") == turn_id for r in self.mirror())

    def turn_items(self, turn_id: str) -> list[dict]:
        return [_p(r).get("item") or {} for r in self.mirror() if r.get("dir") == "in"
                and (r.get("msg") or {}).get("method") == "item/completed" and _p(r).get("turnId") == turn_id]

    def measure(self, phase: str, kind: str, turn_id: str | None) -> dict:
        if turn_id:
            self.wait_for(lambda: self.turn_done(turn_id), 600, poll=2.0)
        items = self.turn_items(turn_id) if turn_id else []
        texts = [str(i.get("text") or "") for i in items if i.get("type") == "agentMessage"]
        texts = [t for t in texts if t.strip()]
        final = texts[-1] if texts else ""
        lines = [ln for ln in final.splitlines() if ln.strip()]
        mcp = [i for i in items if i.get("type") == "mcpToolCall"]
        mcp_failed = [f"{i.get('tool')}: {str(i.get('error'))[:120]}" for i in mcp
                      if i.get("status") not in (None, "completed") or i.get("error")]
        delta = [i for i in mcp if i.get("tool") == "context_delta"]
        if kind == "unchanged":
            passed = bool(turn_id) and not texts
        else:
            passed = bool(turn_id) and len(lines) <= 1
        passed = passed and not mcp_failed
        row = {"phase": phase, "kind": kind, "turn": turn_id, "passed": passed, "agent_texts": texts,
               "final_lines": len(lines), "mcp_calls": [i.get("tool") for i in mcp], "mcp_failed": mcp_failed,
               "context_delta_results": [str((i.get("result") or {}))[:600] for i in delta]}
        self.wakes.append(row)
        self.step(f"{phase}_{kind}_wake", **{k: row[k] for k in ("passed", "turn", "final_lines", "mcp_calls", "mcp_failed")},
                  texts=[t[:200] for t in texts])
        return row

    # ---------------------------------------------------------------- wakes
    def changed_wake(self, phase: str, word: str) -> dict:
        self.settle()
        seq = self.last_seq()
        q = self.say(f"Drill ({phase}): reply on this thread with a message whose text contains {word}.")
        self.step(f"{phase}_changed_sent", message=q["id"])
        self.wait_for(lambda: [m for m in self.seat_messages(seq) if word in m.get("text", "")], 600)
        tid = self.wait_for(lambda: self.turn_of(lambda s: q["id"] in s), 60, poll=2.0)
        return self.measure(phase, "changed", tid)

    def unchanged_wake(self, phase: str) -> dict:
        """A one-shot heartbeat: the steer asking for it is itself a changed wake (measured too); the fire is
        the unchanged one — the owner says nothing between the two."""
        self.settle()
        fire = dt.datetime.now() + dt.timedelta(minutes=3)
        if fire.minute in (0, 30):
            fire += dt.timedelta(minutes=1)
        cron = f"{fire.minute} {fire.hour} {fire.day} {fire.month} *"
        marker = f"HEARTBEAT {phase.upper()}"
        q = self.say(f"Drill ({phase}): call CronCreate with cron \"{cron}\", recurring false, and prompt "
                     f"\"{marker}: context_delta(cursor=<your last cursor>); act only on what changed.\"", kind="steer")
        self.step(f"{phase}_heartbeat_steer", message=q["id"], cron=cron)
        tid = self.wait_for(lambda: self.turn_of(lambda s: q["id"] in s), 120, poll=2.0)
        self.measure(phase, "changed-steer", tid)
        self.settle()
        # the fire is a BARE-prompt turn/start (input text starts with the marker); the steer only quotes it
        fire_tid = self.wait_for(lambda: self.turn_of(lambda s: f'"text": "{marker}' in s), 420, poll=3.0)
        return self.measure(phase, "unchanged", fire_tid)

    def compact(self) -> bool:
        self.settle()
        t = time.time()
        if "Update now" in self.screen("seat"):
            self.step("compact_typed", passed=False, refused="update modal on screen")
            return False
        seat = self.procs["seat"]
        seat.write("/compact")
        time.sleep(0.8)
        seat.write("\r")
        self.step("compact_typed", text="/compact")

        def compacted():
            return [r for r in self.mirror() if r.get("ts", 0) >= t and r.get("dir") == "in" and (
                (r.get("msg") or {}).get("method") == "thread/compacted"
                or (_p(r).get("item") or {}).get("type") == "contextCompaction")]
        got = self.wait_for(compacted, 300, poll=2.0)
        self.log["result"]["compaction"] = {"passed": bool(got), "seen": [
            {"ts": r.get("ts"), "method": (r["msg"] or {}).get("method"), "item": (_p(r).get("item") or {}).get("type"),
             "turn": _p(r).get("turnId")} for r in (got or [])][:4]}
        self.step("compact_done", passed=bool(got))
        return bool(got)

    def resume_turn(self, t0: float) -> dict:
        """The resume wake itself (the runner's `You were resumed` turn) is a changed wake."""
        tid = self.wait_for(lambda: self.turn_of(lambda s: "You were resumed" in s), 300, poll=2.0)
        return self.measure("resume", "changed-resume", tid)

    # ---------------------------------------------------------------- run
    def run(self) -> int:
        self.out.mkdir(parents=True, exist_ok=True)
        try:
            if not self.up():
                return 2
            ok = self.boot()
            ok = ok and all(w["passed"] for w in (self.changed_wake("fresh", "KIWI-1"), self.unchanged_wake("fresh")))
            ok = ok and self.compact()
            ok = ok and all(w["passed"] for w in (self.changed_wake("compact", "KIWI-2"), self.unchanged_wake("compact")))
            t0 = time.time()
            ok = ok and self.resume()  # runner crash + thread/resume of the same thread (drill_codex_seat)
            if ok:
                self.resume_turn(t0)
                self.changed_wake("resume", "KIWI-3")
                self.unchanged_wake("resume")
            ok = ok and all(w["passed"] for w in self.wakes)
            self.log["result"]["wakes"] = self.wakes
            self.log["result"]["token_never_on_argv"] = not any(self.seat_tok in a for argv in self.argvs for a in argv)
            ok = ok and self.log["result"]["token_never_on_argv"]
            self.log["result"]["all_passed"] = ok
            return 0 if ok else 1
        finally:
            self.log["result"]["wakes"] = self.wakes
            self.log["finished"] = base.now()
            self.save()
            for name in list(self.procs)[::-1]:
                p = self.procs[name]
                if isinstance(p, base.PtySeat):
                    if p.poll() is None:
                        p.kill()
                else:
                    base.kill_tree(p)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(base.V8 / ".logs" / "codex-output-drill"))
    ap.add_argument("--effort", default="low")
    ap.add_argument("--model", default=None)
    a = ap.parse_args(argv)
    out = Path(a.out).resolve()
    if out.exists() and any(out.iterdir()):
        out = out.with_name(out.name + "-" + dt.datetime.now().strftime("%Y%m%dT%H%M%S"))
    return OutputDrill(out, a.effort, a.model).run()


if __name__ == "__main__":
    sys.exit(main())
