"""TESTPLAN §5 — logging.py."""

import json
import logging

from edp_contracts import get_logger
from edp_contracts.logging import LoggerLike


def _capture(caplog, level=logging.DEBUG):
    caplog.set_level(level, logger="edp.test-svc")


def _emit_and_read(capsys, fn):
    fn()
    err = capsys.readouterr().err.strip().splitlines()
    return [json.loads(line) for line in err if line.startswith("{")]


def test_log_1_mandatory_fields(capsys):
    """LOG-1 MUST."""
    rows = _emit_and_read(
        capsys, lambda: get_logger("test-svc").info("spawned", "detail here")
    )
    assert rows, "no JSON line emitted"
    r = rows[-1]
    for k in ("ts", "svc", "level", "kind", "detail"):
        assert k in r, f"missing mandatory field {k}"
    assert r["svc"] == "test-svc"
    assert r["kind"] == "spawned"
    assert r["detail"] == "detail here"


def test_log_2_recommended_fields_ride(capsys):
    """LOG-2 MUST."""
    rows = _emit_and_read(
        capsys,
        lambda: get_logger("test-svc").info("k", "d", recipe_id="r1", plan_id="p1"),
    )
    r = rows[-1]
    assert r["recipe_id"] == "r1" and r["plan_id"] == "p1"


def test_log_3_level_fidelity(capsys):
    """LOG-3 MUST."""
    rows = _emit_and_read(
        capsys, lambda: get_logger("test-svc").error("k", "boom")
    )
    assert rows[-1]["level"] == "error"


def test_logger_satisfies_protocol():
    """Refactor S3b — get_logger returns something matching LoggerLike."""
    assert isinstance(get_logger("x"), LoggerLike)


def test_log_to_disk_daily_rolling(tmp_path, monkeypatch):
    """LOG-to-disk (2026-05-25): get_logger persists a JSON line to a
    daily-rolling file under EDP_LOG_DIR, in addition to stderr."""
    import uuid
    from logging.handlers import TimedRotatingFileHandler
    monkeypatch.setenv("EDP_LOG_DIR", str(tmp_path))
    svc = f"disk-{uuid.uuid4().hex[:8]}"          # fresh name → fresh handlers
    log = get_logger(svc)
    log.info("started", "wrote to disk", plan_id="p1")
    f = tmp_path / f"{svc}.log"
    assert f.exists(), "no log file on disk"
    rows = [json.loads(x) for x in
            f.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert rows[-1]["kind"] == "started"
    assert rows[-1]["plan_id"] == "p1"
    # it's a daily-rotating handler (rolls at midnight)
    fh = [h for h in logging.getLogger(f"edp.{svc}").handlers
          if isinstance(h, TimedRotatingFileHandler)]
    assert fh and fh[0].when.upper().startswith("MIDNIGHT")


def test_log_per_process_file_via_discriminator(tmp_path, monkeypatch):
    """Concurrent shells get SEPARATE files (no cross-process rotation
    race) — keyed by EDP_LOG_SUFFIX / EDP_HANDLE."""
    import uuid
    monkeypatch.setenv("EDP_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("EDP_LOG_SUFFIX", "plan-x_a1")
    svc = f"disc-{uuid.uuid4().hex[:8]}"
    get_logger(svc).info("k", "d")
    assert (tmp_path / f"{svc}-plan-x_a1.log").exists()
    assert not (tmp_path / f"{svc}.log").exists()
