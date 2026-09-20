"""Upload / content / staging / sweep tests (design §18.1, S21).

Cover the sniffer (magic wins over the filename; SVG is a file, never an image), the streaming
cap and type allowlist, staged invisibility, atomic finalise via a message, the content
endpoint's headers, and the 24 h sweep.
"""

from __future__ import annotations

import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import io

import pytest
from fastapi.testclient import TestClient

from edp8 import broker_adapter, uploads
from edp8.board import Board
from edp8.schemas import now
from edp8.service import create_app
from edp8.store import Store

ADMIN = {"X-Admin": "t"}
OWN = {"X-Participant": "owner"}

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n"
SVG = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"
EXE = b"MZ\x90\x00\x03\x00\x00\x00"  # DOS/PE header — binary, disallowed


@pytest.fixture
def board_app(monkeypatch, tmp_path):
    monkeypatch.setattr(broker_adapter, "publish", lambda *a, **k: True)
    monkeypatch.setenv("EDP8_DATA", str(tmp_path))
    monkeypatch.setenv("EDP8_UPLOAD_SWEEP", "0")  # no background thread in tests
    board = Board(Store(":memory:"))
    client = TestClient(create_app(board, admin_token="t"))
    r = client.post("/v1/participants", json={"type": "human", "role": "owner", "handle": "owner",
                                              "id": "owner"}, headers=ADMIN).json()
    assert r["ok"], r
    epic = client.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "E"},
                       headers=OWN).json()["value"]["id"]
    return {"board": board, "client": client, "epic": epic}


def _upload(client, data: bytes, filename: str, ctype: str = "application/octet-stream"):
    return client.post("/v1/artifacts/upload", files={"file": (filename, io.BytesIO(data), ctype)},
                       data={"note": "n"}, headers=OWN)


# --------------------------------------------------------------------------- sniffer (pure)


def test_sniffer_magic_beats_filename():
    assert uploads.sniff_upload(PNG, "evil.txt") == "image/png"   # magic wins
    assert uploads.sniff_upload(b"just text", "x.png") == "text/plain"  # ext lies, bytes don't
    assert uploads.sniff_upload(PDF, "image.png") == "application/pdf"  # polyglot: real type
    assert uploads.sniff_upload(SVG, "a.svg") == "image/svg+xml"
    assert uploads.sniff_upload(EXE, "setup.exe") is None          # disallowed
    assert uploads.sniff_upload(b'{"a":1}', "d.json") == "application/json"


def test_svg_is_never_an_inline_image():
    assert not uploads.is_inline_image("image/svg+xml")
    assert uploads.is_inline_image("image/png")


# --------------------------------------------------------------------------- upload endpoint


def test_upload_png_is_staged_image(board_app):
    r = _upload(board_app["client"], PNG, "a.png", "image/png").json()
    assert r["ok"], r
    assert r["value"]["form"] == "image" and r["value"]["content_type"] == "image/png"
    assert r["value"]["staged"] is True
    assert r["value"]["uri"] == f"/v1/artifacts/{r['value']['id']}/content"


def test_upload_svg_stored_as_file(board_app):
    r = _upload(board_app["client"], SVG, "x.svg", "image/svg+xml").json()
    assert r["ok"] and r["value"]["form"] == "file" and r["value"]["content_type"] == "image/svg+xml"


def test_upload_rejects_disallowed_and_oversize(board_app, monkeypatch):
    bad = _upload(board_app["client"], EXE, "setup.exe")
    assert bad.status_code == 415 and bad.json()["error"]["code"] == "unsupported_type"
    monkeypatch.setattr(uploads, "MAX_UPLOAD_BYTES", 16)
    big = _upload(board_app["client"], PNG + b"\x00" * 64, "big.png")
    assert big.status_code == 413 and big.json()["error"]["code"] == "too_large"


# --------------------------------------------------------------------------- staged invisibility + finalise


def test_staged_artifact_is_invisible_until_finalised(board_app):
    c, epic = board_app["client"], board_app["epic"]
    aid = _upload(c, PNG, "a.png").json()["value"]["id"]
    lib = c.get("/v1/library", headers=OWN).json()["value"]
    assert all(art["id"] != aid for art in lib["artifacts"])  # staged: absent
    # finalise via a message → visible, linked produced to the ticket
    m = c.post("/v1/messages", json={"ticket_id": epic, "kind": "note", "text": "see art",
                                     "artifacts": [aid]}, headers=OWN).json()
    assert m["ok"], m
    lib2 = c.get("/v1/library", headers=OWN).json()["value"]
    assert any(art["id"] == aid and art["staged"] is False for art in lib2["artifacts"])
    links = c.get("/v1/links", params={"to_id": aid}, headers=OWN).json()["value"]
    assert any(lk["from_id"] == epic and lk["relation"] == "produced" for lk in links)


def test_finalise_is_atomic_bad_id_posts_nothing(board_app):
    c, epic = board_app["client"], board_app["epic"]
    aid = _upload(c, PNG, "a.png").json()["value"]["id"]
    before = len(c.get("/v1/messages", params={"ticket_id": epic}, headers=OWN).json()["value"])
    r = c.post("/v1/messages", json={"ticket_id": epic, "kind": "note", "text": "x",
                                     "artifacts": [aid, "art-does-not-exist"]}, headers=OWN)
    assert not r.json()["ok"]  # the bad id fails the whole finalise
    after = len(c.get("/v1/messages", params={"ticket_id": epic}, headers=OWN).json()["value"])
    assert after == before  # message never posted
    # the good artifact stayed staged (nothing became visible)
    assert c.get(f"/v1/artifacts/{aid}", headers=OWN).json()["value"]["staged"] is True


# --------------------------------------------------------------------------- direct ticket attach (finding 11)


def test_drop_finalize_attaches_directly_to_ticket(board_app):
    """Finding 11: a file dropped on the ticket's Files card is finalised straight onto the ticket
    (no message) — unstaged, `produced`-linked, and it shows in Files & evidence (contextual) so it
    survives reload instead of lingering staged=True until the 24 h sweep."""
    c, epic = board_app["client"], board_app["epic"]
    aid = _upload(c, PNG, "a.png").json()["value"]["id"]
    assert c.get(f"/v1/artifacts/{aid}", headers=OWN).json()["value"]["staged"] is True
    r = c.post("/v1/artifacts/finalize", json={"artifact_ids": [aid], "ticket_id": epic},
               headers=OWN).json()
    assert r["ok"], r
    assert r["value"][0]["id"] == aid and r["value"][0]["staged"] is False
    # unstaged on disk
    assert c.get(f"/v1/artifacts/{aid}", headers=OWN).json()["value"]["staged"] is False
    # produced link to the ticket
    links = c.get("/v1/links", params={"to_id": aid}, headers=OWN).json()["value"]
    assert any(lk["from_id"] == epic and lk["relation"] == "produced" for lk in links)
    # appears in the ticket's Files & evidence viewer (contextual) — survives reload
    ctx = c.get(f"/v1/tickets/{epic}/contextual", headers=OWN).json()["value"]
    assert any(rec["record"]["id"] == aid and rec["type"] == "artifact" for rec in ctx["records"])


def test_drop_finalize_refuses_another_actors_upload(board_app):
    """The same uploader-scope check as the message finalise path: only the uploader can attach."""
    c, board, epic = board_app["client"], board_app["board"], board_app["epic"]
    c.post("/v1/participants", json={"type": "human", "role": "reviewer", "handle": "ravi", "id": "ravi"},
           headers=ADMIN)
    aid = _upload(c, PNG, "a.png").json()["value"]["id"]  # uploaded by owner
    r = c.post("/v1/artifacts/finalize", json={"artifact_ids": [aid], "ticket_id": epic},
               headers={"X-Participant": "ravi"})
    assert not r.json()["ok"] and r.json()["error"]["code"] == "scope"
    assert board._get("artifact", aid, "artifact").staged is True


# --------------------------------------------------------------------------- content endpoint


def test_finalise_refuses_another_actors_staged_upload(board_app):
    c, board, epic = board_app["client"], board_app["board"], board_app["epic"]
    c.post("/v1/participants", json={"type": "human", "role": "reviewer", "handle": "ravi", "id": "ravi"},
           headers=ADMIN)
    aid = _upload(c, PNG, "a.png").json()["value"]["id"]  # uploaded by owner
    # ravi tries to attach owner's staged upload onto a message → refused, artifact stays staged
    r = c.post("/v1/messages", json={"ticket_id": epic, "kind": "note", "text": "mine now",
                                     "artifacts": [aid]}, headers={"X-Participant": "ravi"})
    assert not r.json()["ok"] and r.json()["error"]["code"] == "scope"
    assert board._get("artifact", aid, "artifact").staged is True


def test_content_headers_png_inline_svg_attachment(board_app):
    c = board_app["client"]
    png_id = _upload(c, PNG, "a.png").json()["value"]["id"]
    svg_id = _upload(c, SVG, "x.svg").json()["value"]["id"]
    rp = c.get(f"/v1/artifacts/{png_id}/content", headers=OWN)
    assert rp.status_code == 200 and rp.headers["content-type"].startswith("image/png")
    assert rp.headers["x-content-type-options"] == "nosniff"
    assert rp.headers["content-disposition"].startswith("inline")
    rs = c.get(f"/v1/artifacts/{svg_id}/content", headers=OWN)
    assert rs.headers["content-type"].startswith("image/svg+xml")
    assert rs.headers["content-disposition"].startswith("attachment")  # never rendered inline
    assert rs.headers["x-content-type-options"] == "nosniff"


def test_content_disposition_helper_rfc6266():
    """Finding 14 (pure): the header carries an ASCII fallback AND filename*=UTF-8'' — quotes and
    backslashes escaped in the fallback, non-ASCII bytes never leak into the latin-1 header."""
    v = uploads.content_disposition("attachment", 'проверка "1".png')
    disp, _, star = v.partition("; filename*=")
    # non-Latin chars → underscores, and the embedded quotes are backslash-escaped in the fallback
    assert disp == 'attachment; filename="________ \\"1\\".png"'  # 8 Cyrillic letters → 8 "_"
    assert "\\\"1\\\"" in disp
    assert star == "UTF-8''%D0%BF%D1%80%D0%BE%D0%B2%D0%B5%D1%80%D0%BA%D0%B0%20%221%22.png"
    v.encode("latin-1")  # the whole value is header-safe (would have raised before the fix)
    assert uploads.content_disposition("inline", "").startswith('inline; filename="download"')


def test_download_non_latin_filename_is_200_not_500(board_app):
    """Finding 14: a download whose stored filename is non-Latin (or has quotes) returns 200 with a
    valid RFC 6266 header, not a Starlette UnicodeEncodeError 500."""
    c = board_app["client"]
    aid = _upload(c, PNG, 'отчёт "final".png', "image/png").json()["value"]["id"]
    r = c.get(f"/v1/artifacts/{aid}/content", headers=OWN)
    assert r.status_code == 200
    cd = r.headers["content-disposition"]
    assert cd.startswith("inline; filename=")
    assert "filename*=UTF-8''" in cd and "%D0%BE%D1%82" in cd  # the UTF-8 name, percent-encoded


# --------------------------------------------------------------------------- sweep


def test_sweep_deletes_staged_older_than_24h(board_app):
    from datetime import timedelta
    board, c = board_app["board"], board_app["client"]
    aid = _upload(c, PNG, "a.png").json()["value"]["id"]
    art = board._get("artifact", aid, "artifact")
    art.created_at = now() - timedelta(hours=25)  # pretend it was uploaded yesterday
    board.store.put("artifact", art)
    path = uploads.uploads_dir() / f"{aid}.png"
    assert path.exists()
    removed = board.sweep_staged_artifacts()
    assert aid in removed
    assert board.store.get("artifact", aid) is None and not path.exists()


def test_sweep_spares_finalised_and_fresh(board_app):
    board, c, epic = board_app["board"], board_app["client"], board_app["epic"]
    fresh = _upload(c, PNG, "fresh.png").json()["value"]["id"]
    done = _upload(c, PNG, "done.png").json()["value"]["id"]
    c.post("/v1/messages", json={"ticket_id": epic, "kind": "note", "text": "x", "artifacts": [done]},
           headers=OWN)
    removed = board.sweep_staged_artifacts()
    assert fresh not in removed and done not in removed  # fresh staged + finalised both spared
