"""Shared pytest configuration.

Cutover default for the test suite (S12, design §4.1). Production ships EDP8_UI=folio (SPA at
/ui, legacy renderer at /ui-legacy), but the existing python UI tests were written against the
pre-cutover mapping — the legacy renderer at /ui. So the suite defaults to EDP8_UI=legacy here,
keeping every legacy-renderer test a byte-identical golden master. The folio mapping and the
switch itself are proven explicitly in tests/test_cutover.py (which overrides EDP8_UI per case)
and by the Playwright e2e run (globalSetup spawns the board with EDP8_UI=folio).

Honour an EDP8_UI already set in the environment (a CI job can force folio) rather than clobbering
it, and never override a test that sets EDP8_UI itself (monkeypatch in the test body wins).
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _default_legacy_ui(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDP8_UI", os.environ.get("EDP8_UI") or "legacy")
