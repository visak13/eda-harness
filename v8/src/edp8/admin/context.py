"""What the admin routes need from the app: the board, the tokens file writers `create_app` owns, and
last-seen. One object, so each panel module takes `ctx` and nothing reaches into `service.py` closures."""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..board import Board


class LastSeen:
    """When each participant last made an authenticated request. In memory, flushed to `path` at most
    every `flush_every` seconds (a restart loses under a minute of it); loaded back at start."""

    def __init__(self, path: Path | None, flush_every: float = 60.0) -> None:
        self.path = path
        self.flush_every = flush_every
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()
        self._flushed = time.time()
        if path is not None:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                self._seen = {str(k): float(v) for k, v in raw.items()} if isinstance(raw, dict) else {}
            except (OSError, ValueError, TypeError):
                self._seen = {}

    def touch(self, participant_id: str) -> None:
        now = time.time()
        with self._lock:
            self._seen[participant_id] = now
            due = now - self._flushed >= self.flush_every
            if due:
                self._flushed = now
                snapshot = dict(self._seen)
        if due:
            self._write(snapshot)

    def get(self, participant_id: str) -> float | None:
        with self._lock:
            return self._seen.get(participant_id)

    def flush(self) -> None:
        with self._lock:
            snapshot = dict(self._seen)
            self._flushed = time.time()
        self._write(snapshot)

    def _write(self, snapshot: dict[str, float]) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(snapshot), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass  # last-seen is a convenience; never fail a request over it


@dataclass
class AdminContext:
    board: Board
    #: (humans, agents) handle -> secret from the app's tokens file ({} , {} in trusted mode)
    tokens: Callable[[], tuple[dict[str, str], dict[str, str]]]
    #: apply `update(data)` to the tokens file atomically (raises when it is absent or unreadable)
    write_tokens: Callable[[Callable[[dict[str, Any]], None]], None]
    tokens_file: Callable[[], Path]
    last_seen: LastSeen = field(default_factory=lambda: LastSeen(None))
