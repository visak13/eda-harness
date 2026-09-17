"""PiSeat — a Pi RPC process driven from Python (strict JSONL on stdio, LF-delimited).

    seat = PiSeat(cwd=..., model="openai/gpt-6-astra", extension=".pi/extensions/edp8.ts", env={...})
    seat.start()
    seat.prompt("<role card text>")          # first input = role card (design §3 N5)
    for ev in seat.events(timeout=600):      # yields dicts; stops after agent_settled
        ...
    seat.stop()

Rules: EDP8_TOKEN travels in env only, never argv/logs (shared-host rules). Every stdout record is
mirrored to `<log_dir>/pi-seat.<handle>.jsonl` for the parity oracle (model-input boundary is
captured by the extension's `before_provider_request` hook, not here).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from queue import Empty, Queue

SETTLED = "agent_settled"
_SECRET_KEYS = ("EDP8_TOKEN", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")


def find_pi(explicit: str | None = None) -> list[str]:
    """argv prefix for Pi: EDP_PI_BIN (a cli.js path → run under node, or an exe), else `pi` on PATH."""
    cand = explicit or os.environ.get("EDP_PI_BIN")
    if cand:
        p = Path(cand)
        if p.suffix == ".js":
            return ["node", str(p)]
        return [str(p)]
    for cli in default_pi_cli_candidates():
        if cli.is_file():
            return ["node", str(cli)]
    exe = shutil.which("pi")
    if not exe:
        raise FileNotFoundError("pi not found: install it under edp-pool/.pi-harness (npm install --ignore-scripts), "
                                "set EDP_PI_BIN to <pi-coding-agent>/dist/cli.js, or put pi on PATH")
    return [exe]


PI_CLI_REL = Path("node_modules") / "@earendil-works" / "pi-coding-agent" / "dist" / "cli.js"


def default_pi_cli_candidates() -> list[Path]:
    """Durable install locations (qa report-fb5ff85cd9 §1): `<repo>/edp-pool/.pi-harness` — package.json +
    lockfile committed, node_modules ignored — next to the agent home, or EDP_PI_HARNESS."""
    out: list[Path] = []
    env = os.environ.get("EDP_PI_HARNESS", "").strip()
    if env:
        out.append(Path(env) / PI_CLI_REL)
    here = Path(__file__).resolve()
    for base in [Path.cwd(), *here.parents]:
        out.append(base / "edp-pool" / ".pi-harness" / PI_CLI_REL)
        out.append(base.parent / "edp-pool" / ".pi-harness" / PI_CLI_REL)
    return out


class PiSeat:
    def __init__(
        self,
        *,
        cwd: str | os.PathLike[str],
        model: str | None = None,
        extension: str | None = None,
        session_file: str | None = None,
        env: dict[str, str] | None = None,
        log_dir: str | os.PathLike[str] | None = None,
        handle: str = "seat",
        pi_bin: str | None = None,
        thinking: str | None = None,
    ) -> None:
        self.cwd = str(cwd)
        self.model = model
        self.extension = extension
        self.session_file = session_file
        self.env = {**os.environ, **(env or {})}
        self.handle = handle
        self.log_path = Path(log_dir or self.cwd) / f"pi-seat.{handle}.jsonl"
        self.pi_bin = pi_bin
        self.thinking = thinking
        self.proc: subprocess.Popen[str] | None = None
        self._q: Queue[dict] = Queue()
        self._reader: threading.Thread | None = None
        self._seq = 0
        self.last_output_ts = 0.0
        self.exit_code: int | None = None

    # ---------------------------------------------------------------- process
    def argv(self) -> list[str]:
        a = [*find_pi(self.pi_bin), "--mode", "rpc"]
        if self.model:
            a += ["--model", self.model]
        if self.extension:
            a += ["-e", self.extension]
        if self.session_file:
            a += ["--session", self.session_file]
        else:
            a += ["--no-session"]
        if self.thinking:
            a += ["--thinking", self.thinking]
        return a

    def start(self) -> None:
        argv = self.argv()
        for k in _SECRET_KEYS:  # belt and braces: secrets never on argv
            assert not any(self.env.get(k) and self.env[k] in x for x in argv), f"{k} leaked into argv"
        self.proc = subprocess.Popen(
            argv,
            cwd=self.cwd,
            env=self.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=open(self.log_path.with_suffix(".stderr.log"), "ab"),
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self._reader = threading.Thread(target=self._pump, name=f"pi-seat-{self.handle}", daemon=True)
        self._reader.start()

    def _pump(self) -> None:
        assert self.proc and self.proc.stdout
        with open(self.log_path, "a", encoding="utf-8") as log:
            for raw in self.proc.stdout:
                line = raw.rstrip("\r\n")
                if not line:
                    continue
                self.last_output_ts = time.time()
                try:
                    obj = json.loads(line)
                except ValueError:
                    obj = {"type": "raw", "line": line}
                log.write(json.dumps({"ts": self.last_output_ts, **obj}, ensure_ascii=False) + "\n")
                log.flush()
                self._q.put(obj)
        self.exit_code = self.proc.wait()
        self._q.put({"type": "process_exit", "code": self.exit_code})

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    @property
    def pid(self) -> int | None:
        return self.proc.pid if self.proc else None

    # ---------------------------------------------------------------- commands
    def send(self, obj: dict) -> str:
        assert self.proc and self.proc.stdin
        self._seq += 1
        rid = obj.get("id") or f"r{self._seq}"
        obj = {"id": rid, **obj}
        self.proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        return rid

    def prompt(self, text: str) -> str:
        return self.send({"type": "prompt", "message": text})

    def steer(self, text: str) -> str:
        return self.send({"type": "steer", "message": text})

    def follow_up(self, text: str) -> str:
        return self.send({"type": "follow_up", "message": text})

    def get_state(self) -> dict:
        rid = self.send({"type": "get_state"})
        return self.wait_response(rid)

    def wait_response(self, rid: str, timeout: float = 30) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                ev = self._q.get(timeout=max(0.0, deadline - time.time()))
            except Empty:
                break
            if ev.get("type") == "response" and ev.get("id") == rid:
                return ev
            self._q.put(ev)  # not ours; re-queue (order among unrelated events is not needed here)
            time.sleep(0.01)
        raise TimeoutError(f"no response for {rid}")

    def events(self, timeout: float = 600, until: str = SETTLED) -> Iterator[dict]:
        """Yield stdout records until `until` (default agent_settled) or timeout."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                ev = self._q.get(timeout=max(0.0, min(1.0, deadline - time.time())))
            except Empty:
                continue
            yield ev
            if ev.get("type") in (until, "process_exit"):
                return

    def stop(self, grace: float = 5.0) -> None:
        if not self.alive():
            return
        try:
            self.send({"type": "clear_queue"})
            self.send({"type": "abort"})
            assert self.proc
            self.proc.stdin.close()  # type: ignore[union-attr]
            self.proc.wait(timeout=grace)
        except Exception:
            pass
        if self.alive():
            assert self.proc
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True)
            else:
                self.proc.kill()
