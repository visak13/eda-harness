"""t-96df382440: a board started on a home that never ran `init` still serves a model catalog."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from edp8 import model_catalog, seat_choice, settings
from edp8.service import create_app

OWNER = {"X-Participant": "owner"}
OWNER_ROW = {"type": "human", "role": "owner", "handle": "owner", "id": "owner"}


def _models(client) -> dict:
    r = client.post("/v1/participants", json=OWNER_ROW, headers={"X-Admin": "dev"})
    assert r.status_code == 200, r.text
    r = client.get("/v1/models", headers=OWNER)
    assert r.status_code == 200, r.text
    return r.json()["value"]


def test_create_app_on_a_fresh_home_materialises_the_catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP8_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("EDP8_EMBEDDER", "none")
    dest = settings.data_dir() / "models.json"
    assert not dest.exists()
    value = _models(TestClient(create_app()))
    assert value["models"] and value["roles"]
    assert dest.is_file()
    assert json.loads(dest.read_text(encoding="utf-8"))["models"] == model_catalog.read()["models"]
    assert model_catalog.ensure() == []  # a second start merges nothing new


def test_the_shipped_catalog_is_served_when_no_copy_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP8_HOME", str(tmp_path / "home"))
    assert not (settings.data_dir() / "models.json").exists()
    reg = seat_choice._registry(seat_choice.agent_home())
    assert reg["models"] and seat_choice.catalog(seat_choice.agent_home())


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_subprocess_board_on_a_fresh_home_serves_models(tmp_path):
    port = _free_port()
    home = tmp_path / "home"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("EDP", "HERONRY", "PYTHONPATH"))}
    env.update(EDP_HOME=str(home), EDP8_PORT=str(port), EDP8_EMBEDDER="none", EDP_DEV="1",
               EDP8_TOKENS=str(tmp_path / "absent-tokens.json"), PYTHONIOENCODING="utf-8")
    log = open(tmp_path / "board.log", "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-m", "edp8.service"], env=env, stdout=log, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL)
    try:
        deadline = time.time() + 120
        while True:
            assert proc.poll() is None, (tmp_path / "board.log").read_text(encoding="utf-8")
            try:
                httpx.post(f"http://127.0.0.1:{port}/v1/participants", json=OWNER_ROW, headers={"X-Admin": "dev"},
                           timeout=5).raise_for_status()
                r = httpx.get(f"http://127.0.0.1:{port}/v1/models", headers=OWNER, timeout=5)
                break
            except httpx.TransportError:
                assert time.time() < deadline, "board never listened"
                time.sleep(0.5)
        assert r.status_code == 200, r.text
        assert r.json()["value"]["models"]
        copies = list(Path(home).rglob("models.json"))
        assert any(p.parent.name == ".data" for p in copies), copies
    finally:
        proc.kill()
        proc.wait(timeout=30)
        log.close()


# ---------------------------------------------------------------- RC2 item 1 (t-e338298d88): an upgraded install

_SHIPPED = Path(__file__).resolve().parents[1] / "models.json"


def _version(root: Path, card: str, catalog: dict) -> Path:
    """A packaged agent home: one role card, one guide, the catalog."""
    (root / ".claude" / "commands").mkdir(parents=True)
    (root / "guides").mkdir()
    (root / ".claude" / "commands" / "engineer.md").write_text(f"engineer {card}", encoding="utf-8")
    (root / ".claude" / "commands" / "qa.md").write_text(f"qa {card}", encoding="utf-8")
    (root / "guides" / f"{card}.md").write_text(card, encoding="utf-8")
    (root / "models.json").write_text(json.dumps(catalog, indent=1), encoding="utf-8")
    return root


def test_board_start_brings_an_upgraded_install_to_the_shipped_version(tmp_path, monkeypatch):
    """0.9.1 → 0.10: the MSI never re-runs `init`, so the agent home kept 0.9.1's cards, skills and models.json,
    and the catalog merge read that stale copy: the shipped `high` caps never reached the live catalog."""
    from edp8 import materialise
    monkeypatch.setenv("EDP8_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("EDP8_EMBEDDER", "none")
    new = json.loads(_SHIPPED.read_text(encoding="utf-8"))
    old = json.loads(json.dumps(new))
    for mid in ("claude-fable-5-1", "claude-opus-5-5"):
        old["models"][mid]["effort_cap"] = "medium"
    v1 = _version(tmp_path / "v1", "v1", old)
    v2 = _version(tmp_path / "v2", "v2", new)
    home = settings.agent_home()

    # the 0.9.1 install: init materialised v1; the owner then edited one card and hand-set one catalog row
    monkeypatch.setattr(materialise, "packaged_root", lambda: v1, raising=False)
    monkeypatch.setattr(materialise, "source_root", lambda: v1)
    materialise.materialise(home, v1)
    model_catalog.materialise()
    (home / ".claude" / "commands" / "qa.md").write_text("qa as the owner wrote it", encoding="utf-8")
    data = json.loads(model_catalog.path().read_text(encoding="utf-8"))
    assert data["models"]["claude-opus-5-5"]["effort_cap"] == "medium"
    data["models"]["claude-fable-5-1"]["effort_cap"] = "low"
    model_catalog.path().write_text(json.dumps(data, indent=1), encoding="utf-8")

    # the MSI swaps the package; the next board start is all that runs
    monkeypatch.setattr(materialise, "packaged_root", lambda: v2, raising=False)
    monkeypatch.setattr(materialise, "source_root", lambda: v2)
    create_app()

    cards = home / ".claude" / "commands"
    assert (cards / "engineer.md").read_text(encoding="utf-8") == "engineer v2"   # unedited: follows the upgrade
    assert (cards / "qa.md").read_text(encoding="utf-8") == "qa as the owner wrote it"  # edited: kept
    assert (cards / "qa.md.new").read_text(encoding="utf-8") == "qa v2"           # the new one beside it
    assert (home / "guides" / "v2.md").is_file()
    live = json.loads(model_catalog.path().read_text(encoding="utf-8"))["models"]
    assert live["claude-opus-5-5"]["effort_cap"] == "high"   # came only from the old template: updated
    assert live["claude-fable-5-1"]["effort_cap"] == "low"   # hand-set by the owner: kept
    assert seat_choice._effort_cap("claude-opus-5-5", home) == "high"


def test_the_package_catalog_wins_over_a_stale_agent_home_copy(tmp_path, monkeypatch):
    from edp8 import materialise
    monkeypatch.setenv("EDP8_HOME", str(tmp_path / "home"))
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "models.json").write_text("{}", encoding="utf-8")
    stale = settings.agent_home() / "models.json"
    stale.parent.mkdir(parents=True)
    stale.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(materialise, "packaged_root", lambda: pkg, raising=False)
    assert model_catalog.shipped_path() == pkg / "models.json"
    monkeypatch.setattr(materialise, "packaged_root", lambda: None, raising=False)
    assert model_catalog.shipped_path() == stale  # a source run (no package) still reads the home's copy


def test_refresh_leaves_a_source_checkout_home_alone(tmp_path, monkeypatch):
    from edp8 import materialise
    monkeypatch.setattr(materialise, "source_root", lambda: tmp_path)
    assert materialise.refresh(tmp_path) is None


def test_the_shipped_claude_rows_allow_high_effort():
    """c-300f4365a2: New epic offers high effort on the installed build."""
    rows = json.loads(_SHIPPED.read_text(encoding="utf-8"))["models"]
    assert {m: r["effort_cap"] for m, r in rows.items() if r["harness"] == "claude"} == {
        "claude-fable-5-1": "high", "claude-opus-5-5": "high"}
