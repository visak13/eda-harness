"""The logging contract — one structured-JSON line schema for every service.

Mandatory fields: ts, svc, level, kind, detail. Recommended fields
(trace_id, corr_id, recipe_id, plan_id, session_id) ride via ``extra``.
Never ``print()`` — enforced by ruff flake8-print (T20) in pyproject
(TESTPLAN ST-3 / LOG-4).
"""

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler


class _WindowsSafeRotatingHandler(TimedRotatingFileHandler):
    """TimedRotatingFileHandler that SURVIVES Windows rename contention
    (2026-07-20, live finding): the midnight rollover renames the live
    log, and WinError 32 fires when ANY other process holds the file
    open (a second service instance, a tail, an editor) — stock
    behavior then spams a full stack trace on EVERY emit and never
    rotates. Rotation is a nicety; logging is load-bearing. On rename
    failure: skip this rollover, keep writing the current file, retry
    at the next midnight."""

    def doRollover(self) -> None:  # noqa: N802 — stdlib name
        try:
            super().doRollover()
        except OSError:
            # reopen the stream if the failed rollover closed it, and
            # push the next rollover a day out so we do not re-attempt
            # (and re-fail) on every subsequent emit.
            if self.stream is None or self.stream.closed:
                try:
                    self.stream = self._open()
                except OSError:
                    pass
            self.rolloverAt = self.computeRollover(
                int(__import__("time").time()))
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

# LogLevel stays `Literal` (not StrEnum): used only as a Pydantic field type.
LogLevel = Literal["debug", "info", "warning", "error"]

_LOGGER_NAMESPACE = "edp"
_DEFAULT_SVC = "unknown"
_DEFAULT_KIND = "log"


class LogRecordModel(BaseModel):
    """Schema every emitted log line conforms to.

    ``extra="allow"`` so recommended fields are open-ended without
    weakening the mandatory five.
    """

    model_config = ConfigDict(extra="allow")

    ts: datetime
    svc: str
    level: LogLevel
    kind: str
    detail: str


class _DynamicStderrHandler(logging.StreamHandler):
    """StreamHandler that resolves ``sys.stderr`` at emit time.

    A plain ``StreamHandler(sys.stderr)`` binds the stream at construction.
    Because the handler is created once per logger-name and reused, it would
    otherwise keep writing to a stale stderr after any redirection (real:
    log rotation / capture; tests: pytest capsys swaps stderr per test).
    Resolving lazily is both more correct and what makes the logger
    testable.
    """

    @property
    def stream(self):  # type: ignore[override]
        return sys.stderr

    @stream.setter
    def stream(self, _value):  # ignore StreamHandler.__init__'s assignment
        pass


class _JsonLineFormatter(logging.Formatter):
    """Render a record as one LogRecordModel-shaped JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "svc": getattr(record, "svc", _DEFAULT_SVC),
            "level": record.levelname.lower(),
            "kind": getattr(record, "kind", _DEFAULT_KIND),
            "detail": record.getMessage(),
        }
        extra = getattr(record, "edp_fields", None)
        if extra:
            payload.update(extra)
        # Validate-shape in debug builds is overkill per line; the schema is
        # asserted in tests (LOG-1..3). Keep the hot path cheap.
        return json.dumps(payload, default=str)


@runtime_checkable
class LoggerLike(Protocol):
    """The structured-logger surface consumers type against / inject doubles
    for (S3b refactor: a Protocol lets tests substitute a fake logger and
    lets callers annotate against an interface, not the concrete class)."""

    def debug(self, kind: str, detail: str, **fields: Any) -> None: ...
    def info(self, kind: str, detail: str, **fields: Any) -> None: ...
    def warning(self, kind: str, detail: str, **fields: Any) -> None: ...
    def error(self, kind: str, detail: str, **fields: Any) -> None: ...


def _log_discriminator() -> str | None:
    """A per-PROCESS file suffix so concurrent shells (each its own MCP
    server) write SEPARATE files — no cross-process rotation race, and
    you can find a stalled worker's log by its handle. EDP_LOG_SUFFIX
    wins; else the sanitized EDP_HANDLE (plan:action / recipe:step);
    else None (single file — fine for the singleton pool/broker)."""
    raw = os.environ.get("EDP_LOG_SUFFIX") or os.environ.get("EDP_HANDLE")
    if not raw:
        return None
    return re.sub(r"[^A-Za-z0-9._-]", "_", raw)[:60]


def _add_file_handler(log: logging.Logger, svc: str) -> None:
    """Daily-rotating JSON file handler (LOG-to-disk, 2026-05-25).
    Dir = EDP_LOG_DIR (default '.logs'); rotate at midnight; keep
    EDP_LOG_RETENTION_DAYS (default 14). Best-effort: a logging failure
    must never crash the service, so swallow setup errors."""
    try:
        log_dir = Path(os.environ.get("EDP_LOG_DIR", ".logs"))
        log_dir.mkdir(parents=True, exist_ok=True)
        disc = _log_discriminator()
        name = f"{svc}-{disc}.log" if disc else f"{svc}.log"
        try:
            keep = int(os.environ.get("EDP_LOG_RETENTION_DAYS", "14"))
        except ValueError:
            keep = 14
        fh = _WindowsSafeRotatingHandler(
            log_dir / name, when="midnight", backupCount=keep,
            encoding="utf-8", delay=True,
        )
        fh.setFormatter(_JsonLineFormatter())
        log.addHandler(fh)
    except Exception:  # never let logging setup break the service
        pass


def _level_from_env() -> int:
    """EDP_LOG_LEVEL (debug|info|warning|error), default INFO.

    2026-06-10 log-volume fix: the level was hard-coded DEBUG, so every
    `.debug()` call hit stderr AND the rotating file. High-frequency
    read paths (broker inbox polls every ~2s per rx subscription) are now
    logged at debug — with INFO as the default they cost nothing; set
    EDP_LOG_LEVEL=debug to see them while troubleshooting."""
    name = os.environ.get("EDP_LOG_LEVEL", "info").strip().lower()
    return {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
    }.get(name, logging.INFO)


class _Logger:
    """Thin adapter exposing ``.info/.warning/.error(kind, detail, **fields)``."""

    def __init__(self, svc: str) -> None:
        self._svc = svc
        self._log = logging.getLogger(f"{_LOGGER_NAMESPACE}.{svc}")
        if not self._log.handlers:
            handler = _DynamicStderrHandler()
            handler.setFormatter(_JsonLineFormatter())
            self._log.addHandler(handler)
            _add_file_handler(self._log, svc)  # + persist to disk, rolling
            self._log.setLevel(_level_from_env())
            self._log.propagate = False

    def _emit(
        self, level: int, kind: str, detail: str, **fields: Any
    ) -> None:
        self._log.log(
            level,
            detail,
            extra={"svc": self._svc, "kind": kind, "edp_fields": fields},
        )

    def debug(self, kind: str, detail: str, **fields: Any) -> None:
        self._emit(logging.DEBUG, kind, detail, **fields)

    def info(self, kind: str, detail: str, **fields: Any) -> None:
        self._emit(logging.INFO, kind, detail, **fields)

    def warning(self, kind: str, detail: str, **fields: Any) -> None:
        self._emit(logging.WARNING, kind, detail, **fields)

    def error(self, kind: str, detail: str, **fields: Any) -> None:
        self._emit(logging.ERROR, kind, detail, **fields)


def get_logger(svc: str) -> LoggerLike:
    """Return a logger that emits one LogRecordModel-shaped JSON line per call.

    Usage: ``get_logger("edp-pool").info("spawned", "worker for a1",
    plan_id="p1")``.
    """
    return _Logger(svc)
