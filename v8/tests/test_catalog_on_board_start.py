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
