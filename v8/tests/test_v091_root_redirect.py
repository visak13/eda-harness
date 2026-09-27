"""v0.9.1 (s-dbe96f11cd): the board's bare origin opens the UI instead of a 404 (a tailnet URL opened
on a phone landed on `/`)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from edp8.board import Board
from edp8.service import create_app
from edp8.store import Store


def test_root_redirects_to_the_ui():
    client = TestClient(create_app(Board(Store(":memory:")), admin_token="t"))
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/ui/"
