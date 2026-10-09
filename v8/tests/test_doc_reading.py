"""note-e6ddb85977 §1-§4: the /doc-read skill, the architect section line and ticket hint, already-read doc reads,
and the shared argument-alias table."""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from edp8.board import Board  # noqa: E402
from edp8.bundles import ALL_TOOLS, ARG_ALIASES, invoke, set_client  # noqa: E402
from edp8.client import BoardClient  # noqa: E402
from edp8.codex_seat import seat as seat_mod  # noqa: E402
from edp8.service import create_app  # noqa: E402
from edp8.store import Store  # noqa: E402

V8 = Path(__file__).resolve().parents[1]
ADMIN = {"X-Admin": "t"}
ARCH = {"X-Participant": "arch"}
OWNER = {"X-Participant": "owner"}
BIG = ("# Big doc\n\n## Purpose\nWhy.\n\n## Key points\n- rule\n\n## Outline\n- x\n\n## Topics\n"
       + "".join(f"### Topic {i}\n" + ("filler line %d.\n" % i) * 60 + "\n" for i in range(12)))


@pytest.fixture
def http():
    c = TestClient(create_app(Board(Store(":memory:")), admin_token="t"))
    for pid, role, typ in [("owner", "owner", "human"), ("arch", "architect", "agent"), ("eng", "engineer", "agent"),
                           ("eng2", "engineer", "agent")]:
        assert c.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                      headers=ADMIN).json()["ok"]
    return c


def _tool(http, who, name, **args):
    set_client(BoardClient(participant=who, client=http))
    return invoke(ALL_TOOLS[name], args, seat=who)


def _doc(http, body=BIG, doc_type="note"):
    r = http.post("/v1/docs", json={"doc_type": doc_type, "title": "Big doc", "body_md": body, "scope": "global"},
                  headers=ARCH).json()
    assert r["ok"], r
    return r["value"]["id"]


# ----------------------------------------------------------------------------- 1 the skill and the cards

def test_skill_file_is_the_note_text_and_every_doc_write_card_lists_it():
    text = (V8 / ".claude" / "skills" / "doc-read" / "SKILL.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert text.startswith("---\nname: doc-read\ndescription: Trigger before you read a board doc (doc_read), "
                           "especially a design or strategy linked to your ticket.\n---\n")
    assert "<!-- roles: architect, engineer, qa, sme, adversary, doctor -->" in text and "# /doc-read" in text
    for card_name in ("architect", "engineer", "engineer-quick", "qa", "sme", "adversary"):
        card = (V8 / ".claude" / "commands" / f"{card_name}.md").read_text(encoding="utf-8")
        skills = next(ln for ln in card.splitlines() if ln.startswith("**SKILLS**"))
        assert "/doc-write" in skills and "/doc-read" in skills, card_name
    # astra F4: the read-only Help seat holds doc_read, not the doc write tools, so it binds /doc-read only
    doctor = (V8 / ".claude" / "commands" / "doctor.md").read_text(encoding="utf-8")
    skills = next(ln for ln in doctor.splitlines() if ln.startswith("**SKILLS**"))
    assert "/doc-read" in skills and "/doc-write" not in skills


def test_a_codex_seat_binds_doc_read_for_every_role_that_holds_it():
    for role in ("architect", "engineer", "qa", "sme", "adversary"):
        names = [Path(r).name for r in seat_mod.role_skill_roots(V8, role)]
        assert "doc-read" in names, role


def test_doc_read_tool_names_the_skill_once():
    assert ALL_TOOLS["doc_read"].description.count("/doc-read") == 1
    assert "head first, then whole or sections" in ALL_TOOLS["doc_read"].description


# ----------------------------------------------------------------------------- 2 architect line and ticket hint

def test_architect_card_carries_the_section_sentence():
    card = (V8 / ".claude" / "commands" / "architect.md").read_text(encoding="utf-8")
    assert ("Each story's description names the design sections it relies on (`design §<heading>`); "
            "Key decisions apply to all.") in card


def _epic_with_design(http):
    d = _doc(http, "# D\n\n## Purpose\nx\n\n## Key decisions\n1. y\n\n## §4 Billing\nz\n", doc_type="design")
    e = http.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "E", "words": "w"},
                  headers=OWNER).json()["value"]["id"]
    assert http.patch(f"/v1/tickets/{e}", json={"design_ref": d}, headers=ARCH).json()["ok"]
    return e, d


def _story(http, e, description):
    r = http.post("/v1/tickets", json={"kind": "story", "work_type": "feature", "title": "S", "parent_id": e,
                                       "description": description}, headers=ARCH).json()
    assert r["ok"], r
    return r


def test_story_create_and_update_hint_the_headings_when_no_section_is_named(http):
    e, d = _epic_with_design(http)
    r = _story(http, e, "Build the thing.")
    assert f"description names no section of {d}" in r["hint"] and "Key decisions" in r["hint"]
    tid = r["value"]["id"]
    up = http.patch(f"/v1/tickets/{tid}", json={"title": "S2"}, headers=ARCH).json()
    assert up["ok"] and up["value"]["title"] == "S2" and "description names no section" in up["hint"]


def test_no_hint_when_a_heading_is_named(http):
    e, d = _epic_with_design(http)
    r = _story(http, e, "Build it; design §Key decisions applies.")
    assert "names no section" not in r["hint"]
    r2 = _story(http, e, "Billing work, see §4.")
    assert "names no section" not in r2["hint"]
    tid = r["value"]["id"]
    assert "names no section" not in http.patch(f"/v1/tickets/{tid}", json={"title": "S3"}, headers=ARCH).json()["hint"]


# ----------------------------------------------------------------------------- 3 already read

def test_repeat_read_serves_only_the_unsent_part_and_fresh_resends(http):
    d = _doc(http)
    first = _tool(http, "eng", "doc_read", id=d)["value"]
    assert first["body_md"] and "already_read" not in first
    n = len(first["body_md"])
    again = _tool(http, "eng", "doc_read", id=d)["value"]
    assert again["body_md"] == "" and f"you already have 0–{n:,} of v1" in again["already_read"]
    assert "fresh=true" in again["already_read"]
    page = _tool(http, "eng", "doc_read", id=d, offset=0, limit=n + 500)["value"]
    assert page["body_md"] == BIG[n:n + 500] and page["offset"] == n
    assert f"this continues from {n:,}" in page["already_read"]
    whole = _tool(http, "eng", "doc_read", id=d, fresh=True)["value"]
    assert whole["body_md"] == first["body_md"] and "already_read" not in whole


def test_a_section_read_is_tracked_in_document_coordinates(http):
    d = _doc(http)
    head = _tool(http, "eng", "doc_read", id=d)["value"]
    sec = _tool(http, "eng", "doc_read", id=d, section="### Topic 11")["value"]
    assert sec["body_md"].startswith("### Topic 11") and "already_read" not in sec
    assert _tool(http, "eng", "doc_read", id=d, section="### Topic 11")["value"]["body_md"] == ""
    assert head["total_chars"] == len(BIG)


def test_a_new_version_serves_everything(http):
    d = _doc(http)
    a = _tool(http, "eng", "doc_read", id=d)["value"]
    assert http.patch(f"/v1/docs/{d}", json={"body_md": BIG + "more\n"}, headers=ARCH).json()["ok"]
    b = _tool(http, "eng", "doc_read", id=d)["value"]
    assert b["version"] == 2 and b["body_md"][:len(a["body_md"])] == a["body_md"] and "already_read" not in b


def test_another_seat_and_a_seat_after_resume_get_full_reads(http):
    d = _doc(http)
    mine = _tool(http, "eng", "doc_read", id=d)["value"]
    assert _tool(http, "eng2", "doc_read", id=d)["value"]["body_md"] == mine["body_md"]
    assert _tool(http, "eng", "doc_read", id=d)["value"]["body_md"] == ""
    assert http.post("/v1/docs/reads/reset", headers={"X-Participant": "eng"}).json()["ok"]
    assert _tool(http, "eng", "doc_read", id=d)["value"]["body_md"] == mine["body_md"]
    assert _tool(http, "eng2", "doc_read", id=d)["value"]["body_md"] == ""


def test_a_person_is_never_trimmed(http):
    d = _doc(http)
    a = http.get(f"/v1/docs/{d}", headers=OWNER).json()["value"]
    assert http.get(f"/v1/docs/{d}", headers=OWNER).json()["value"]["body_md"] == a["body_md"]


# ----------------------------------------------------------------------------- 4 argument aliases

def test_aliases_are_accepted_on_three_tools_with_a_note(http):
    d = _doc(http)
    r = _tool(http, "eng", "doc_read", doc_id=d)
    assert r["ok"] and r["value"]["id"] == d and "'doc_id' read as 'id'" in r["hint"]
    u = _tool(http, "arch", "doc_update", doc_id=d, title="Renamed")
    assert u["ok"] and "'doc_id' read as 'id'" in u["hint"]
    e, _ = _epic_with_design(http)
    t = _tool(http, "arch", "ticket_read", ticket=e)
    assert t["ok"] and "'ticket' read as 'ticket_id'" in t["hint"]
    c = _tool(http, "arch", "criterion_query", ticket=e)
    assert c["ok"] and "'ticket' read as 'ticket_id'" in c["hint"]


def test_an_unknown_argument_is_refused_naming_the_right_one(http):
    d = _doc(http)
    for tool, args, want in [("doc_read", {"document": d}, "id"), ("ticket_read", {"ticketid": "x"}, "ticket_id"),
                             ("doc_edit", {"doc_ref": d, "expected_version": 1, "edits": []}, "id")]:
        r = _tool(http, "eng", tool, **args)
        assert r["ok"] is False and r["error"]["code"] == "schema", (tool, r)
        assert r["error"].get("nearest") == want or want in r["error"]["message"], (tool, r)


def test_an_alias_never_overrides_a_real_argument_and_the_table_is_one():
    assert ARG_ALIASES["doc_id"][0] == "id"
    r = invoke(ALL_TOOLS["doc_read"], {"doc_id": "a", "id": "b"})
    assert r["ok"] is False and r["error"]["code"] == "schema"


def test_a_fresh_boot_through_subscribe_clears_the_already_read_record(http):
    d = _doc(http)
    mine = _tool(http, "eng", "doc_read", id=d)["value"]
    assert _tool(http, "eng", "doc_read", id=d)["value"]["body_md"] == ""
    sub = _tool(http, "eng", "subscribe")
    assert sub["ok"] and sub["value"]["reads_reset"] == "cleared"
    assert _tool(http, "eng", "doc_read", id=d)["value"]["body_md"] == mine["body_md"]


def test_a_failed_reset_is_reported_not_swallowed(http, monkeypatch):
    set_client(BoardClient(participant="eng", client=http))

    def boom(self):
        raise RuntimeError("board unreachable")

    monkeypatch.setattr(BoardClient, "doc_reads_reset", boom)
    r = invoke(ALL_TOOLS["subscribe"], {}, seat="eng")
    assert r["ok"] and r["value"]["reads_reset"] == "failed: board unreachable"
