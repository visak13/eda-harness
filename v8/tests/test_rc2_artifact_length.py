"""RC2 (t-e338298d88, architect m-bf8306d6f7): an artifact's bytes go out exactly as stored, with their
Content-Length. S22's GZip compressed GET /v1/artifacts/{id}/content (FileResponse streams in chunks, so the
1 KB minimum never applied): the length header dropped to chunked transfer, and the VS Code chat's size probe
showed a 34 B notes file as "0 B"."""
from __future__ import annotations

from test_uploads import OWN, _upload, board_app  # noqa: F401 (fixture)

NOTES = b"# notes\n\nsome text for the reader\n"
GZ = {**OWN, "Accept-Encoding": "gzip, deflate, br"}


def test_text_artifact_content_keeps_its_length_and_is_not_gzipped(board_app):  # noqa: F811
    c = board_app["client"]
    aid = _upload(c, NOTES, "notes.md", "text/markdown").json()["value"]["id"]
    r = c.get(f"/v1/artifacts/{aid}/content", headers=GZ)
    assert r.status_code == 200 and r.content == NOTES
    assert "content-encoding" not in r.headers
    assert r.headers["content-length"] == str(len(NOTES))


def test_other_json_stays_compressed(board_app):  # noqa: F811
    c = board_app["client"]
    for i in range(30):
        c.post("/v1/tickets", headers=OWN, json={"kind": "epic", "title": f"epic {i} " + "x" * 80})
    r = c.get("/v1/tickets", headers=GZ)
    assert r.status_code == 200 and r.headers.get("content-encoding") == "gzip"
