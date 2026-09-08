"""Shared pytest configuration.

Cutover default for the test suite (S12, design §4.1). Production ships EDP8_UI=folio (SPA at
/ui, legacy renderer at /ui-legacy), but the existing python UI tests were written against the
pre-cutover mapping — the legacy renderer at /ui. The `ui_prefix` fixture below carries that:
by default it puts the legacy renderer at /ui under EDP8_UI=legacy, keeping every legacy-renderer
test a byte-identical golden master. Set EDP8_TEST_UI_PREFIX=/ui-legacy to run those SAME
characterisation tests against folio's mount (EDP8_UI=folio), proving the retained renderer is
identical under the cutover — this is the "parametrised by a shared ui_prefix fixture" contract of
c-a8c1be7137 (second-opinion 2026-09-08: the legacy suite was not actually prefix-parameterised —
only test_cutover read the prefix; test_ui_live / test_views / test_human_plane / test_signoff_ui /
test_collab_events hardcoded /ui and would hit the SPA under folio). The folio/legacy mapping and
the switch itself are also proven explicitly in tests/test_cutover.py.

/ui/poll is FIXED at /ui/poll under both modes — it never takes the prefix.
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def ui_prefix(monkeypatch: pytest.MonkeyPatch) -> str:
    """The mount prefix the legacy renderer answers on, and the EDP8_UI mode that puts it there.

    Default: /ui under EDP8_UI=legacy (the golden-master mapping). EDP8_TEST_UI_PREFIX=/ui-legacy
    runs the legacy characterisation against folio's mount (EDP8_UI=folio). An EDP8_UI already set
    in the environment (a CI job can force folio) is honoured and derives the default prefix; a test
    that monkeypatches EDP8_UI in its own body still wins for an app it builds after setup.

    Autouse so it also sets EDP8_UI for tests that do not name it; request `ui_prefix` as a fixture
    to build legacy-renderer URLs (f"{ui_prefix}/me", …) instead of a hardcoded /ui.
    """
    env_ui = os.environ.get("EDP8_UI")
    prefix = os.environ.get("EDP8_TEST_UI_PREFIX")
    if prefix is None:
        prefix = "/ui-legacy" if env_ui == "folio" else "/ui"
    mode = env_ui or ("folio" if prefix == "/ui-legacy" else "legacy")
    monkeypatch.setenv("EDP8_UI", mode)
    return prefix
