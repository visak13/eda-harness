"""t-67d19c5807 (qa m-e633397a42): the e2e spec board's agent home.

The spec board runs on a private EDP_HOME (web/e2e/hermeticEnv.ts, 8d0ec6f) so it is not in dev mode: its agent
home is `<home>/agent-home` and there is no source checkout to fall back on. Unseeded, every Standard card is
missing and a Standard copy fails Validate with card_missing, so Publish stops. `seedAgentHome` (hermeticEnv.ts)
copies the repo's `.claude/commands/*.md` there; this guard reproduces that layout and shows a Standard copy
validates with 0 errors — and that the empty home is what broke it.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest

from edp8 import materialise
from edp8 import workflow as wf
from edp8.board import Board
from edp8.schemas import Role
from edp8.store import Store

REPO = Path(__file__).resolve().parents[1]  # v8/


class _Pool:
    def spawn(self, *_a, **_k):
        return {"ok": True}


@pytest.fixture
def spec_board_env(tmp_path, monkeypatch):
    """The env a spec board gets: a private EDP_HOME that is not a checkout, no agent-home or dev override."""
    for k in ("EDP_AGENT_HOME", "EDP_DEV", "EDP8_HOME"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("EDP_HOME", str(tmp_path))

    # no packaged agent home and no dev-mode checkout: exactly the spec board's resolution on a source tree
    def _none():
        raise FileNotFoundError("spec board: no packaged agent home, not dev mode")
    monkeypatch.setattr(materialise, "source_root", _none)
    return tmp_path


def _seed(home: Path) -> Path:
    """Mirror of web/e2e/hermeticEnv.ts seedAgentHome."""
    dst = home / "agent-home" / ".claude" / "commands"
    dst.mkdir(parents=True, exist_ok=True)
    for f in (REPO / ".claude" / "commands").glob("*.md"):
        shutil.copyfile(f, dst / f.name)
    shutil.copyfile(REPO / "models.json", home / "agent-home" / "models.json")
    return home / "agent-home"


def _standard_copy_errors() -> list[dict]:
    b = Board(Store(":memory:"), pool=_Pool(), free_mb=lambda: 10_000)
    b.participant_create("human", Role.owner, "owner", id_="owner")
    d = wf.dump(b.workflows.duplicate("standard@1", new_id="team", by="owner"))
    return [p for p in wf.validate(d) if p["severity"] == "error"]


def test_seeded_spec_board_validates_a_standard_copy_clean(spec_board_env):
    from edp8 import settings
    assert settings.agent_home() == _seed(spec_board_env)
    assert _standard_copy_errors() == []
    # the role-model picker reads the seeded catalog (unseeded, the shipped-catalog lookup has no source at all)
    from edp8 import model_catalog
    assert model_catalog.shipped_path() == spec_board_env / "agent-home" / "models.json"
    assert model_catalog.read().get("models")


def test_unseeded_spec_board_is_what_broke_publish(spec_board_env):
    codes = [p["code"] for p in _standard_copy_errors()]
    assert codes and set(codes) == {"card_missing"}
