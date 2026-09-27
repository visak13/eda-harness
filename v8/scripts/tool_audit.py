"""S23-T1: exercise every advertised role tool through bundles.invoke on a private board.

Run from v8: .venv/Scripts/python.exe scripts/tool_audit.py --out <audit.json>
The source DB is opened read-only and copied with SQLite backup. All writes, tokens,
sessions, uploads and the fake pool are private. stdout is one JSON line per task;
--out contains the role/tool call ledger and six-standard scores for T3's cold run.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from edp8.bundles import ALL_TOOLS, ROLE_BUNDLES, bind_request, enum_fields, invoke  # noqa: E402
from edp8 import tool_idem  # noqa: E402
from edp8.client import BoardClient  # noqa: E402
from edp8.tool_contracts import IDEMPOTENT_CREATES  # noqa: E402
from edp_contracts.settings.secrets import write_secret  # noqa: E402

ROLES = ("owner", "architect", "engineer", "qa", "adversary", "sme", "doctor")
SOURCE_DB = ROOT / ".data" / "edp8.db"
ENV_ALLOW = {"PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC",
             "TEMP", "TMP", "TMPDIR", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
             "USERNAME", "USER", "LOCALAPPDATA", "APPDATA", "PROGRAMDATA", "OS", "LANG", "TZ"}


# T6 N5: topic_research's successful path runs on a LOCAL page (no network): the private board is started through
# this wrapper, which swaps topics.FETCH/RESOLVE for the fixture before edp8.service runs as __main__.
RESEARCH_URL = "https://github.com/edp-audit/fixture/blob/main/SKILL.md"
RESEARCH_TAIL = "AUDIT_TAIL_FACT_7391"
BOARD_BOOT = """
import os, runpy
from pathlib import Path
from edp8 import topics
page = Path(os.environ["EDP8_AUDIT_RESEARCH_PAGE"]).read_bytes()
url = os.environ["EDP8_AUDIT_RESEARCH_URL"]
topics.RESOLVE = lambda host: ["140.82.112.3"]
topics.FETCH = lambda u: (200, page, None) if u == url else (404, b"", None)
runpy.run_module("edp8.service", run_name="__main__", alter_sys=True)
"""

# T6 N6: lifecycle goals the audit deliberately gives no tool, each with its written ruling (report-36481f7a4e N6)
COMPLETENESS_EXEMPT = {
    "library_doc_approval": "Library doc approval is human UI-only by design (owner uses the browser UI only, "
                            "m-0213457e52); ruled m-089e487351. topic_propose's reply says so; no tool is added.",
}


def research_page() -> bytes:
    """An ordinary-prose page longer than one topic_research slice, its last fact after every early cut."""
    words = " ".join(f"Fixture sentence {i} on arrange-act-assert and fixtures." for i in range(320))
    return (f"<html><body><h1>Audit fixture skill</h1><p>{words}</p>"
            f"<p>{RESEARCH_TAIL} closes the page.</p></body></html>").encode()


def transcripts(root: Path, claude_seat: str, codex_seat: str) -> tuple[Path, Path]:
    """T6 N4: hermetic seat logs, one Claude transcript and one codex app-server mirror, each with a harvest
    window (trigger -> record -> close_self) and token usage, so harvest_cost passes from any kind of seat."""
    t0 = time.time() - 600

    def iso(s: float) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0 + s))

    def turn(s: float, mid: str, usage: dict, name: str, args: dict) -> dict:
        return {"type": "assistant", "timestamp": iso(s), "message": {"id": mid, "usage": usage, "content": [
            {"type": "tool_use", "name": name, "input": args}]}}

    claude = root / "claude" / "audit-project" / "audit-session.jsonl"
    claude.parent.mkdir(parents=True, exist_ok=True)
    who = json.dumps({"participant": {"id": claude_seat}})
    rows = [{"type": "user", "timestamp": iso(0), "message": {"role": "user", "content": [
                {"type": "tool_result", "content": who}]}},
            turn(10, "msg-1", {"input_tokens": 100, "output_tokens": 20}, "Skill", {"skill": "harvest"}),
            turn(20, "msg-2", {"input_tokens": 300, "cache_read_input_tokens": 50, "output_tokens": 40},
                 "mcp__edp8__record_lesson", {"text": "x"}),
            turn(30, "msg-3", {"input_tokens": 10, "output_tokens": 5}, "mcp__edp8__close_self", {})]
    claude.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    def usage(s: float, n: int) -> dict:
        return {"ts": t0 + s, "msg": {"method": "thread/tokenUsage/updated", "params": {
            "threadId": "th-1", "tokenUsage": {"total": {"inputTokens": n, "outputTokens": n // 10,
                                                         "totalTokens": n}}}}}

    def item(s: float, it: dict) -> dict:
        return {"ts": t0 + s, "msg": {"method": "item/started", "params": {"item": it}}}

    codex = root / "codex" / "seat-logs" / f"codex-seat.{codex_seat}.jsonl"
    codex.parent.mkdir(parents=True, exist_ok=True)
    rows = [usage(5, 1000),
            item(10, {"type": "commandExecution", "command": "cat .agents/skills/harvest/SKILL.md"}),
            usage(15, 1600),
            item(20, {"type": "mcpToolCall", "tool": "record_lesson", "arguments": {"text": "x"}}),
            usage(25, 2400),
            item(30, {"type": "mcpToolCall", "tool": "close_self", "arguments": {}})]
    codex.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return root / "claude", root / "codex"


def encoded(obj: object) -> bytes:
    return json.dumps(obj, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8")


def free_port(preferred: int) -> int:
    if preferred in (9300, 9301, 9400, 9402):
        raise ValueError("fleet port refused")
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", preferred))
        except OSError:
            sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class FakePool(BaseHTTPRequestHandler):
    sessions: list[dict] = []

    def reply(self, payload: object) -> None:
        data = encoded(payload)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/v1/limits"):
            return self.reply({"max_workers": 20})
        if self.path.startswith("/v1/pool/capabilities"):
            return self.reply({"spawn": True, "resume_parked": True, "resume_closed": True, "park": True})
        if self.path.startswith("/v1/sessions"):
            return self.reply(self.sessions)
        if self.path.startswith("/v1/liveness"):
            return self.reply({"state": "dead", "answered": True})
        return self.reply({"ok": True, "value": []})

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/v1/spawn":
            pid = body.get("participant_id") or body.get("handle")  # the pool contract sends `handle`
            row = {"session_id": f"audit-session-{len(self.sessions) + 1}",
                   "participant_id": pid, "role": body.get("role"),
                   "handle": pid, "state": "alive",
                   "spawn_settings": {"env": body.get("env") or {}}}  # the real pool records the spawn env
            self.sessions.append(row)
            return self.reply({"session_id": row["session_id"], "handle": row["handle"]})
        if self.path.endswith("/reap") or self.path.endswith("/release_self"):
            for row in self.sessions:
                if row.get("participant_id") in (body.get("participant_id"), body.get("handle")):
                    row["state"] = "dead"
        return self.reply({"ok": True, "value": {"participant_id": body.get("participant_id"), "state": "done"}})

    def log_message(self, *_):
        pass


class Audit:
    def __init__(self, home: Path, board_port: int, pool_port: int):
        self.home = home
        self.board_port = board_port
        self.pool_port = pool_port
        self.base = f"http://127.0.0.1:{board_port}"
        self.admin = secrets.token_urlsafe(24)
        self.owner_token = secrets.token_urlsafe(24)
        self.roles: dict[str, tuple[str, str]] = {"owner": ("audit.owner", self.owner_token)}
        self.calls: list[dict] = []
        self.tasks: list[dict] = []
        self.ids: dict[str, str] = {}
        self.board_proc: subprocess.Popen | None = None
        self.pool: ThreadingHTTPServer | None = None
        self.seats: dict[str, tuple[str, str]] = {}  # extra credentials (the topic's own sme seat) by label
        self.claude_seat, self.codex_seat = "qa.audit-claude-transcript", "qa.audit-codex-transcript"
        self.log_roots: tuple[Path, Path] = (home / "transcripts" / "claude", home / "transcripts" / "codex")

    def start(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self.log_roots = transcripts(self.home / "transcripts", self.claude_seat, self.codex_seat)
        (self.home / "research-page.html").write_bytes(research_page())
        source = sqlite3.connect(f"file:{SOURCE_DB.as_posix()}?mode=ro", uri=True)
        copy = sqlite3.connect(self.home / "edp8.db")
        source.backup(copy)
        copy.close()
        source.close()
        # The private file is intentionally never populated from the fleet token file.
        write_secret(self.home / "tokens.json",
                     encoded({"audit.owner": self.owner_token, "agents": {}}).decode("utf-8"))
        self.pool = ThreadingHTTPServer(("127.0.0.1", self.pool_port), FakePool)
        threading.Thread(target=self.pool.serve_forever, daemon=True).start()
        os.environ.update(EDP_POOL_URL=f"http://127.0.0.1:{self.pool_port}", EDP8_HOME=str(self.home),
                          EDP8_TOKENS=str(self.home / "tokens.json"), EDP8_BOARD_URL=self.base,
                          EDP8_ADMIN_TOKEN=self.admin, EDP8_EMBEDDER="none")
        self.start_board()
        admin = BoardClient(self.base, participant="audit.owner", token=self.owner_token, admin_token=self.admin)
        made = admin.participant_create("human", "owner", "audit.owner", id="audit.owner")
        if not made.get("ok"):
            raise RuntimeError(f"private owner registration: {made}")

    def start_board(self) -> None:
        safe = {k: v for k, v in os.environ.items() if k.upper() in ENV_ALLOW}
        safe.update(EDP8_HOME=str(self.home), EDP8_RUN_DIR=str(self.home / ".run"),
                    EDP8_DB=str(self.home / "edp8.db"), EDP8_TOKENS=str(self.home / "tokens.json"),
                    EDP8_HOST="127.0.0.1", EDP8_PORT=str(self.board_port),
                    EDP8_ADMIN_TOKEN=self.admin, EDP8_EMBEDDER="none", EDP8_LOG="warning",
                    EDP8_RSI="0", EDP8_OWNER="audit.owner", EDP8_PAIN_FILE=str(self.home / "pain.jsonl"),
                    # T6 N4: hermetic Claude AND codex roots, never the host's seat logs
                    EDP8_HARVEST_LOG_ROOTS=os.pathsep.join(str(r) for r in self.log_roots),
                    EDP8_AUDIT_RESEARCH_PAGE=str(self.home / "research-page.html"),
                    EDP8_AUDIT_RESEARCH_URL=RESEARCH_URL,
                    EDP_POOL_URL=f"http://127.0.0.1:{self.pool_port}",
                    PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        log = (self.home / "board.log").open("ab")
        self.board_proc = subprocess.Popen([sys.executable, "-c", BOARD_BOOT], cwd=ROOT, env=safe,
                                           stdout=log, stderr=subprocess.STDOUT,
                                           creationflags=flags, start_new_session=os.name != "nt")
        log.close()
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if self.board_proc.poll() is not None:
                raise RuntimeError(f"private board exited {self.board_proc.returncode}; see {self.home / 'board.log'}")
            try:
                if httpx.get(f"{self.base}/v1/health", timeout=2).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.4)
        raise RuntimeError("private board did not become healthy")

    def stop_board(self) -> None:
        if self.board_proc is None:
            return
        # Only the process spawned here, identified by its live Process object, is stopped.
        try:
            root = psutil.Process(self.board_proc.pid)
            tree = [*root.children(recursive=True), root]
            for proc in tree:
                try:
                    proc.kill()
                except psutil.NoSuchProcess:
                    pass
            psutil.wait_procs(tree, timeout=10)
        except psutil.NoSuchProcess:
            pass
        self.board_proc = None

    def stop(self) -> None:
        self.stop_board()
        if self.pool:
            self.pool.shutdown()
            self.pool.server_close()

    def register(self, role: str, ticket_id: str) -> None:
        pid = f"{role}.{ticket_id}"
        owner = BoardClient(self.base, participant="audit.owner", token=self.owner_token, admin_token=self.admin)
        made = owner.participant_create("agent", role, pid, id=pid)
        if not made.get("ok"):
            raise RuntimeError(f"register {role}: {made}")
        minted = owner.seat_token(pid, ticket_id)
        if not minted.get("ok"):
            raise RuntimeError(f"mint {role}: {minted}")
        token = ((minted.get("value") or {}).get("env") or {}).get("EDP8_TOKEN")
        if not token:
            raise RuntimeError(f"private board did not mint {role} token")
        self.roles[role] = (pid, token)

    def topic_seat(self, topic_id: str) -> None:
        """The Library topic's resident sme (`sme.<topic>`, its assignee): the seat topic_research and
        topic_propose act as. Its token is re-read (get-or-mint) before each call: the board's pairing spawn
        mints the seat its own token on a later pool tick."""
        self.seats["sme"] = (f"sme.{topic_id}", topic_id)

    def seat_credential(self, seat: str) -> tuple[str, str]:
        pid, ticket_id = self.seats[seat]
        owner = BoardClient(self.base, participant="audit.owner", token=self.owner_token, admin_token=self.admin)
        minted = owner.seat_token(pid, ticket_id)
        token = ((minted.get("value") or {}).get("env") or {}).get("EDP8_TOKEN")
        if not token:
            raise RuntimeError(f"private board did not mint the {pid} token: {minted}")
        return pid, token

    def call(self, role: str, name: str, args: dict | None = None, *, task: str = "coverage",
             seat: str | None = None) -> dict:
        """`seat` borrows another credential of the same role (the topic's own sme) for this call."""
        pid, token = self.seat_credential(seat) if seat else self.roles[role]
        client = BoardClient(self.base, participant=pid, token=token,
                             admin_token=self.admin if role == "owner" else None,
                             workspace_root=ROOT)
        t0 = time.monotonic()
        try:
            with bind_request(client, session_id=f"audit-{role}"):
                result = invoke(ALL_TOOLS[name], args or {}, seat=pid)
        except Exception as exc:  # diagnostic: keep the whole matrix even if one tool crashes
            result = {"ok": False, "error": {"code": "exception", "message": repr(exc)}, "hint": ""}
        raw = encoded(result)
        error = result.get("error") or {}
        ledger_args = {key: (str(value).replace(str(ROOT), "<workspace>") if key == "path" else value)
                       for key, value in (args or {}).items()}
        self.calls.append({"task": task, "role": role, "tool": name, "args": ledger_args,
                           "ok": bool(result.get("ok")), "error_code": error.get("code"),
                           "result_id": (result.get("value") or {}).get("id") if isinstance(result.get("value"), dict) else None,
                           "error": str(error.get("message") or "")[:400],
                           "hint": str(result.get("hint") or "")[:400],
                           "bytes_out": len(raw), "max_line_bytes": max(map(len, raw.splitlines()), default=0),
                           "duration_ms": round((time.monotonic() - t0) * 1000)})
        return result

    def task(self, name: str, fn) -> None:
        start = len(self.calls)
        try:
            outcome = fn()
            passed, note = outcome[:2]
            workarounds = outcome[2] if len(outcome) > 2 else []
        except Exception as exc:
            passed, note, workarounds = False, repr(exc), []
        calls = self.calls[start:]
        row = {"type": "task", "task": name, "calls": len(calls),
               "arg_misses": sum(c["error_code"] == "schema" for c in calls),
               "bytes_out": sum(c["bytes_out"] for c in calls),
               "max_line_bytes": max((c["max_line_bytes"] for c in calls), default=0),
               "workarounds_needed": workarounds, "pass": bool(passed) and not workarounds,
               "note": note}
        self.tasks.append(row)
        print(json.dumps(row, ensure_ascii=True), flush=True)

    def image_content(self, role: str, artifact_id: str, *, task: str) -> bytes:
        """The second hop needed after artifact_read: record it as a call-to-goal."""
        pid, token = self.roles[role]
        response = httpx.get(f"{self.base}/v1/artifacts/{artifact_id}/content",
                             headers={"X-Participant": pid, "X-Token": token}, timeout=15)
        self.calls.append({"task": task, "role": role, "tool": "artifact_content_http", "args": {"id": artifact_id},
                           "ok": response.status_code == 200, "error_code": None if response.status_code == 200 else "http",
                           "result_id": artifact_id, "error": "" if response.status_code == 200 else str(response.status_code),
                           "hint": "", "bytes_out": len(response.content), "max_line_bytes": len(response.content),
                           "duration_ms": 0})
        return response.content if response.status_code == 200 else b""

    def value(self, result: dict, what: str) -> dict:
        if not result.get("ok"):
            raise RuntimeError(f"{what}: {result.get('error')}")
        return result.get("value") or {}


def workflow(a: Audit) -> None:
    def file_story():
        epic = a.value(a.call("owner", "ticket_create", {"kind": "epic", "work_type": "feature",
            "title": "Tool audit private epic", "words": "Private tool-usability exercise"}, task="file_story"), "epic")
        a.ids["epic"] = epic["id"]
        a.register("architect", epic["id"])
        story = a.value(a.call("architect", "ticket_create", {"kind": "story", "work_type": "feature",
            "title": "Audit story", "parent_id": epic["id"], "description": "Private workflow exercise"},
            task="file_story"), "story")
        a.ids["story"] = story["id"]
        for role in ("engineer", "qa", "adversary", "sme", "doctor"):
            a.register(role, story["id"])
        owner = BoardClient(a.base, participant="audit.owner", token=a.owner_token, admin_token=a.admin)
        topic = owner._request("POST", "/v1/topics", json={"title": "Audit research topic", "tags": ["audit"]})
        if topic.get("ok"):  # T6 N5: a real topic for topic_research's successful path (coverage)
            a.ids["topic"] = topic["value"]["topic"]["id"]
            a.topic_seat(a.ids["topic"])
        crit = a.value(a.call("architect", "criterion_create", {"ticket_id": story["id"],
            "text": "A private task produces evidence", "check": "command"}, task="file_story"), "criterion")
        a.ids["criterion"] = crit["id"]
        doc = a.value(a.call("architect", "doc_create", {"doc_type": "design", "title": "Audit design",
            "body_md": "# Audit design\n\nFirst section.\n", "scope": epic["id"], "ticket_id": story["id"]},
            task="file_story"), "design")
        a.ids["doc"] = doc["id"]
        a.call("architect", "ticket_update", {"ticket_id": story["id"], "design_ref": doc["id"]}, task="file_story")
        designed = a.call("architect", "ticket_update", {"ticket_id": story["id"], "status": "designed"}, task="file_story")
        signed = a.call("architect", "ticket_update", {"ticket_id": story["id"], "status": "signed_off"}, task="file_story")
        current = a.call("architect", "ticket_read", {"ticket_id": story["id"]}, task="file_story")
        status = ((current.get("value") or {}).get("status") or (current.get("value") or {}).get("ticket", {}).get("status"))
        return bool(designed.get("ok") and signed.get("ok") and status in ("ready", "signed_off")), f"status={status}"
    a.task("file_story", file_story)

    def thread():
        sent = a.value(a.call("architect", "message_send", {"ticket_id": a.ids["story"], "kind": "question",
            "to": a.roles["engineer"][0], "text": "Can you inspect the evidence?"}, task="thread"), "message")
        a.ids["message"] = sent["id"]
        queried = a.call("engineer", "message_query", {"ticket_id": a.ids["story"]}, task="thread")
        read = a.call("engineer", "message_read", {"id": sent["id"]}, task="thread")
        answered = a.call("engineer", "message_send", {"ticket_id": a.ids["story"], "kind": "answer",
            "reply_to": sent["id"], "text": "Yes, on this private copy."}, task="thread")
        return all(x.get("ok") for x in (queried, read, answered)), "send → query → read → answer"
    a.task("thread", thread)

    def image():
        import base64
        path = ROOT / "web" / "public" / "brand" / "favicon-32.png"
        uploaded = a.call("engineer", "artifact_upload", {"path": str(path)}, task="image")
        if not uploaded.get("ok"):
            return False, str(uploaded.get("error"))[:180]
        aid = uploaded["value"]["id"]
        a.ids["artifact"] = aid
        attached = a.call("engineer", "message_send", {"ticket_id": a.ids["story"], "kind": "note",
            "text": "Image attached", "artifacts": [aid]}, task="image")
        read = a.call("qa", "artifact_read", {"id": aid}, task="image")
        content = ((read.get("value") or {}).get("content") or {})
        png = base64.b64decode(content.get("base64") or "").startswith(b"\x89PNG")
        return bool(attached.get("ok") and read.get("ok") and content.get("kind") == "image" and png), \
            f"artifact={aid}; one artifact_read returns the image (MCP image block); png={png}"
    a.task("image", image)

    def edit_design():
        read = a.call("architect", "doc_read", {"id": a.ids["doc"]}, task="edit_design")
        body = a.value(read, "doc read")
        edited = a.call("architect", "doc_edit", {"id": a.ids["doc"], "expected_version": body["version"],
            "edits": [{"old_text": "First section.", "new_text": "Revised section."}]}, task="edit_design")
        confirm = a.call("architect", "doc_read", {"id": a.ids["doc"]}, task="edit_design")
        return edited.get("ok") and "Revised section." in (confirm.get("value") or {}).get("body_md", ""), "versioned exact edit"
    a.task("edit_design", edit_design)

    def decision():
        made = a.call("architect", "record_decision", {"scope": a.ids["epic"],
            "text": "This private audit uses an in-process tool harness.", "detail": "T1 audit only."}, task="decision")
        found = a.call("engineer", "lookup", {"scope": a.ids["epic"], "question": "in-process tool harness"}, task="decision")
        if made.get("ok"):
            a.ids["decision"] = made["value"]["id"]
        return made.get("ok") and found.get("ok"), "record → lookup"
    a.task("decision", decision)

    def spawn_reap():
        custom = f"engineer.audit-{a.ids['story']}"
        spawned = a.call("architect", "spawn", {"role": "engineer", "ticket_id": a.ids["story"],
            "participant_id": custom, "assign": False}, task="spawn_reap")
        queried = a.call("architect", "session_query", {"participant_id": custom}, task="spawn_reap")
        reaped = a.call("architect", "reap", {"participant_id": custom}, task="spawn_reap")
        workaround = [] if reaped.get("ok") else ["direct pool reap is required for custom participant_id"]
        return all(x.get("ok") for x in (spawned, queried, reaped)), \
            f"spawn={spawned.get('error') or 'ok'}; reap={reaped.get('error') or 'ok'}", workaround
    a.task("spawn_reap", spawn_reap)

    def verdict():
        report = a.call("engineer", "doc_create", {"doc_type": "report", "title": "Audit evidence",
            "body_md": "# Evidence\n\nPrivate task complete.\n", "scope": a.ids["epic"],
            "ticket_id": a.ids["story"]}, task="verdict")
        if not report.get("ok"):
            return False, str(report.get("error"))[:180]
        a.ids["report"] = report["value"]["id"]
        attached = a.call("engineer", "criterion_update", {"id": a.ids["criterion"],
            "evidence_ref": a.ids["report"]}, task="verdict")
        progress = a.call("engineer", "ticket_update", {"ticket_id": a.ids["story"], "status": "in_progress"}, task="verdict")
        review = a.call("engineer", "ticket_update", {"ticket_id": a.ids["story"], "status": "in_review"}, task="verdict")
        judged = a.call("qa", "criterion_update", {"id": a.ids["criterion"], "verdict": "pass"}, task="verdict")
        return all(x.get("ok") for x in (attached, progress, review, judged)), \
            f"progress={progress.get('error') or 'ok'}; review={review.get('error') or 'ok'}; verdict={judged.get('error') or 'ok'}"
    a.task("verdict", verdict)

    def restart_cursor():
        ctx = a.call("owner", "context", {}, task="restart_cursor")
        cursor = (ctx.get("value") or {}).get("cursor")
        a.stop_board()
        a.start_board()
        delta = a.call("owner", "context_delta", {"cursor": cursor or "missing"}, task="restart_cursor")
        return bool(cursor and delta.get("ok")), f"post-restart delta={delta.get('error') or 'ok'} (no context() fallback)"
    a.task("restart_cursor", restart_cursor)

    def participants():
        result = a.call("owner", "participants", {}, task="participants")
        return result.get("ok"), f"bytes={a.calls[-1]['bytes_out']}"
    a.task("participants", participants)

    def file_pain():
        found = a.call("engineer", "pain", {"action": "query", "q": "audit probe symptom"}, task="file_pain")
        filed = a.call("engineer", "pain", {"action": "file", "severity": "low", "area": "tools",
            "symptom": "audit probe symptom", "expected": "a bounded tool", "evidence": "tool_audit"}, task="file_pain")
        pid = (filed.get("value") or {}).get("id")
        again = a.call("engineer", "pain", {"action": "query", "q": "audit probe symptom"}, task="file_pain")
        shown = a.call("engineer", "pain", {"action": "read", "id": pid or "missing"}, task="file_pain")
        resolved = a.call("doctor", "pain", {"action": "resolve", "id": pid or "missing", "status": "invalid",
            "note": "audit probe"}, task="file_pain")
        hit = [r.get("id") for r in (again.get("value") or {}).get("items", [])] == [pid]
        return all(x.get("ok") for x in (found, filed, again, shown, resolved)) and hit, \
            f"query -> file {pid} -> query finds it -> read -> doctor resolves"
    a.task("file_pain", file_pain)

    def harvest_cost():
        # T6 N4: hermetic Claude and codex transcripts (the private home's own roots), so the task passes from
        # either kind of seat; a seat with no log gets an error naming the roots, with no `since` advice
        claude = a.call("qa", "harvest_cost", {"participant_id": a.claude_seat}, task="harvest_cost")
        codex = a.call("qa", "harvest_cost", {"participant_id": a.codex_seat}, task="harvest_cost")
        missing = a.call("qa", "harvest_cost", {"participant_id": a.roles["qa"][0]}, task="harvest_cost")
        err = missing.get("error") or {}
        named = err.get("code") == "not_found" and all(str(r) in str(err.get("message")) for r in a.log_roots) \
            and "since" not in str(missing.get("hint") or "") + str(err.get("hint") or "")
        kinds = [(x.get("value") or {}).get("seat") for x in (claude, codex)]
        return bool(claude.get("ok") and codex.get("ok") and kinds == ["claude", "codex"] and named), \
            f"claude={(claude.get('value') or {}).get('tokens')}; codex={(codex.get('value') or {}).get('tokens')}; " \
            f"no-log seat -> {err.get('code')} naming both roots={named}"
    a.task("harvest_cost", harvest_cost)

    def teammate_access():
        made = a.call("owner", "teammate", {"action": "create", "handle": "audit.alex", "role": "qa"},
                      task="teammate_access")
        minted = a.call("owner", "teammate", {"action": "mint", "handle": "audit.alex"}, task="teammate_access")
        once = bool((minted.get("value") or {}).get("token"))
        listed = a.call("owner", "teammate", {"action": "list"}, task="teammate_access")
        revoked = a.call("owner", "teammate", {"action": "revoke", "handle": "audit.alex"}, task="teammate_access")
        agent = a.call("architect", "teammate", {"action": "list"}, task="teammate_access")
        return all(x.get("ok") for x in (made, minted, listed, revoked)) and once, \
            f"create -> mint (token once={once}) -> list -> revoke; agent seat refused={not agent.get('ok')}"
    a.task("teammate_access", teammate_access)

    def workflow_edit():
        listed = a.call("owner", "workflow", {"action": "list"}, task="workflow_edit")
        dup = a.call("owner", "workflow", {"action": "duplicate", "ref": "standard@1", "new_id": "audit-flow"},
                     task="workflow_edit")
        dv = dup.get("value") or {}
        dv = dv.get("draft") or dv
        ref = f"{dv.get('id') or 'audit-flow'}@{dv.get('version') or 1}"
        full = a.call("owner", "workflow", {"action": "read", "ref": ref, "full": True}, task="workflow_edit")
        definition = (full.get("value") or {}).get("definition") or {}
        checked = a.call("owner", "workflow", {"action": "validate", "definition": definition}, task="workflow_edit")
        saved = a.call("owner", "workflow", {"action": "edit", "definition": definition}, task="workflow_edit")
        bad = [(x.get("error") or {}).get("message") for x in (listed, dup, full, checked, saved) if not x.get("ok")]
        return not bad, f"list -> duplicate {ref} -> read full -> validate -> edit; errors={bad}"
    a.task("workflow_edit", workflow_edit)

    def service_status():
        got = a.call("owner", "service_status", {}, task="service_status")
        return bool(got.get("ok")), f"rows={len(got.get('value') or [])}"
    a.task("service_status", service_status)


def sample_args(a: Audit, role: str, name: str) -> dict:
    """A safe, schema-valid probe for every role/tool pair not used in the workflows."""
    ids = a.ids
    values = {"ticket_id": ids.get("story"), "epic_id": ids.get("epic"), "scope": ids.get("epic"),
              "id": ids.get("doc"), "subject_id": ids.get("story"), "from_id": ids.get("story"),
              "to_id": ids.get("doc"), "participant_id": a.roles.get("engineer", (None,))[0],
              "role": "engineer", "type": "ticket", "name": "shared-host-rules", "query": "audit",
              "question": "audit", "text": "Audit probe", "title": "Audit probe",
              "body_md": "# Audit probe\n", "doc_type": "note", "kind": "task", "work_type": "chore",
              "check": "path", "status": "reviewed", "relation": "produced", "form": "repo_ref",
              "uri": "repo://scripts/tool_audit.py", "gate": "demo", "answer": "approved",
              "decision_id": ids.get("decision"), "topic_id": ids.get("topic") or "audit-topic",
              "source_url": RESEARCH_URL, "url": RESEARCH_URL,
              "effect": "Audit-only proposal", "action": {"kind": "noop"}, "domain": "tool-layer",
              "topic": "audit", "ref": "standard@1", "service": "board", "lines": 5,
              "path": str(ROOT / "web" / "public" / "brand" / "favicon-32.png"),
              "cursor": "not-a-cursor", "evidence_ref": ids.get("report"),
              "edits": [{"old_text": "absent", "new_text": "present"}], "expected_version": 1,
              "binding": False, "claim_id": "clm-audit-missing", "evidence": [], "to": a.roles.get("owner", (None,))[0]}
    # Select the correct id/object for methods with different meanings.
    by_tool = {"message_read": {"id": ids.get("message")},
               "criterion_update": {"id": ids.get("criterion")},
               "doc_edit": {"id": ids.get("doc")}, "doc_update": {"id": ids.get("doc")},
               "doc_read": {"id": ids.get("doc")}, "ticket_read": {"ticket_id": ids.get("story")},
               "ticket_update": {"ticket_id": ids.get("story"), "status": None},
               "artifact_read": {"id": ids.get("artifact")},
               # S23 action-enum tools: a read-only action for the coverage probe
               "pain": {"action": "query"}, "workflow": {"action": "list"}, "teammate": {"action": "list"},
               "link_delete": {"id": "lk-audit-missing"},
               # T6 N5: the real topic's successful paths (a local page), not a nonexistent-topic error
               "topic_research": {"url": RESEARCH_URL},
               "topic_propose": {"body_md": "- [expected] tests follow arrange-act-assert (audit fixture)"},
               "propose_fix": {"topic_id": "audit-topic"}, "message_send": {"ticket_id": ids.get("story"), "kind": "note"},
               "gate_open": {"ticket_id": ids.get("story"), "gate": "demo"},
               "gate_answer": {"ticket_id": ids.get("story"), "gate": "demo", "answer": "approved"},
               "doc_create": {"scope": ids.get("epic"), "doc_type": "note"},
               "ticket_create": {"parent_id": ids.get("story"), "kind": "task", "work_type": "chore"},
               "criterion_create": {"ticket_id": ids.get("story"), "check": "path"},
               "record_status": {"status": "reviewed", "ticket_id": ids.get("story")},
               "record_decision": {"scope": ids.get("epic")},
               "record_claim": {"scope": ids.get("epic")},
               "lookup": {"scope": ids.get("epic")},
               "assemble_ruleset": {"ticket_id": ids.get("story")},
               "find": {"query": "audit"},
               "spawn": {"role": "engineer", "ticket_id": ids.get("story"), "assign": False},
               "reap": {"participant_id": "engineer.audit-missing"},
               "resume": {"participant_id": "engineer.audit-missing"},
               "close": {"epic_id": ids.get("epic")},
               "why_stuck": {"ticket_id": ids.get("story")},
               "gates": {"ticket_id": ids.get("story")},
               "board": {"epic_id": ids.get("epic")},
               "criterion_query": {"ticket_id": ids.get("story")},
               "artifact_create": {"form": "repo_ref", "uri": "repo://scripts/tool_audit.py",
                                   "ticket_id": ids.get("story")}}
    fields = ALL_TOOLS[name].args_model.model_fields
    chosen = {key for key, field in fields.items() if field.is_required()} | set(by_tool.get(name, {}))
    merged = {**values, **by_tool.get(name, {})}
    return {key: merged[key] for key in chosen if key in fields and key in merged and merged[key] is not None}


def coverage(a: Audit) -> None:
    def scan():
        seen = {(c["role"], c["tool"]) for c in a.calls}
        for role in ROLES:
            for name in ROLE_BUNDLES[role]:
                if (role, name) in seen or name == "close_self":
                    continue
                a.call(role, name, sample_args(a, role, name), task="coverage",
                       seat="sme" if name.startswith("topic_") and "sme" in a.seats else None)
        # close_self can release its private stub session; always run it last.
        for role in ROLES:
            if "close_self" in ROLE_BUNDLES[role] and (role, "close_self") not in seen:
                a.call(role, "close_self", {}, task="coverage")
        actual = {(c["role"], c["tool"]) for c in a.calls if c["tool"] in ALL_TOOLS}
        missing = [(r, n) for r in ROLES for n in ROLE_BUNDLES[r] if (r, n) not in actual]
        # T6 N1/N5: the research probe succeeded, and its named continuation reads the page to its last fact
        text, offset = "", None
        first = next((c for c in a.calls if c["tool"] == "topic_research" and c["ok"]), None)
        while first is not None:
            args = {"topic_id": a.ids.get("topic"), "url": RESEARCH_URL, "offset": offset or 0}
            got = a.call("sme", "topic_research", args, task="coverage", seat="sme")
            v = got.get("value") or {}
            text += v.get("text") or ""
            offset = v.get("next_offset")
            if not got.get("ok") or offset is None:
                break
        tail = RESEARCH_TAIL in text
        return not missing and tail, f"{len(actual)} role/tool pairs; missing={missing[:6]}; research tail read={tail}"
    a.task("coverage", scan)

    def arg_guidance():
        tests = [("engineer", "message_read", {"message_id": a.ids["message"]}, "id"),
                 ("engineer", "criterion_create", {"ticket_id": a.ids["story"], "text": "Probe",
                    "checkable": "path"}, "check"),
                 ("engineer", "ticket_create", {"kind": "tasck", "work_type": "chore", "title": "Probe"}, "task"),
                 ("engineer", "doc_edit", {"id": a.ids["doc"], "edits": []}, "expected_version"),
                 ("engineer", "lookup", {"question": "audit"}, "scope")]
        clear = 0
        for role, name, args, remedy in tests:
            result = a.call(role, name, args, task="arg_guidance")
            msg = str(result.get("error") or "") + str(result.get("hint") or "")
            clear += result.get("ok") if name == "message_read" else remedy in msg
        ignored = a.call("engineer", "message_query", {"ticket_id": a.ids["story"], "limt": 1},
                         task="arg_guidance")
        return clear == len(tests) and not ignored.get("ok"), \
            f"{clear}/{len(tests)} accepted aliases or clear errors; unknown optional arg silently accepted={ignored.get('ok')}"
    a.task("arg_guidance", arg_guidance)

    def describe_objects():
        index = a.call("engineer", "describe_objects", {}, task="describe_objects")
        if not index.get("ok"):
            return False, str(index.get("error"))[:120]
        value = index.get("value") or {}
        names = value.get("objects") if isinstance(value, dict) else None
        if isinstance(names, dict):
            names = list(names)
        if not isinstance(names, list):
            names = ["ticket", "criterion", "doc", "artifact", "message", "participant"]
        success = 0
        for name in names:
            typ = name.get("name") if isinstance(name, dict) else name
            if not isinstance(typ, str):
                continue
            result = a.call("engineer", "describe", {"type": typ}, task="describe_objects")
            success += bool(result.get("ok"))
        return success == len(names), f"{success}/{len(names)} objects described"
    a.task("describe_objects", describe_objects)

    def idempotency():
        probes = [("engineer", "doc_create", {"doc_type": "note", "title": "Repeat note", "body_md": "same",
                    "scope": a.ids["epic"], "ticket_id": a.ids["story"]}),
                  ("engineer", "artifact_create", {"form": "repo_ref", "uri": "repo://scripts/tool_audit.py",
                    "ticket_id": a.ids["story"]}),
                  ("architect", "ticket_create", {"kind": "task", "work_type": "chore",
                    "parent_id": a.ids["story"], "title": "Repeated task"})]
        # T3 F2: every other create, retried with an idempotency_key after the tool process forgot it (an
        # MCP-proxy restart): the board's key must replay the first record. topic_propose and propose_fix are
        # scored from the contract test (IDEM_NOT_MEASURED): the audit board has no fetched page or help thread.
        # the audit story is done by now and takes no criteria: probe on a fresh one
        fresh = a.call("architect", "ticket_create", {"kind": "story", "work_type": "chore", "parent_id": a.ids["epic"],
                       "title": "Idempotency probe story"}, task="idempotency_setup")
        target = (fresh.get("value") or {}).get("id") or a.ids["story"]
        keyed = [("engineer", "message_send", {"ticket_id": a.ids["story"], "kind": "note", "text": "Repeated note"}),
                 ("architect", "criterion_create", {"ticket_id": target, "text": "Repeated criterion",
                   "check": "command"}),
                 ("architect", "record_decision", {"scope": a.ids["epic"], "text": "Repeated decision"}),
                 ("engineer", "record_claim", {"scope": a.ids["epic"], "text": "Repeated claim"}),
                 ("engineer", "record_lesson", {"domain": "tool-layer", "topic": "idem", "text": "Repeated lesson"}),
                 ("sme", "topic_propose", {"topic_id": a.ids.get("topic"), "title": "Repeated proposal",
                   "body_md": "- [expected] repeated", "source_url": RESEARCH_URL})]
        same = 0
        for role, name, args in probes:
            first = a.call(role, name, args, task="idempotency")
            second = a.call(role, name, args, task="idempotency")
            same += bool(first.get("ok") and second.get("ok") and
                         (first.get("value") or {}).get("id") == (second.get("value") or {}).get("id"))
        for role, name, args in keyed:
            args = {**args, "idempotency_key": f"audit-{name}"}
            seat = "sme" if name == "topic_propose" else None
            first = a.call(role, name, args, task="idempotency", seat=seat)
            tool_idem.reset()
            second = a.call(role, name, args, task="idempotency", seat=seat)
            same += bool(first.get("ok") and second.get("ok") and (second.get("value") or {}).get("replay") and
                         (first.get("value") or {}).get("id") == (second.get("value") or {}).get("id"))
        total = len(probes) + len(keyed)
        return same == total, f"{same}/{total} duplicate creates returned same id ({len(keyed)} keyed, across a proxy reset)"
    a.task("idempotency", idempotency)


def scores(a: Audit) -> dict:
    """Score the owner's six standards per tool, with observable evidence, not a blanket pass."""
    rows = {}
    by_tool = defaultdict(list)
    for call in a.calls:
        by_tool[call["tool"]].append(call)
    object_roots = {"ticket", "criterion", "doc", "artifact", "message", "participant", "session", "gate",
                    "decision", "claim", "topic", "event", "workflow"}
    described = {c["args"].get("type") for c in a.calls if c["tool"] == "describe" and c["ok"]}
    repeated = defaultdict(list)
    for c in a.calls:
        if c["task"] == "idempotency":
            repeated[c["tool"]].append(c)
    for name, tool in ALL_TOOLS.items():
        calls = by_tool[name]
        desc = tool.description.lower()
        schema = tool.input_schema
        enums = enum_fields(tool.args_model)
        related = [part for part in name.split("_") if part in object_roots]
        advertises_object = not related or any(part in desc for part in related)
        # S23 (architect ruling m-fbd6ae40d3): the description names each enum arg + describe('enums');
        # the allowed values are advertised once, in the input schema
        props = schema.get("properties", {})
        advertises_enums = not enums or ("describe('enums')" in desc and all(
            f.lower() in desc and set(vals) <= set(props.get(f, {}).get("enum") or []) for f, vals in enums.items()))
        # A linked skill must be named where the tool has one; the mapping is explicit.
        skill = {"ticket": "ticket", "criterion": "verify", "artifact": "demo",
                 "why_stuck": "ticket", "doc_edit": "methodology"}.get(name, None)
        if skill is None:
            skill = next((s for prefix, s in (("ticket_", "ticket"), ("criterion_", "verify"),
                            ("artifact_", "demo")) if name.startswith(prefix)), None)
        advertises_skill = skill is None or skill in desc
        # S23: an opt-in full/verbose read may exceed the page; the standard is the DEFAULT call
        large = [c for c in calls if c["bytes_out"] > 8192
                 and not (c["args"].get("verbose") or c["args"].get("full"))]
        misses = [c for c in calls if c["error_code"] == "schema"]
        guidance = all((c["error"].split("'")[1] if "'" in c["error"] else "") in c["hint"] + c["error"]
                       for c in misses)
        idempotent = "not_applicable"
        if name in repeated:
            pairs = list(zip(repeated[name][::2], repeated[name][1::2]))
            idempotent = "pass" if pairs and all(x["ok"] and y["ok"] and x["result_id"] == y["result_id"]
                                                    for x, y in pairs) else "fail"
        elif name in IDEMPOTENT_CREATES:
            idempotent = "not_measured"
        reason = IDEM_NOT_MEASURED.get(name) if idempotent == "not_measured" else None
        described_status = "pass" if not related or all(root in described for root in related) else "fail"
        schema_status = "pass" if all(not field.is_required() or bool(field.description)
                                       for field in tool.args_model.model_fields.values()) else "fail"
        # Some errors are deliberately explored; a clear schema error names the field or enum.
        output_status = "pass" if not large and guidance else "fail"
        efficient = "pass" if not large else "fail"  # S23: per call, not harness sweep count
        ok_calls = sum(c["ok"] for c in calls)
        # T6 N5 (report-36481f7a4e): output and efficiency pass only on a SUCCESSFUL representative call; a tool
        # whose every call failed is not_measured with the reason, never a pass read off an error envelope
        unmeasured = None
        if not ok_calls and output_status == efficient == "pass":
            codes = sorted({str(c["error_code"]) for c in calls})
            unmeasured = (f"0 of {len(calls)} calls succeeded ({', '.join(codes)}): its successful reply was never "
                          "produced here, so clear output and token efficiency are unmeasured" if calls else
                          "no role bundle serves it, so the audit never called it: clear output and token "
                          "efficiency are unmeasured")
            output_status = efficient = "not_measured"
        rows[name] = {"roles": [r for r in ROLES if name in ROLE_BUNDLES[r]], "calls": len(calls),
                      "bytes_out": sum(c["bytes_out"] for c in calls),
                      "max_bytes_out": max((c["bytes_out"] for c in calls), default=0),
                      "over_8kb": len(large), "arg_misses": len(misses), "error_names_fix": guidance,
                      "ok_calls": ok_calls,
                      "standards": {"1_advertisement": "pass" if advertises_object and advertises_enums and advertises_skill else "fail",
                                    "2_idempotent": idempotent,
                                    **({"2_idempotent_reason": reason} if reason else {}),
                                    "3_clear_output": output_status,
                                    **({"3_clear_output_reason": unmeasured} if unmeasured else {}),
                                    "4_clear_schema": schema_status,
                                    "5_describe": described_status,
                                    "6_token_efficient": efficient,
                                    **({"6_token_efficient_reason": unmeasured} if unmeasured else {})},
                      "advertises": {"object": advertises_object, "enums": advertises_enums,
                                     "linked_skill": advertises_skill, "skill": skill}}
    return rows


# T3 F2: a create the audit cannot repeat on its private board, with where it IS measured. Any other
# not_measured create is unexplained and fails the ledger (scores' caller checks).
IDEM_NOT_MEASURED = {
    "propose_fix": "needs a help thread and its doctor seat (a /v1/help spawn); measured by tests/test_tool_contract.py::"
                   "test_every_idempotent_create_replays_by_key_across_restarts[propose_fix]",
}


# S23: guide hits that are NOT an agent workaround, each with its reason (T2 triage of report-e517e9e87e).
RULED_OUT = {
    ("guides/tailnet-public-mode.md", "framework_script"):
        "owner host operation: tailnet_readiness.py is the human owner's pre-flight on the host, not a seat step",
    ("guides/tailnet-public-mode.md", "board_rest"):
        "owner host operation: a curl proving the public route answers 401 without a token (no token sent)",
    ("guides/tailnet-public-mode.md", "token_file"):
        "names tokens.json as the readiness check and forbids hand edits; the teammate tool replaces the steps",
    (".claude/commands/doctor.md", "token_file"):
        "a prohibition: the doctor must never tell a person to hand-edit tokens.json",
    ("guides/astra-seat.md", "artifact_disk"):
        "a historical probe log path in a findings table, not an instruction",
}


def unexplained(hits: list[dict]) -> list[dict]:
    """Guide hits left after the ruled-out ones: each is a workaround an agent is still told to use."""
    out = []
    for h in hits:
        if h["source"] != "guide":
            continue
        left = [c for c in h["categories"] if (h["path"], c) not in RULED_OUT]
        if left:
            out.append({**h, "categories": left})
    return out


def scan_workarounds() -> list[dict]:
    """Find framework operations routed outside MCP; record locations, never secret contents."""
    rules = {
        # S23: /pain is the skill (it calls the pain tool now); only the retired CLI counts
        "pain_cli": re.compile(r"scripts[/\\]pain\.py", re.I),
        "harvest_cli": re.compile(r"scripts[/\\]harvest_cost\.py", re.I),
        "board_rest": re.compile(r"(?:curl|httpx|Invoke-RestMethod|urllib\.request).{0,240}/v1/|/v1/.{0,160}(?:curl|httpx)", re.I),
        "token_file": re.compile(r"tokens\.json", re.I),
        "database_file": re.compile(r"\.data[/\\](?:edp8\.db|[^\s]+\.db)|sqlite3\.connect", re.I),
        "framework_script": re.compile(r"scripts[/\\](?:tailnet_readiness|drill_|harvest_|pain)\S*\.py", re.I),
        "artifact_disk": re.compile(r"(?:Read|Get-Content|cat|read_text|open\().{0,160}(?:/tmp/|scratchpad|\.data/codex-images)", re.I),
    }
    hits: list[dict] = []
    for base in (ROOT / ".claude" / "commands", ROOT / ".claude" / "skills", ROOT / "guides"):
        for path in base.rglob("*.md"):
            for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                categories = [key for key, pattern in rules.items() if pattern.search(line)]
                if categories:
                    hits.append({"source": "guide", "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                                 "line": number, "categories": categories})
    transcript_root = ROOT.parent / "edp-pool" / ".claude-pool" / "projects"
    recent = sorted(transcript_root.glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:60]
    for path in recent:
        try:
            with path.open(encoding="utf-8", errors="replace") as stream:
                for number, line in enumerate(stream, 1):
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    content = row.get("message", {}).get("content") or []
                    for block in content if isinstance(content, list) else []:
                        if not isinstance(block, dict) or block.get("type") != "tool_use":
                            continue
                        if block.get("name") not in {"Bash", "Read", "Grep", "Glob"}:
                            continue
                        inp = block.get("input") or {}
                        command = str(inp.get("command") or inp.get("file_path") or inp.get("path") or "")
                        categories = [key for key, pattern in rules.items() if pattern.search(command)]
                        if categories:
                            hits.append({"source": "transcript", "path": path.name, "line": number,
                                         "categories": categories, "tool": block.get("name")})
        except OSError:
            continue
    return hits


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True, help="machine-readable task/call/tool ledger")
    p.add_argument("--home", type=Path, help="private home (default: a new temp dir)")
    p.add_argument("--board-port", type=int, default=19400)
    p.add_argument("--pool-port", type=int, default=19301)
    args = p.parse_args()
    home = (args.home or Path(tempfile.mkdtemp(prefix="edp-tool-audit-"))).resolve()
    if home == ROOT or ROOT in home.parents or SOURCE_DB in home.parents:
        # An explicit workspace home is possible, but must never be the live .data tree.
        if home == ROOT or home == ROOT / ".data" or ROOT / ".data" in home.parents:
            raise SystemExit("private home must not be the workspace root or live .data")
    audit = Audit(home, free_port(args.board_port), free_port(args.pool_port))
    try:
        audit.start()
        workflow(audit)
        coverage(audit)
        def coverage_grep():
            left = unexplained(scan_workarounds())
            return True, f"cards/skills/guides scanned; {len(RULED_OUT)} ruled out with a reason", \
                [f"{h['path']}:{h['line']} {','.join(h['categories'])}" for h in left]
        audit.task("coverage_grep", coverage_grep)
    finally:
        audit.stop()
        workaround_hits = scan_workarounds()
        tools = scores(audit)
        matrix = matrix_summary(tools)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(encoded({"source_db": ".data/edp8.db", "private_home": "<temporary-private-home>",
                                      "board_port": audit.board_port, "pool_port": audit.pool_port,
                                      "tasks": audit.tasks, "calls": audit.calls, "tools": tools,
                                      "matrix": matrix, "workaround_hits": workaround_hits,
                                      "completeness_exempt": COMPLETENESS_EXEMPT}))
        print(json.dumps({"type": "matrix", **matrix, "completeness_exempt": COMPLETENESS_EXEMPT},
                         ensure_ascii=True), flush=True)
    return 0 if all(t["pass"] for t in audit.tasks) and not matrix["failing"] and not matrix["unexplained"] else 1


def matrix_summary(tools: dict) -> dict:
    """The six-standard matrix in counts. A `not_measured` cell without a written reason is `unexplained`
    (T3 F2: 7 such cells hid behind "0 failing tools")."""
    counts: dict[str, int] = defaultdict(int)
    failing, unexplained, not_measured = [], [], {}
    for name, row in tools.items():
        for std, cell in row["standards"].items():
            if std.endswith("_reason"):
                continue
            counts[cell] += 1
            if cell == "fail":
                failing.append(f"{name}.{std}")
            if cell == "not_measured" and f"{std}_reason" not in row["standards"]:
                unexplained.append(f"{name}.{std}")
            elif cell == "not_measured":  # T6 N5: surfaced with its reason, never hidden in a count
                not_measured[f"{name}.{std}"] = row["standards"][f"{std}_reason"]
    return {"tools": len(tools), "cells": dict(counts), "failing": failing, "unexplained": unexplained,
            "not_measured": not_measured}


if __name__ == "__main__":
    raise SystemExit(main())
