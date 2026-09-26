"""Shared pytest configuration for edp-contracts."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def no_seat_log_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    """A seat shell carries EDP_HANDLE, which logging turns into a per-process file suffix; the logging
    tests that expect the plain `<svc>.log` name must not inherit it. Tests that want a suffix set it."""
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    monkeypatch.delenv("EDP_LOG_SUFFIX", raising=False)
