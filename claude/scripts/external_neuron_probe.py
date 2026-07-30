"""External-neuron PARITY PROBE — drives the ENTIRE neuron lifecycle over
raw stdio MCP, exactly as an external harness (codex/Sol) does, and asserts
every leg. This is the executable answer to "can a non-Claude neuron do
everything a Claude neuron does?" for the MCP-side surface:

  A. bind + neuron toolset
  B. author:      start_recipe -> curiosity round-trip -> record_outcome
                  -> comprehension signoff -> add_step (with depends_on)
  C. drive:       next_action(all_ready) step-frontier wave
  D. spawn:       pool_spawn_planner per wave instruction
  E. comms (bi):  child question -> check_inbox -> reply routes back
  F. close:       record_step_result -> mark_outcome_met -> close_recipe

Runs against a TEMP agent home + the stub pool/broker (no real shells, no
pollution of .recipes) — the tool code paths are the production ones; only
the process/transport edges are stubbed. Run:

    uv run python scripts/external_neuron_probe.py
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

CLAUDE = Path(__file__).resolve().parents[1]
FAILS: list[str] = []


class Mcp:
    def __init__(self, home: str):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("CLAUDE")}
        env.update({"EDP_MCP_BACKEND": "stub", "EDP_ROLE": "neuron",
                    "EDP_AGENT_HOME": home, "EDP_LOG_DIR": home})
        self.p = subprocess.Popen(
            ["uv", "run", "--project", str(CLAUDE), "python", "-m",
             "edp_claude.mcp_server"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8", env=env)
        self._id = 0
        self._send({"jsonrpc": "2.0", "id": self._next(), "method":
                    "initialize", "params": {
                        "protocolVersion": "2024-11-05", "capabilities": {},
                        "clientInfo": {"name": "parity-probe",
                                       "version": "0"}}})
        self.init = self._read()
        self._send({"jsonrpc": "2.0",
                    "method": "notifications/initialized"})

    def _next(self):
        self._id += 1
        return self._id

    def _send(self, m):
        self.p.stdin.write(json.dumps(m) + "\n")
        self.p.stdin.flush()

    def _read(self):
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise SystemExit("MCP server died mid-probe")
            line = line.strip()
            if line.startswith("{"):
                return json.loads(line)

    def tools(self) -> set:
        self._send({"jsonrpc": "2.0", "id": self._next(),
                    "method": "tools/list"})
        return {t["name"] for t in self._read()["result"]["tools"]}

    def call(self, name: str, **args) -> dict:
        self._send({"jsonrpc": "2.0", "id": self._next(),
                    "method": "tools/call",
                    "params": {"name": name, "arguments": args}})
        r = self._read()["result"]
        payload = json.loads(r["content"][0]["text"]) if r.get("content") \
            else {}
        return payload


def check(label: str, ok: bool, detail: str = ""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}"
          + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(f"{label}: {detail}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="neuron-probe-",
                                     ignore_cleanup_errors=True) as home:
        m = Mcp(home)

        print("A. bind + toolset")
        names = m.tools()
        need = {"start_recipe", "record_outcome", "consult_curiosity",
                "record_comprehension_signoff", "add_step", "next_action",
                "reconcile", "pool_spawn_planner", "check_inbox", "reply",
                "broker_send", "record_step_result", "mark_outcome_met",
                "close_recipe", "get_recipe_digest", "get_guide",
                "fold_decisions", "pool_resume_planner", "record_context"}
        check("neuron surface serves every lifecycle verb",
              need <= names, f"missing: {sorted(need - names)}")

        print("B. author — recipe, curiosity, outcomes, signoff, steps")
        r = m.call("start_recipe", goal="probe: two independent widgets",
                   domain="software_engineering")
        rid = (r.get("data") or {}).get("recipe_id") or r.get("recipe_id")
        check("start_recipe", bool(rid), json.dumps(r)[:200])

        r = m.call("consult_curiosity",
                   decision="build two widgets in parallel",
                   context="probe", handle=rid)
        check("consult_curiosity (spawns via pool)",
              r.get("ok", True) is not False, json.dumps(r)[:200])
        # the curiosity CLEAR arrives as a broker message; reconcile flips
        # the gate — this also proves inbound broker->neuron flow.
        m.call("broker_send", to=rid, kind="answer", from_="curiosity-probe",
               body={"clear": True, "status": "done"})
        r = m.call("reconcile", handle=rid, handle_type="recipe")
        check("curiosity clear converged via broker + reconcile",
              r.get("ok", True) is not False, json.dumps(r)[:200])

        r = m.call("record_outcome", recipe_id=rid,
                   description="both widgets exist",
                   verification="files present")
        ok_outcome = r.get("ok", True) is not False and not r.get("refused")
        check("record_outcome", ok_outcome, json.dumps(r)[:300])

        r = m.call("record_comprehension_signoff", recipe_id=rid,
                   user_quote="probe operator: proceed exactly as briefed")
        check("comprehension signoff", r.get("ok", True) is not False,
              json.dumps(r)[:300])

        s1 = m.call("add_step", recipe_id=rid, description="build widget A",
                    execution="spawn_planner")
        s2 = m.call("add_step", recipe_id=rid, description="build widget B",
                    execution="spawn_planner")
        sid1 = (s1.get("data") or {}).get("step_id") or s1.get("step_id")
        sid2 = (s2.get("data") or {}).get("step_id") or s2.get("step_id")
        check("add_step x2 (independent)", bool(sid1 and sid2),
              json.dumps((s1, s2))[:300])
        s3 = m.call("add_step", recipe_id=rid, description="integrate A+B",
                    execution="spawn_planner", depends_on=[sid1, sid2])
        check("add_step with depends_on", bool(
            (s3.get("data") or {}).get("step_id") or s3.get("step_id")),
            json.dumps(s3)[:300])
        bad = m.call("add_step", recipe_id=rid, description="typo dep",
                     execution="spawn_planner", depends_on=["s99"])
        check("bogus depends_on refused",
              bad.get("ok") is False or "unknown step" in json.dumps(bad),
              json.dumps(bad)[:300])

        print("C+D. drive — plain next_action advances, wave covers the rest")
        # The documented order: a wave while COMPREHENDING is an empty no-op
        # (comprehension is never bypassable); the PLAIN next_action advances
        # the recipe into PLANNING and hands the FIRST dispatch; the wave
        # then dispatches the REST of the ready frontier.
        r = m.call("next_action", handle=rid, handle_type="recipe")
        data = r.get("data") or r
        first_kind = data.get("kind")
        first_sid = (data.get("args") or {}).get("step_id")
        check("plain next_action advances to the first dispatch",
              first_kind == "spawn_planner" and bool(first_sid),
              json.dumps(data)[:400])
        spawned = 0
        if first_sid:
            rr = m.call("pool_spawn_planner", recipe_id=rid,
                        step_id=first_sid)
            if rr.get("ok", True) is not False:
                spawned += 1
        r = m.call("next_action", handle=rid, handle_type="recipe",
                   all_ready=True)
        data = r.get("data") or r
        wave = data.get("actions") or []
        wave_sids = [(w.get("args") or {}).get("step_id") for w in wave]
        check("wave returns the REST of the frontier (s3 held back)",
              len(wave) == 1 and "s3" not in wave_sids,
              json.dumps(data)[:400])
        for w in wave:
            sid = (w.get("args") or {}).get("step_id")
            rr = m.call("pool_spawn_planner", recipe_id=rid, step_id=sid)
            if rr.get("ok", True) is not False:
                spawned += 1
        check("pool_spawn_planner per instruction (both independents)",
              spawned == 2, f"spawned {spawned}/2")

        print("E. comms — child question in, reply routed back")
        q = m.call("broker_send", to=rid, kind="question",
                   from_=f"{rid}-{sid1}",
                   body={"question": "which color scheme?"})
        inbox = m.call("check_inbox", handle=rid)
        msgs = (inbox.get("data") or inbox).get("messages") or []
        qmsg = next((x for x in msgs if x.get("kind") == "question"), None)
        check("child question lands in neuron inbox", qmsg is not None,
              json.dumps(inbox)[:300])
        if qmsg:
            rr = m.call("reply", msg_id=qmsg["msg_id"],
                        body={"answer": "midnight blue"})
            check("reply routes back to the child",
                  rr.get("ok", True) is not False, json.dumps(rr)[:200])
            back = m.call("check_inbox", handle=f"{rid}-{sid1}")
            bmsgs = (back.get("data") or back).get("messages") or []
            check("child receives the answer (bidirectional proven)",
                  any(x.get("kind") == "answer" for x in bmsgs),
                  json.dumps(back)[:300])

        print("G. reground after compaction — the epoch seam, over MCP")
        # An external neuron that lost its context (harness compaction /
        # resumed session) echoes a stale/unknown epoch and MUST receive the
        # full reground block — this is the Claude SessionStart(compact)
        # hook's harness-neutral replacement, proven over the wire.
        r = m.call("reconcile", handle=rid, handle_type="recipe",
                   ack_epoch="000000000000")
        data = r.get("data") or r
        rg = data.get("reground") or {}
        check("stale epoch echo returns the reground block",
              bool(rg.get("digest")) and "banner" in rg,
              json.dumps(data)[:300])
        check("reground carries changes_since_your_last_ground key",
              "changes_since_your_last_ground" in rg,
              str(list(rg))[:200])
        r = m.call("next_action", handle=rid, handle_type="recipe",
                   reground=True)
        data = r.get("data") or r
        ctx_blk = data.get("context") or {}
        check("explicit reground=true rehydrates context + rollup",
              "progress_rollup" in ctx_blk,
              str(list(ctx_blk))[:200])

        print("H. durable suspend / resume — the recipe parks and returns")
        r = m.call("suspend_recipe", recipe_id=rid,
                   reason="probe: operator paused the recipe")
        check("suspend_recipe parks the recipe",
              r.get("ok", True) is not False, json.dumps(r)[:300])
        r = m.call("next_action", handle=rid, handle_type="recipe",
                   all_ready=True)
        blob = json.dumps(r)
        check("suspended recipe refuses dispatch",
              r.get("ok") is False or "suspend" in blob.lower()
              or (r.get("data") or {}).get("count") == 0, blob[:300])
        r = m.call("resume_recipe", recipe_id=rid)
        check("resume_recipe un-parks the recipe",
              r.get("ok", True) is not False, json.dumps(r)[:300])
        r = m.call("reconcile", handle=rid, handle_type="recipe")
        check("post-resume reconcile is healthy",
              r.get("ok", True) is not False, json.dumps(r)[:200])

        print("F. close — results, outcomes met, honest close")
        for sid in (sid1, sid2, "s3"):
            m.call("record_step_result", recipe_id=rid, step_id=sid,
                   result={"outputs": [f"{sid} done"]})
        dig = m.call("get_recipe_digest", recipe_id=rid)
        oc = ((dig.get("data") or dig).get("expected_outcomes") or [])
        oid = oc[0].get("id") if oc else "o1"
        m.call("mark_outcome_met", recipe_id=rid, outcome_id=oid,
               evidence="probe verified both widget files")
        r = m.call("close_recipe", recipe_id=rid,
                   final_outcome={"status": "succeeded",
                                  "summary": "probe lifecycle complete"})
        check("close_recipe succeeded", r.get("ok", True) is not False
              and not r.get("refused"), json.dumps(r)[:400])

        m.p.terminate()
        try:
            m.p.wait(timeout=10)   # release registry.db before cleanup
        except Exception:
            pass

    print()
    if FAILS:
        print(f"RESULT: {len(FAILS)} leg(s) FAILED")
        for f in FAILS:
            print("  -", f[:300])
        return 1
    print("RESULT: FULL LIFECYCLE PASS — an external MCP client can author, "
          "drive, spawn, converse, and close.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
