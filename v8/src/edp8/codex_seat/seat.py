"""CodexSeat — one `codex app-server` thread driven as an edp8 fleet seat.

    seat = CodexSeat(cwd=..., role="engineer", handle="engineer.s-…", log_dir=..., env={...})
    seat.start()                       # spawn app-server (contained), initialize, thread/start|resume
    seat.enqueue_turn(role_card)       # first input = the role card (design §3 N5)
    seat.wait()                        # resident until the app-server exits

Containment (c-1113387020, architect m-c50e181c7f): every MCP server `codex mcp list --json`
reports is disabled (consult.py's discover-and-disable, fail-closed), the edp8 board is the ONE server
added, its identity headers come from env by NAME (`env_http_headers`), and `live_mcp_servers()` reads
the thread's actual set back so a test/drill can assert it is exactly {edp8}.

A seat is otherwise NORMAL codex (owner ruling m-56c204aa9a, dec-3dc3047782): every feature keeps
codex's own value except `apps`, the one feature measured to inject an MCP server (`codex_apps`,
73 tools; p-8b8c035f, re-measured 2026-09-23 with all other features at their defaults: live set {}).
The role's skills (the **SKILLS** line of its role card, .claude/skills/<name>) are bound per seat with
the app-server's `skills/extraRoots/set`, so the seat sees exactly its bundle and nothing is written
to the tree or to ~/.codex (measured on 0.156.0: per-skill roots are honoured, config.toml untouched).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from collections.abc import Callable
from pathlib import Path

from .rpc import AppServer, RpcError, redactor
from .tools import Delivery, SeatTools

BOARD_SERVER = "edp8"

#: role card line naming the role's skill bundle: `**SKILLS** /verify · /deviation · /pain`
SKILLS_LINE = re.compile(r"^\*\*SKILLS\*\*(.*)$", re.M)

#: codex sandbox per role: doing seats write the workspace, checking seats inspect read-only —
#: consult.py's two modes ("workspace-write" for build/concept, "read-only" for design/verify)
ROLE_SANDBOX: dict[str, str] = {
    "engineer": "workspace-write", "sme": "workspace-write", "architect": "workspace-write",
    "qa": "workspace-write", "owner": "workspace-write",
    "adversary": "read-only",
}

#: native thread items that are TOOLS (a notification arriving while one runs is steered after it)
NATIVE_TOOL_ITEMS: dict[str, str] = {
    "commandExecution": "bash", "fileChange": "edit", "mcpToolCall": "mcp", "webSearch": "web_search",
    "imageView": "view_image", "collabAgentToolCall": "agent",
}


def find_codex(explicit: str | None = None) -> str:
    cand = explicit or os.environ.get("EDP_CODEX_BIN")
    if cand:
        return cand
    exe = shutil.which("codex")
    if not exe:
        raise FileNotFoundError("codex not found: set EDP_CODEX_BIN or put codex on PATH")
    return exe


def containment_args(codex: str, *, discover: Callable | None = None, env: dict[str, str] | None = None,
                     cwd: str | None = None) -> tuple[list[str], list[str]]:
    """(`-c` args, disabled server names). Fail-closed: a discovery error raises. Discovery runs in the
    LAUNCH context (env/cwd), so it reads the config the launched app-server will load."""
    from ..consult import discover_mcp_servers, mcp_containment_args, mcp_disabled_names
    if discover is not None:
        servers, err = discover(codex)
    else:
        servers, err = discover_mcp_servers(codex, env=env, cwd=cwd)
    if err:
        raise RuntimeError(f"MCP discovery failed, refusing to start an uncontained seat: {err}")
    servers = [s for s in servers if s["name"] != BOARD_SERVER]  # ours is redefined below
    # consult.py's path: every listed server off + HIDDEN_SERVER_FEATURES (apps) off; nothing else
    return mcp_containment_args(servers), mcp_disabled_names(servers)


def role_skill_roots(agent_home: str | os.PathLike[str], role: str) -> list[str]:
    """The role's skill dirs: the names on its role card's **SKILLS** line that exist as
    .claude/skills/<name>/SKILL.md; every skill there when the card names none."""
    home = Path(agent_home)
    skills = home / ".claude" / "skills"
    card = home / ".claude" / "commands" / f"{role}.md"
    m = SKILLS_LINE.search(card.read_text(encoding="utf-8")) if card.is_file() else None
    if m:
        names = re.findall(r"/([A-Za-z0-9_-]+)", m.group(1))
    else:
        names = sorted(d.name for d in skills.iterdir()) if skills.is_dir() else []
    return [str((skills / n).resolve()) for n in names if (skills / n / "SKILL.md").is_file()]


def board_args(role: str, mcp_url: str | None = None) -> list[str]:
    """The edp8 board as streamable-HTTP MCP, identity headers read from env BY NAME (never argv)."""
    base = (mcp_url or os.environ.get("EDP8_MCP_URL") or "http://127.0.0.1:9402").rstrip("/")
    headers = '{"X-Participant"="EDP_HANDLE","X-Session"="EDP_SPAWN_SESSION_ID","X-Token"="EDP8_TOKEN"}'
    # measured 2026-09-23 (codex-cli 0.156.0, drill_codex_seat.py): under approval_policy=never every
    # MCP call fails "MCP tool call requires approval" unless the server pre-approves its tools — edp8
    # is the one server a seat may reach, so its tools are approved (every other server is disabled)
    # enabled=true: an inherited `[mcp_servers.edp8] enabled=false` must not leave a board-less seat (qa #7)
    return ["-c", f'mcp_servers.{BOARD_SERVER}.url="{base}/mcp/{role}"',
            "-c", f"mcp_servers.{BOARD_SERVER}.enabled=true",
            "-c", f'mcp_servers.{BOARD_SERVER}.default_tools_approval_mode="approve"',
            "-c", f"mcp_servers.{BOARD_SERVER}.env_http_headers={headers}",
            "-c", f"mcp_servers.{BOARD_SERVER}.startup_timeout_sec=60",
            "-c", f"mcp_servers.{BOARD_SERVER}.tool_timeout_sec=1800"]


def sandbox_for(role: str, env: dict[str, str]) -> str:
    return env.get("EDP_CODEX_SANDBOX") or ROLE_SANDBOX.get(role, "read-only")


def codex_head(codex: str) -> list[str]:
    """argv head for `codex`: a .py "codex" is the test double (tests/codex_seat/fake_app_server.py)."""
    return [sys.executable, codex] if codex.endswith(".py") else [codex]


def monitor_sandbox_prefix(codex: str, mode: str) -> list[str]:
    """`codex sandbox` argv that runs a Monitor command under the seat's own sandbox policy (qa adversary
    #1). Measured 2026-09-23 (codex-cli 0.156.0, Windows restricted token): read-only refuses a write to
    /c/Temp, workspace-write refuses it outside the cwd and allows it inside, stdout streams line by
    line, env (EDP8_TOKEN included) passes through, and the command is a descendant of this argv's
    process (codex → codex-command-runner → bash), so taskkill /T and the runner's job still reach it.
    The mode is an unquoted TOML fallback string (codex.CMD re-quotes argv through cmd.exe)."""
    args = [*codex_head(codex), "sandbox", "-c", f"sandbox_mode={mode}"]
    if mode == "workspace-write":
        args += ["-c", "sandbox_workspace_write.network_access=true"]
    return [*args, "--"]


class CodexSeat:
    def __init__(self, *, cwd: str | os.PathLike[str], role: str, handle: str, log_dir: str | os.PathLike[str],
                 env: dict[str, str] | None = None, model: str | None = None, effort: str | None = None,
                 codex_bin: str | None = None, board: bool = True, ephemeral: bool = False,
                 developer_instructions: str | None = None, discover: Callable | None = None,
                 on_event: Callable[[str, dict], None] | None = None, creationflags: int = 0,
                 ws: bool = False, skill_roots: list[str] | None = None):
        self.ws = ws  # monitor mode: the app-server listens on a loopback websocket the native TUI joins
        self.cwd = str(Path(cwd).resolve())
        self.role = role
        self.handle = handle
        self.log_dir = Path(log_dir)
        self.env = {**os.environ, **(env or {})}
        self.model = model or self.env.get("EDP_CODEX_MODEL") or "gpt-6-astra"
        self.effort = effort or self.env.get("EDP_CODEX_EFFORT") or None
        self.codex = find_codex(codex_bin)
        self.board = board
        self.ephemeral = ephemeral
        self.developer_instructions = developer_instructions
        self._discover = discover
        self.on_event = on_event or (lambda _m, _p: None)
        self.creationflags = creationflags
        self.thread_id: str | None = None
        self.disabled_servers: list[str] = []
        self.state_path = self.log_dir / "codex-sessions" / f"{handle}.json"
        self.log_path = self.log_dir / f"codex-seat.{handle}.jsonl"
        self._elog = self.log_dir / f"codex-seat.{handle}.events.log"
        self._redact = redactor(self.env)
        self.live_servers: list[str] = []
        self.skill_roots = role_skill_roots(self.cwd, role) if skill_roots is None else skill_roots
        self.skills: list[str] = []  # the role skills the app-server's catalog lists (read back at boot)
        self.delivery = Delivery(self._start_turn, self._steer, log=self._log)
        tasks = self.env.get("EDP_CODEX_TASKS_DIR") or str(self.log_dir / "tasks" / handle)
        self.tools = SeatTools(self.delivery, cwd=self.cwd, tasks_dir=tasks, env=self.env, log=self._log,
                               sandbox_prefix=monitor_sandbox_prefix(self.codex, sandbox_for(role, self.env)))
        self.server: AppServer | None = None
        self.last_error: dict | None = None
        self.quota_reported = False

    # ------------------------------------------------------------------ logging
    def _log(self, line: str) -> None:
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            with open(self._elog, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {self._redact(line)}\n")
        except OSError:
            pass

    # ------------------------------------------------------------------ boot
    def argv(self) -> list[str]:
        cargs, self.disabled_servers = containment_args(self.codex, discover=self._discover, env=self.env, cwd=self.cwd)
        argv = [*codex_head(self.codex), "app-server", *cargs, "-c", "approval_policy=never"]
        if self.board:
            argv += board_args(self.role, self.env.get("EDP8_MCP_URL"))
        if sandbox_for(self.role, self.env) == "workspace-write":
            # the seat reaches the board and local test servers from its shell, like a Claude seat
            argv += ["-c", "sandbox_workspace_write.network_access=true"]
        return argv

    def start(self, resume: bool = False) -> dict:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.server = AppServer(self.argv(), cwd=self.cwd, env=self.env, log_path=self.log_path,
                                on_notification=self._on_notification, on_request=self._on_request,
                                creationflags=self.creationflags, ws=self.ws)
        self.server.start()
        self.server.request("initialize", {"clientInfo": {"name": "edp8-codex-seat", "title": "edp8 codex seat", "version": "1"},
                                           "capabilities": {"experimentalApi": True, "requestAttestation": False}})
        self.server.notify("initialized")
        self._bind_skills()  # before thread/start|resume: the thread's catalog is built from these roots
        prior = self._read_state() if resume else None
        if resume and not (prior and prior.get("threadId")):
            # a requested resume never silently becomes a fresh thread (the model would be told it resumed)
            self.server.stop()
            raise RuntimeError(f"resume requested but {self.state_path} holds no valid threadId")
        if prior and prior.get("threadId"):
            res = self.server.request("thread/resume", {"threadId": prior["threadId"], "cwd": self.cwd,
                                                        "sandbox": sandbox_for(self.role, self.env), "model": self.model,
                                                        "excludeTurns": True}, timeout=120)
            self._log(f"thread/resume {prior['threadId']}")
        else:
            params: dict = {"model": self.model, "cwd": self.cwd, "sandbox": sandbox_for(self.role, self.env),
                            "approvalPolicy": "never", "ephemeral": self.ephemeral,
                            "dynamicTools": self.tools.specs()}
            if self.developer_instructions:
                params["developerInstructions"] = self.developer_instructions
            if self.effort:
                params["config"] = {"model_reasoning_effort": self.effort}
            res = self.server.request("thread/start", params, timeout=120)
        self.thread_id = res["thread"]["id"]
        self._enforce_allowlist()
        self._write_state()
        self.tools.start()
        return res

    def _bind_skills(self) -> None:
        """Owner ruling m-56c204aa9a: the role's skills are visible to the seat. Per-seat extra roots on
        the app-server (the TUI joins the same server, so it sees the same catalog); read back with
        skills/list so the boot banner and a drill can prove which ones landed."""
        if not self.skill_roots:
            return
        assert self.server
        try:
            self.server.request("skills/extraRoots/set", {"extraRoots": self.skill_roots}, timeout=60)
            res = self.server.request("skills/list", {"cwds": [self.cwd]}, timeout=60)
        except RpcError as e:  # an older codex without the RPC: the seat runs, the gap is logged
            self._log(f"skills not bound: {e}")
            return
        roots = {os.path.normcase(r) for r in self.skill_roots}
        self.skills = sorted({k["name"] for e in (res or {}).get("data", []) for k in e.get("skills", [])
                              if os.path.normcase(str(Path(k.get("path", "")).parent)) in roots})
        self._log(f"skills bound: {self.skills}")

    def _enforce_allowlist(self) -> None:
        """Fail closed BEFORE the first turn: the thread's live MCP set must be exactly what we added
        ({edp8} with the board, {} without). A server that discovery never saw stops the seat here."""
        allowed = {BOARD_SERVER} if self.board else set()
        try:
            live = set(self.live_mcp_servers())
        except Exception as e:  # noqa: BLE001
            self.server.stop()  # type: ignore[union-attr]
            raise RuntimeError(f"cannot read the thread's MCP set, refusing an unverified seat: {e}") from e
        self.live_servers = sorted(live)
        if live != allowed:  # equality (qa #7): an extra server AND a missing board both refuse the seat
            self.server.stop()  # type: ignore[union-attr]
            raise RuntimeError(f"thread MCP set {sorted(live)} != required {sorted(allowed)}: "
                               f"uncontained {sorted(live - allowed)}, missing {sorted(allowed - live)}")

    def _read_state(self) -> dict | None:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _write_state(self) -> None:
        if self.ephemeral:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_name(f"{self.state_path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"threadId": self.thread_id, "role": self.role, "handle": self.handle,
                                   "model": self.model, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}),
                       encoding="utf-8")
        os.replace(tmp, self.state_path)  # atomic: a kill mid-write never leaves a half file

    def live_mcp_servers(self) -> list[str]:
        """Servers ACTUALLY live in this thread: any tool catalog, or a runtimeStatus other than
        "disabled" (a disabled server is still LISTED, with runtimeStatus "disabled" — measured 0.156.0)."""
        assert self.server
        res = self.server.request("mcpServerStatus/list", {"threadId": self.thread_id}, timeout=120)
        return sorted(s["name"] for s in res.get("data", [])
                      if s.get("tools") or s.get("runtimeStatus") not in (None, "disabled"))

    # ------------------------------------------------------------------ turns
    def enqueue_turn(self, text: str) -> None:
        self.delivery.enqueue_turn(text)

    def _start_turn(self, text: str, msg_id: str) -> bool | None:
        """True accepted · False refused (an RPC error: safe to resend) · None unknown (timeout).
        `msg_id` is stable across resends of the same input (Delivery), echoed back as the item clientId."""
        if not self.server or not self.thread_id:
            return False
        params: dict = {"threadId": self.thread_id, "clientUserMessageId": msg_id,
                        "input": [{"type": "text", "text": text, "text_elements": []}]}
        if self.effort:
            params["effort"] = self.effort
        try:
            res = self.server.request("turn/start", params, timeout=60)
        except (RpcError, OSError) as e:  # OSError: the pipe is gone, nothing was sent
            self._log(f"turn/start refused: {e}")
            return False
        except TimeoutError as e:
            self._log(f"turn/start timed out (outcome unknown): {e}")
            return None
        # turn_started ignores an id whose turn/completed the dispatcher already processed
        self.delivery.turn_started((res or {}).get("turn", {}).get("id"))
        return True

    def _steer(self, text: str, turn_id: str, msg_id: str) -> bool | None:
        if not self.server or not self.thread_id:
            return False
        try:
            self.server.request("turn/steer", {"threadId": self.thread_id, "expectedTurnId": turn_id,
                                               "clientUserMessageId": msg_id,
                                               "input": [{"type": "text", "text": text, "text_elements": []}]}, timeout=30)
            return True
        except (RpcError, OSError) as e:
            self._log(f"turn/steer refused: {e}")
            return False
        except TimeoutError as e:
            self._log(f"turn/steer timed out (outcome unknown: kept pending until witnessed): {e}")
            return None

    # ------------------------------------------------------------------ server → us
    def _on_notification(self, method: str, p: dict) -> None:
        if method == "turn/started":
            self.delivery.turn_started(p.get("turn", {}).get("id"))
        elif method == "turn/completed":
            turn = p.get("turn") or {}
            if turn.get("error"):
                self.last_error = turn["error"]
                self._log(f"turn error: {json.dumps(turn['error'])[:300]}")
                self._maybe_report_quota(turn["error"])
            self.delivery.turn_completed(turn.get("id"))
        elif method in ("item/started", "item/completed"):
            item = p.get("item") or {}
            if item.get("type") == "userMessage":
                self.delivery.message_seen(item.get("clientId"))  # our input landed: the dedup witness
            native = NATIVE_TOOL_ITEMS.get(item.get("type", ""))
            if native:
                if item.get("type") == "mcpToolCall":
                    native = f"mcp:{item.get('server')}/{item.get('tool')}"
                if method == "item/started":
                    self.delivery.native_started(native, item.get("id"))
                else:
                    self.delivery.native_completed(item.get("id"))  # per item: a parallel sibling keeps running
        self.on_event(method, p)

    def _on_request(self, method: str, p: dict) -> dict | None:
        if method == "item/tool/call":
            text, ok = self.tools.call(p.get("tool", ""), p.get("arguments") or {}, p.get("callId", ""))
            return {"contentItems": [{"type": "inputText", "text": text}], "success": ok}
        if method in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval"):
            return {"decision": "decline"}  # approval_policy=never: nothing should ask; never auto-grant
        return None

    def _maybe_report_quota(self, err: dict) -> None:
        """The HARNESS publishes a quota block, not the capped model (design §7 S8 [Astra])."""
        info = err.get("codexErrorInfo")
        if info not in ("usageLimitExceeded", "rateLimitExceeded") or self.quota_reported or not self.board:
            return
        self.quota_reported = True
        text = f"inference capped ({info}): {err.get('message', '')[:300]}"
        try:
            assert self.server
            self.server.request("mcpServer/tool/call", {"threadId": self.thread_id, "server": BOARD_SERVER,
                                                        "tool": "record_status", "arguments": {"status": "blocked", "text": text}},
                                timeout=60)
        except Exception as e:  # noqa: BLE001
            self._log(f"record_status(blocked) failed: {e}")

    # ------------------------------------------------------------------ native TUI (monitor mode)
    def tui_argv(self) -> list[str]:
        """The native codex TUI joined to THIS seat's thread on its app-server (owner ruling m-0e7b8fdd7f):
        what the owner sees and types into. The ws token reaches it by env NAME, never argv."""
        from .rpc import WS_TOKEN_ENV
        assert self.server and self.server.ws_url and self.thread_id
        # check_for_update_on_startup=false: measured 2026-09-23, a newer codex release (0.156.1) makes the
        # TUI open on a modal "Update now / Skip" prompt that holds the seat's screen until someone answers
        return [*codex_head(self.codex), "resume", self.thread_id, "--remote", self.server.ws_url,
                "--remote-auth-token-env", WS_TOKEN_ENV, "-c", "check_for_update_on_startup=false", "-C", self.cwd]

    def tui_env(self) -> dict[str, str]:
        assert self.server
        return dict(self.server.env)  # carries WS_TOKEN_ENV

    # ------------------------------------------------------------------ lifecycle
    def alive(self) -> bool:
        return self.server is not None and self.server.alive()

    @property
    def pid(self) -> int | None:
        return self.server.pid if self.server else None

    def wait(self, timeout: float | None = None) -> bool:
        assert self.server
        return self.server.exited.wait(timeout)

    def stop(self) -> None:
        self.tools.shutdown()
        if self.server and self.server.alive() and self.delivery.turn_id and self.thread_id:
            try:
                self.server.request("turn/interrupt", {"threadId": self.thread_id, "turnId": self.delivery.turn_id}, timeout=5)
            except Exception:  # noqa: BLE001
                pass
        if self.server:
            self.server.stop()


def idle_waiter(seat: CodexSeat, timeout: float) -> bool:
    """Block until the seat is idle with nothing queued (tests / oracle driver)."""
    end = time.time() + timeout
    while time.time() < end:
        if seat.delivery.is_idle() and not seat.delivery.pending:
            return True
        time.sleep(0.2)
    return False


