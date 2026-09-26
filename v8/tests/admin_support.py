"""Shared set-up for the S5 admin API tests: an in-process board in token mode with an admin human (the
init human `owner`), a non-admin human (`bob`) and an agent seat (`eng.x`)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("EDP8_EMBEDDER", "none")

from fastapi.testclient import TestClient

from edp8.board import Board
from edp8.service import create_app
from edp8.store import Store

OWNER_TOKEN = "owner-secret"
BOB_TOKEN = "bob-secret"
ENG_TOKEN = "eng-secret"
MACHINE_ADMIN = "machine-admin"

ADMIN_H = {"X-Participant": "owner", "X-Token": OWNER_TOKEN}
BOB_H = {"X-Participant": "bob", "X-Token": BOB_TOKEN}
AGENT_H = {"X-Participant": "eng.x", "X-Token": ENG_TOKEN}


@dataclass
class AdminEnv:
    client: TestClient
    board: Board
    tokens: Path
    app: object

    def tokens_data(self) -> dict:
        return json.loads(self.tokens.read_text(encoding="utf-8"))


def make_env(tmp_path: Path, monkeypatch, db: str = ":memory:") -> AdminEnv:
    tokens = tmp_path / "tokens.json"
    tokens.write_text(json.dumps({"owner": OWNER_TOKEN, "bob": BOB_TOKEN, "agents": {"eng.x": ENG_TOKEN}}),
                      encoding="utf-8")
    monkeypatch.setenv("EDP8_TOKENS", str(tokens))
    monkeypatch.setenv("EDP8_OWNER", "owner")
    board = Board(Store(db))
    app = create_app(board, admin_token=MACHINE_ADMIN)
    c = TestClient(app)
    for pid, role, typ in [("owner", "owner", "human"), ("bob", "owner", "human"), ("eng.x", "engineer", "agent")]:
        r = c.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                   headers={"X-Admin": MACHINE_ADMIN})
        assert r.status_code == 200, r.text
    return AdminEnv(client=c, board=board, tokens=tokens, app=app)
