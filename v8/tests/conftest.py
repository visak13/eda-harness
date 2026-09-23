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


@pytest.fixture(autouse=True)
def isolated_tokens(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never read the HOST's tokens.json (EDP8_HOME defaults to the cwd, where the fleet board
    keeps its minted agent secrets). Human #34 made token mode refuse an unminted human, so a suite
    run from v8/ would otherwise 401 every header-only `owner` call. Tests that need a tokens file
    set EDP8_TOKENS themselves (test_human_plane, test_public_mode, test_s20_pool_control …)."""
    if "EDP8_TOKENS" not in os.environ:
        monkeypatch.setenv("EDP8_TOKENS", str(tmp_path_factory.mktemp("tokens") / "absent-tokens.json"))


@pytest.fixture(autouse=True)
def no_pool_watch(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test app starts the pool watcher (incident m-c31573e1a2): a seat shell carries EDP_POOL_URL, so
    create_app() started the real `_pool_watch` daemon thread in tests; it outlived its test, drained a
    queued pairing and minted into the fleet's tokens.json. A test that wants the watcher sets it itself."""
    monkeypatch.delenv("EDP_POOL_URL", raising=False)
    monkeypatch.delenv("EDP8_POOL_WATCH", raising=False)
