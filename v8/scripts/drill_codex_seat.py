"""s-10a2b1f9ec wake/boot/resume drills for the codex seat on a HERMETIC stack (never the fleet).

Starts its own board (scratch DB + tokens.json = token mode, no pool, no broker) and its own MCP
proxy on free ports, seeds owner + an epic/story + one agent seat with a minted secret, then runs
`python -m edp8.codex_seat.run` for that seat under a real `codex app-server` and drives:

    boot    the MODEL itself calls whoami -> subscribe -> Monitor -> CronCreate -> context from the
            role card and posts its first message on the story
    wake-a  a board question addressed to the seat reaches it as a Monitor event; it answers on the board
    wake-b  a one-shot CronCreate fire wakes the idle seat; it acts on the prompt (posts the marker)
    resume  kill ONLY the runner pid (a crash: no /T) -> every descendant it had (app-server, the
            model's Monitor watches such as its feed driver) must be gone within 30 s (the runner's
            kill-on-close job, qa adversary #5) -> respawn with EDP_CODEX_RESUME=1 -> thread/resume of
            the SAME thread id -> the seat posts again after resume_self()

Every step is logged with UTC timestamps to <out>/drill.json; the runner mirror + event log stay in
<out>/logs. The seat token travels in env only (asserted against every recorded argv).

    .venv/Scripts/python.exe scripts/drill_codex_seat.py --out .logs/codex-drill [--effort low]

Exit 0 = every drill passed; 1 = a drill failed (drill.json says which); 2 = the stack never came up.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

V8 = Path(__file__).resolve().parents[1]
VENV = V8 / ".venv" / "Scripts"
ROLE = "reviewer"
FLEET_ONLY_ENV = ("EDP_POOL_URL", "EDP8_POOL_WATCH", "EDP_BROKER_URL", "EDP8_BOARD_URL", "EDP8_PUBLIC_URL",
                  "EDP8_TOKEN", "EDP_HANDLE", "EDP8_PARTICIPANT", "EDP_ROLE", "EDP_SPAWN_SESSION_ID",
                  "EDP8_ADMIN_TOKEN", "EDP8_MCP_URL", "EDP8_USAGE_CONFIG", "EDP_CODEX_RESUME", "EDP_ACTIVATION",
                  "EDP_LOG_DIR", "EDP_AGENT_HOME", "EDP8_TOKENS", "EDP8_HOME", "EDP8_DB")


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def hermetic(extra: dict[str, str]) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in FLEET_ONLY_ENV}
    env.update(extra)
    return env


def wait_healthy(url: str, timeout: float = 90.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            if httpx.get(url, timeout=3).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    return False


class PtySeat:
    """The seat runner under ConPTY (--tui): monitor mode, i.e. the native codex TUI owns the pseudo console
    exactly as it owns the seat's window under the pool; its screen text goes to <out>/<name>.tui.log so the
    drill can prove what the owner would SEE. Popen-shaped (pid/poll/kill/wait) for the drill's bookkeeping.
    Needs pywinpty: run this drill with edp-pool's venv python (the pool spawns Claude seats under it)."""

    def __init__(self, argv: list[str], env: dict[str, str], cwd: Path, screen: Path):
        import threading

        from winpty import PtyProcess
        self.p = PtyProcess.spawn(subprocess.list2cmdline(argv), cwd=str(cwd), env=env, dimensions=(50, 200))
        self.pid = self.p.pid
        self.screen = screen
        self._f = open(screen, "a", encoding="utf-8", errors="replace")
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        while True:
            try:
                data = self.p.read(8192)
            except Exception:  # noqa: BLE001 — EOF / closed pty
                return
            if data:
                self._f.write(data)
                self._f.flush()

    def write(self, text: str) -> None:
        self.p.write(text)

    def poll(self):
        return None if self.p.isalive() else (self.p.exitstatus if self.p.exitstatus is not None else 0)

    def kill(self) -> None:  # the runner pid only (TerminateProcess, no /T): the crash mode
        subprocess.run(["taskkill", "/PID", str(self.pid), "/F"], capture_output=True)

    def wait(self, timeout: float | None = None):
        end = None if timeout is None else time.time() + timeout
        while self.poll() is None:
            if end is not None and time.time() > end:
                raise subprocess.TimeoutExpired(str(self.pid), timeout)
            time.sleep(0.2)
        return self.poll()


def screen_text(path: Path) -> str:
    """A ConPTY capture with the terminal control sequences stripped (what a person reads on screen)."""
    import re
    raw = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    return re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\x1b[()][0-9A-Za-z]|\x1b[=>]", "", raw)


def kill_tree(p: subprocess.Popen | None) -> None:
    """Our own child by PID only (never by image — the fleet board shares the exe name)."""
    if p and p.poll() is None:
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
        try:
            p.wait(15)
        except subprocess.TimeoutExpired:
            pass


class Drill:
    def __init__(self, out: Path, effort: str, model: str | None, tui: bool = False):
        self.out = out
        self.tui = tui  # monitor mode: the native codex TUI under ConPTY, its screen captured
        self.effort = effort
        self.model = model
        self.log: dict = {"story": "s-10a2b1f9ec", "started": now(), "steps": [], "result": {}}
        self.procs: dict[str, subprocess.Popen] = {}
        self.home = out / "home"
        self.logs = out / "logs"
        self.admin = secrets.token_urlsafe(16)
        self.owner_tok = secrets.token_urlsafe(16)
        self.seat_tok = secrets.token_urlsafe(24)
        self.argvs: list[list[str]] = []

    # ---------------------------------------------------------------- record
    def step(self, name: str, **kw) -> None:
        row = {"ts": now(), "step": name, **kw}
        self.log["steps"].append(row)
        print(json.dumps(row), flush=True)
        self.save()

    def save(self) -> None:
        (self.out / "drill.json").write_text(json.dumps(self.log, indent=2), encoding="utf-8")

    # ---------------------------------------------------------------- stack
    def spawn(self, name: str, argv: list[str], env: dict[str, str], cwd: Path = V8) -> subprocess.Popen:
        self.argvs.append(argv)
        f = open(self.out / f"{name}.out.log", "ab")
        p = subprocess.Popen(argv, cwd=str(cwd), env=env, stdout=f, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.procs[name] = p
        return p

    def up(self) -> bool:
        self.home.mkdir(parents=True, exist_ok=True)
        self.bport, self.mport = free_port(), free_port()
        self.board = f"http://127.0.0.1:{self.bport}"
        self.mcp = f"http://127.0.0.1:{self.mport}"
        tokens = self.home / "tokens.json"
        self.spawn("board", [str(VENV / "edp8-board.exe")], hermetic({
            "EDP8_HOST": "127.0.0.1", "EDP8_PORT": str(self.bport), "EDP8_DB": str(self.home / "edp8.db"),
            "EDP8_HOME": str(self.home), "EDP8_TOKENS": str(tokens), "EDP8_EMBEDDER": "none",
            "EDP8_ADMIN_TOKEN": self.admin, "EDP8_LOG": "warning", "EDP8_USAGE_CONFIG": ""}))
        if not wait_healthy(f"{self.board}/healthz"):
            self.step("board_up", ok=False)
            return False
        self.spawn("mcp", [str(VENV / "edp8-mcp.exe")], hermetic({
            "EDP8_MCP_HOST": "127.0.0.1", "EDP8_MCP_PORT": str(self.mport), "EDP8_BOARD_URL": self.board}))
        if not wait_healthy(f"{self.mcp}/healthz"):
            self.step("mcp_up", ok=False)
            return False
        adm = {"X-Admin": self.admin}
        self.post("/v1/participants", {"type": "human", "role": "owner", "handle": "owner", "id": "owner"}, adm)
        self.post("/v1/participants", {"type": "agent", "role": "architect", "handle": "arch", "id": "arch"}, adm)
        # token mode from here on: tokens.json names the owner and the seat (the seat's secret goes in env only)
        self.epic = self.post("/v1/tickets", {"kind": "epic", "work_type": "feature", "title": "Codex seat drill epic",
                                              "words": "drill"}, self.owner())["id"]
        self.story = self.post("/v1/tickets", {"kind": "story", "work_type": "feature", "parent_id": self.epic,
                                               "title": "Codex seat drill story",
                                               "description": "Hermetic drill ticket for s-10a2b1f9ec. Nothing to review "
                                               "beyond answering the owner's drill messages on this thread."},
                               {"X-Participant": "arch"})["id"]
        self.handle = f"{ROLE}.{self.story}"
        self.post("/v1/participants", {"type": "agent", "role": ROLE, "handle": self.handle, "id": self.handle}, adm)
        tokens.write_text(json.dumps({"owner": self.owner_tok, "agents": {self.handle: self.seat_tok}}), encoding="utf-8")
        time.sleep(1.2)  # tokens.json is mtime-cached
        self.owner_h = {"X-Participant": "owner", "X-Token": self.owner_tok}
        bad = httpx.get(f"{self.board}/v1/messages", params={"ticket_id": self.story},
                        headers={"X-Participant": self.handle}, timeout=10)
        self.step("stack_up", ok=True, board=self.board, mcp=self.mcp, epic=self.epic, story=self.story,
                  seat=self.handle, token_mode_refuses_headerless_seat=bad.status_code == 401)
        return True

    def owner(self) -> dict[str, str]:
        return {"X-Participant": "owner"}

    def post(self, path: str, body: dict, headers: dict[str, str]) -> dict:
        r = httpx.post(f"{self.board}{path}", json=body, headers=headers, timeout=30)
        if r.status_code >= 400:
            raise RuntimeError(f"POST {path} -> {r.status_code}: {r.text[:400]}")
        return r.json()["value"]

    def seat_messages(self, since: int = 0) -> list[dict]:
        r = httpx.get(f"{self.board}/v1/messages", headers=self.owner_h, timeout=15,
                      params={"ticket_id": self.story, "created_by": self.handle, "since_seq": since, "limit": 200})
        return r.json().get("value") or []

    def last_seq(self) -> int:
        r = httpx.get(f"{self.board}/v1/messages", headers=self.owner_h, timeout=15,
                      params={"ticket_id": self.story, "limit": 1})
        rows = r.json().get("value") or []
        return rows[-1]["seq"] if rows else 0

    def say(self, text: str, kind: str = "question") -> dict:
        return self.post("/v1/messages", {"ticket_id": self.story, "to": self.handle, "kind": kind, "text": text},
                         self.owner_h)

    # ---------------------------------------------------------------- seat
    def seat_env(self, resume: bool) -> dict[str, str]:
        env = hermetic({
            "EDP_ROLE": ROLE, "EDP_HANDLE": self.handle, "EDP_SPAWN_SESSION_ID": f"drill-{secrets.token_hex(4)}",
            "EDP8_TOKEN": self.seat_tok, "EDP8_MCP_URL": self.mcp, "EDP8_BOARD_URL": self.board,
            "EDP_AGENT_HOME": str(V8), "EDP_LOG_DIR": str(self.logs), "EDP_CODEX_EFFORT": self.effort,
            "EDP_CODEX_CONSOLE": "1" if self.tui else "0", "EDP_CODEX_RESUME": "1" if resume else "0",
            "PYTHONIOENCODING": "utf-8"})
        if self.model:
            env["EDP_CODEX_MODEL"] = self.model
        return env

    def start_seat(self, resume: bool) -> None:
        name = "seat" + ("-resume" if resume else "")
        argv = [str(VENV / "python.exe"), "-m", "edp8.codex_seat.run"]
        if not self.tui:
            self.spawn(name, argv, self.seat_env(resume))
            return
        self.argvs.append(argv)
        self.procs[name] = PtySeat(argv, self.seat_env(resume), V8, self.out / f"{name}.tui.log")

    def screen(self, name: str = "seat") -> str:
        return screen_text(self.out / f"{name}.tui.log")

    def mirror(self) -> list[dict]:
        p = self.logs / f"codex-seat.{self.handle}.jsonl"
        if not p.is_file():
            return []
        out = []
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
        return out

    def tool_calls(self, since_ts: float = 0) -> list[str]:
        """Tool names the MODEL called, in order: seat tools (item/tool/call) + board MCP tools (mcpToolCall)."""
        names = []
        for r in self.mirror():
            if r.get("ts", 0) < since_ts or r.get("dir") != "in":
                continue
            m = r.get("msg") or {}
            if m.get("method") == "item/tool/call":
                names.append(m["params"].get("tool"))
            elif m.get("method") == "item/started":
                it = (m.get("params") or {}).get("item") or {}
                if it.get("type") == "mcpToolCall":
                    names.append(f"{it.get('server')}.{it.get('tool')}")
        return names

    def wait_for(self, pred, timeout: float, poll: float = 3.0):
        end = time.time() + timeout
        while time.time() < end:
            for name, p in self.procs.items():
                if name.startswith("seat") and p.poll() is not None and name == self.live_seat:
                    return None
            v = pred()
            if v:
                return v
            time.sleep(poll)
        return None

    # ---------------------------------------------------------------- drills
    def run(self) -> int:
        self.out.mkdir(parents=True, exist_ok=True)
        try:
            if not self.up():
                return 2
            ok = self.boot() and self.wake_a() and self.wake_b() and (not self.tui or self.typed()) and self.resume()
            if self.tui:
                ok = self.tui_screen() and ok
            self.log["result"]["token_never_on_argv"] = not any(self.seat_tok in a for argv in self.argvs for a in argv)
            ok = ok and self.log["result"]["token_never_on_argv"]
            self.log["result"]["all_passed"] = ok
            return 0 if ok else 1
        finally:
            self.log["finished"] = now()
            self.log["result"]["cost_note"] = "one gpt-6-astra thread; turns logged in logs/codex-seat.*.jsonl"
            self.save()
            for name in list(self.procs)[::-1]:
                kill_tree(self.procs[name])

    def boot(self) -> bool:
        t0 = time.time()
        self.live_seat = "seat"
        self.step("boot_spawn", seat=self.handle, role=ROLE, sandbox="read-only (seat.ROLE_SANDBOX)")
        self.start_seat(resume=False)
        msgs = self.wait_for(lambda: self.seat_messages(), timeout=900)
        calls = self.tool_calls(t0)
        want = ["edp8.whoami", "edp8.subscribe", "Monitor", "CronCreate", "edp8.context"]
        order_ok = _subsequence(want, calls)
        live = _live_servers(self.mirror())
        self.log["result"]["boot"] = {"passed": bool(msgs) and order_ok, "first_seat_message": (msgs or [{}])[0],
                                      "tool_calls": calls, "boot_order_ok": order_ok, "live_mcp": live}
        self.step("boot_done", passed=bool(msgs) and order_ok, first_message=(msgs or [{}])[0].get("id"),
                  boot_calls=calls[:12], live_mcp=live)
        return bool(msgs) and order_ok

    def wake_a(self) -> bool:
        time.sleep(20)  # let the boot turn settle so the question lands on an idle seat (turn/start path)
        seq = self.last_seq()
        q = self.say("Drill (a): reply on this thread with a message whose text contains the word PAPAYA-7. "
                     "That is the whole task.")
        self.step("wake_a_sent", message=q["id"])
        t = time.time()
        got = self.wait_for(lambda: [m for m in self.seat_messages(seq) if "PAPAYA-7" in m.get("text", "")], 600)
        self.log["result"]["wake_a"] = {"passed": bool(got), "question": q["id"], "answer": (got or [{}])[0].get("id"),
                                        "latency_s": round(time.time() - t, 1), "monitor_event_delivered":
                                        _delivered(self.mirror(), q["id"])}
        self.step("wake_a_done", passed=bool(got), answer=(got or [{}])[0].get("id"),
                  latency_s=round(time.time() - t, 1))
        return bool(got)

    def wake_b(self) -> bool:
        time.sleep(15)
        fire = dt.datetime.now() + dt.timedelta(minutes=3)
        if fire.minute in (0, 30):
            fire += dt.timedelta(minutes=1)
        cron = f"{fire.minute} {fire.hour} {fire.day} {fire.month} *"
        seq = self.last_seq()
        q = self.say(f"Drill (b): call CronCreate with cron \"{cron}\", recurring false, and prompt "
                     f"\"CRON DRILL: post a status message on ticket {self.story} whose text contains CRON-FIRED-9\". "
                     "Do not post CRON-FIRED-9 yourself now; only when that job fires.", kind="steer")
        self.step("wake_b_sent", message=q["id"], cron=cron)
        t = time.time()
        got = self.wait_for(lambda: [m for m in self.seat_messages(seq) if "CRON-FIRED-9" in m.get("text", "")], 600)
        # The cron fire is a BARE-prompt turn/start (the prompt text itself, no wake envelope); the steer that
        # asked for the CronCreate also mentions "CRON DRILL" inside its <task-notification> envelope, so a
        # substring match over the whole input would count that wake as the fire (qa finding, 2026-09-23).
        fired = [r for r in self.mirror() if r.get("dir") == "out" and (r.get("msg") or {}).get("method") == "turn/start"
                 and any(str(i.get("text", "")).startswith("CRON DRILL") for i in ((r["msg"].get("params") or {}).get("input") or []))]
        marker_ts = _iso_ts((got or [{}])[0].get("created_at"))
        early = bool(got) and (not fired or (marker_ts is not None and marker_ts < fired[0]["ts"]))
        # the fire must land in its slot (Claude: at the minute; up to 90 s early only on :00/:30, which the
        # slot above avoids) and the server must have ACCEPTED that turn/start (a response carrying result)
        slot_ts = fire.replace(second=0, microsecond=0).timestamp()
        on_time = bool(fired) and (slot_ts - 5) <= fired[0]["ts"] <= (slot_ts + 75)
        fire_id = (fired[0]["msg"].get("id") if fired else None)
        accepted = any(r.get("dir") == "in" and (r.get("msg") or {}).get("id") == fire_id and "result" in (r.get("msg") or {})
                       for r in self.mirror()) if fire_id is not None else False
        passed = bool(got) and bool(fired) and not early and on_time and accepted
        self.log["result"]["wake_b"] = {"passed": passed, "steer": q["id"], "cron": cron,
                                        "marker_message": (got or [{}])[0].get("id"),
                                        "cron_fire_turn_ts": fired[0]["ts"] if fired else None, "slot_ts": slot_ts,
                                        "fire_on_time": on_time, "fire_turn_accepted": accepted,
                                        "posted_before_fire": early, "wait_s": round(time.time() - t, 1)}
        self.step("wake_b_done", passed=passed, marker=(got or [{}])[0].get("id"),
                  cron_fire_turn=bool(fired), fire_on_time=on_time, fire_turn_accepted=accepted, posted_before_fire=early)
        return passed

    def typed(self) -> bool:
        """(--tui) the owner types into the native TUI: it becomes a user turn the model answers, and the
        runner sees that turn (its busy tracking follows turns it did not start)."""
        time.sleep(10)
        t = time.time()
        seat = self.procs["seat"]
        if "Update now" in self.screen("seat"):
            # never type into codex's update modal: Enter there runs `npm install -g @openai/codex` on the
            # shared host (drill tui1, 2026-09-23 14:19Z, before tui_argv disabled the startup update check)
            self.log["result"]["typed"] = {"passed": False, "refused": "update modal on screen"}
            self.step("typed_done", passed=False, refused="update modal on screen")
            return False
        seat.write("Reply in this terminal with exactly: TYPED-OK-5")
        time.sleep(0.5)
        seat.write("\r")
        self.step("typed_sent", text="TYPED-OK-5")

        def answered():
            return [r for r in self.mirror() if r.get("ts", 0) >= t and r.get("dir") == "in"
                    and (r.get("msg") or {}).get("method") == "item/completed"
                    and ((r["msg"].get("params") or {}).get("item") or {}).get("type") == "agentMessage"
                    and "TYPED-OK-5" in str(((r["msg"].get("params") or {}).get("item") or {}).get("text"))]
        got = self.wait_for(answered, 180, poll=1.0)
        started = [r for r in self.mirror() if r.get("ts", 0) >= t and (r.get("msg") or {}).get("method") == "turn/started"]
        passed = bool(got) and bool(started)
        self.log["result"]["typed"] = {"passed": passed, "runner_saw_turn_started": bool(started),
                                       "latency_s": round(time.time() - t, 1)}
        self.step("typed_done", passed=passed, runner_saw_turn_started=bool(started))
        return passed

    def tui_screen(self) -> bool:
        """(--tui) what the owner SEES: the native TUI rendered the runner-delivered wakes and the typed turn."""
        first, again = self.screen("seat"), self.screen("seat-resume")
        marks = {"wake_a_envelope": "task-notification" in first, "wake_a_answer": "PAPAYA-7" in first,
                 "cron_fire_turn": "CRON DRILL" in first, "typed_turn": "TYPED-OK-5" in first,
                 "native_tui": "OpenAI Codex" in first, "resumed_tui": "OpenAI Codex" in again,
                 "resume_prompt": "You were resumed" in again,
                 "no_update_modal": "Update now" not in first and "Update now" not in again}
        passed = all(marks.values())
        self.log["result"]["tui_screen"] = {"passed": passed, **marks}
        self.step("tui_screen", passed=passed, **marks)
        return passed

    def resume(self) -> bool:
        time.sleep(15)
        state = json.loads((self.logs / "codex-sessions" / f"{self.handle}.json").read_text(encoding="utf-8"))
        tid = state.get("threadId")
        runner = self.procs["seat"]
        before = _descendants(runner.pid)
        self.step("resume_kill", pid=runner.pid, thread=tid, mode="runner pid only (TerminateProcess, no /T)",
                  descendants=[f"{p['pid']} {p['name']}" for p in before])
        runner.kill()  # the crash mode: the job object, not a tree kill, must take the children
        runner.wait(15)
        t_kill = time.time()
        alive = before
        while alive and time.time() - t_kill < 30:
            time.sleep(1)
            alive = _alive(before)
        orphans_ok = bool(before) and not alive
        self.log["result"]["orphans"] = {"passed": orphans_ok, "runner_pid": runner.pid, "descendants_before": before,
                                         "alive_after_30s": alive, "gone_after_s": round(time.time() - t_kill, 1)}
        self.step("orphan_check", passed=orphans_ok, descendants=len(before),
                  alive=[f"{p['pid']} {p['name']} {p['cmd'][:100]}" for p in alive])
        for p in _alive(alive):  # never leave them behind, whatever the verdict (identity re-checked, no /T)
            subprocess.run(["taskkill", "/PID", str(p["pid"]), "/F"], capture_output=True)
        seq = self.last_seq()
        t0 = time.time()
        self.live_seat = "seat-resume"
        self.start_seat(resume=True)
        self.step("resume_spawn", env="EDP_CODEX_RESUME=1")
        got = self.wait_for(lambda: self.seat_messages(seq), 600)
        resumed = [r for r in self.mirror() if r.get("ts", 0) >= t0 and r.get("dir") == "out"
                   and (r.get("msg") or {}).get("method") == "thread/resume"]
        same = bool(resumed) and resumed[0]["msg"]["params"].get("threadId") == tid
        calls = self.tool_calls(t0)
        passed = bool(got) and same and "edp8.resume_self" in calls and orphans_ok
        self.log["result"]["resume"] = {"passed": passed, "thread": tid, "thread_resume_same_id": same,
                                        "resume_self_called": "edp8.resume_self" in calls, "tool_calls": calls,
                                        "post_resume_message": (got or [{}])[0].get("id")}
        self.step("resume_done", passed=passed, same_thread=same, calls=calls[:12])
        return passed


def _procs() -> dict[int, dict]:
    """pid → {ppid, created (FILETIME ticks), name, cmd} for every live process."""
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "Get-CimInstance Win32_Process | % { '{0}|{1}|{2}|{3}|{4}' -f $_.ProcessId,$_.ParentProcessId,"
                          "$_.CreationDate.ToFileTimeUtc(),$_.Name,(($_.CommandLine -replace '[|\\r\\n]',' '))}"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60).stdout
    rows: dict[int, dict] = {}
    for line in out.split("\n"):
        a = line.rstrip("\r").split("|", 4)
        if len(a) == 5 and a[0].isdigit() and a[1].isdigit() and a[2].isdigit():
            rows[int(a[0])] = {"ppid": int(a[1]), "created": int(a[2]), "name": a[3], "cmd": a[4][:160]}
    return rows


def _descendants(root: int) -> list[dict]:
    """Every live descendant of `root`, read before the kill. Windows keeps a dead parent's pid in
    ParentProcessId and reuses pids, so a child counts only when it was created AFTER its parent (the
    stale-ppid guard); identity is (pid, creation time), never the pid alone."""
    rows = _procs()
    if root not in rows:
        return []
    seen: list[dict] = []
    todo = [root]
    while todo:
        par = todo.pop()
        for c, r in rows.items():
            if r["ppid"] == par and c != root and r["created"] >= rows[par]["created"] and all(x["pid"] != c for x in seen):
                seen.append({"pid": c, **r})
                todo.append(c)
    return seen


def _alive(procs: list[dict]) -> list[dict]:
    """The members of `procs` still running: same pid AND same creation time (a reused pid is not alive)."""
    rows = _procs()
    return [p for p in procs if p["pid"] in rows and rows[p["pid"]]["created"] == p["created"]]


def _subsequence(want: list[str], got: list[str]) -> bool:
    it = iter(got)
    return all(any(g == w for g in it) for w in want)


def _live_servers(rows: list[dict]) -> list[str] | None:
    """mcpServerStatus/list answer the runner read at boot (live = has tools or a non-disabled status)."""
    ids = {r["msg"].get("id") for r in rows if r.get("dir") == "out" and r["msg"].get("method") == "mcpServerStatus/list"}
    for r in rows:
        m = r.get("msg") or {}
        if r.get("dir") == "in" and m.get("id") in ids and "result" in m:
            return [s["name"] for s in m["result"].get("data", [])
                    if s.get("tools") or s.get("runtimeStatus") not in (None, "disabled")]
    return None


def _delivered(rows: list[dict], msg_id: str) -> str | None:
    """How the question reached the model: 'turn/start' or 'turn/steer' carrying its id in a task-notification."""
    for r in rows:
        m = r.get("msg") or {}
        if r.get("dir") == "out" and m.get("method") in ("turn/start", "turn/steer") and msg_id in json.dumps(m.get("params")):
            return m["method"]
        if r.get("dir") == "out" and "result" in m and msg_id in json.dumps(m.get("result")):
            return "tool_result"
    return None


def _iso_ts(v: str | None) -> float | None:
    """Board ISO-8601 UTC timestamp -> epoch seconds (None when absent/unparseable)."""
    if not v:
        return None
    try:
        return dt.datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(V8 / ".logs" / "codex-drill"))
    ap.add_argument("--effort", default="low")
    ap.add_argument("--model", default=None)
    ap.add_argument("--tui", action="store_true", help="monitor mode: the native codex TUI under ConPTY (edp-pool venv python)")
    a = ap.parse_args(argv)
    out = Path(a.out).resolve()
    if out.exists() and any(out.iterdir()):
        out = out.with_name(out.name + "-" + dt.datetime.now().strftime("%Y%m%dT%H%M%S"))
    return Drill(out, a.effort, a.model, tui=a.tui).run()


if __name__ == "__main__":
    sys.exit(main())
