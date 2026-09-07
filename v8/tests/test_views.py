"""Characterisation snapshots of the LEGACY /ui HTML (design §4.4a, strategy Phase 2).

These pin what `ui.py` renders TODAY for a fixed rig — BEFORE any views.py extraction —
so the extraction can be proved byte-identical (golden-master / Feathers). Committed in
its own commit ahead of the extraction commit (criterion c-5425fb202a: git log order).
A deliberate output change (the nh3 sanitiser swap, S21) updates the doc-md snapshots
with the diff explained in that commit (c-81f3df9052).

Fragments are pinned exactly, with the rig's generated ids interpolated and volatile
dates masked; drift in any pinned fragment fails the test (proves it pins behaviour,
not merely that the page renders)."""

from __future__ import annotations

import os
import re

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

from edp8 import broker_adapter
from edp8.board import Board
from edp8.service import create_app
from edp8.store import Store

ADMIN = {"X-Admin": "t"}
OWN = {"X-Participant": "owner"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(broker_adapter, "publish", lambda *a, **k: True)
    return TestClient(create_app(Board(Store(":memory:")), admin_token="t"))


@pytest.fixture
def rig(client):
    def post(path, json, headers):
        r = client.post(path, json=json, headers=headers).json()
        assert r["ok"], r
        return r["value"]

    for pid, role, typ in [("owner", "owner", "human"), ("ravi", "reviewer", "human"),
                           ("arch", "architect", "agent"), ("craft", "sme", "agent")]:
        post("/v1/participants", {"type": typ, "role": role, "handle": pid, "id": pid}, ADMIN)
    epic = post("/v1/tickets", {"kind": "epic", "work_type": "feature", "title": "Galaxy site"}, OWN)["id"]
    story = post("/v1/tickets", {"kind": "story", "work_type": "bug", "title": "fix the ship sheet",
                                 "parent_id": epic, "tags": ["assets"]}, {"X-Participant": "arch"})["id"]
    seat = f"engineer.{story}"
    post("/v1/participants", {"type": "agent", "role": "engineer", "handle": seat, "id": seat}, ADMIN)
    client.put("/v1/sessions/sid-1", json={"participant_id": seat, "ticket_id": story, "pool_id": "local",
                                           "state": "alive"}, headers=ADMIN)
    crit = post("/v1/criteria", {"ticket_id": story, "text": "the ship sheet renders", "check": "command"},
                {"X-Participant": "arch"})["id"]
    kt = post("/v1/tickets", {"kind": "story", "work_type": "knowledge", "title": "hl-craft",
                              "parent_id": epic, "assignee": "craft"}, {"X-Participant": "arch"})["id"]
    kcrit = post("/v1/criteria", {"ticket_id": kt, "text": "strategy doc signed by the owner",
                                  "check": "look", "checked_by": "owner"}, {"X-Participant": "arch"})["id"]
    doc = post("/v1/docs", {"doc_type": "strategy_hl", "title": "shape",
                            "body_md": "# Walking skeleton\n- build the **thin** thread first",
                            "scope": epic}, {"X-Participant": "craft"})["id"]
    client.patch(f"/v1/criteria/{kcrit}", json={"evidence_ref": doc}, headers={"X-Participant": "craft"})
    post("/v1/messages", {"ticket_id": story, "kind": "question", "to": "owner", "text": "one?"},
         {"X-Participant": "ravi"})
    post("/v1/messages", {"ticket_id": epic, "kind": "question", "to": "owner", "text": "two?"},
         {"X-Participant": "ravi"})
    return {"client": client, "epic": epic, "story": story, "seat": seat, "crit": crit,
            "kt": kt, "kcrit": kcrit, "doc": doc}


def _mask(s: str) -> str:
    return re.sub(r"\d{4}-\d{2}-\d{2}", "DATE", s)


def _one(html: str, pattern: str) -> str:
    m = re.search(pattern, html, re.DOTALL)
    assert m, f"fragment not found: {pattern}"
    return m.group(0)


# --------------------------------------------------------------------------- /ui/me


def test_signoff_card_pinned(rig):
    page = rig["client"].get("/ui/me", params={"as": "owner"}).text
    frag = _one(page, r"<article class='signoff-card'>.*?</article>")
    kt, kcrit = rig["kt"], rig["kcrit"]
    assert frag == (
        f"<article class='signoff-card'><div class='who'>sign-off wanted on "
        f"<a href='/ui/ticket/{kt}'>{kt}</a> · <span class='object-id'>{kcrit}</span></div>"
        f"<p>strategy doc signed by the owner</p><details open><summary>shape "
        f"<span class='muted'>strategy_hl v1</span></summary><div class='doc-md'>"
        f"<h1>Walking skeleton</h1>\n<ul>\n<li>build the <strong>thin</strong> thread first</li>\n</ul>"
        f"</div></details><form class='signoff-actions' method='post' action='/ui/me/verdict'>"
        f"<input type='hidden' name='as_' value='owner'><input type='hidden' name='token' value=''>"
        f"<input type='hidden' name='criterion_id' value='{kcrit}'>"
        f"<input type='hidden' name='ticket_id' value='{kt}'>"
        f"<input name='note' placeholder='optional note to the author…'>"
        f"<button name='verdict' value='pass' title='approve — the ticket can close'>Approve</button>"
        f"<button name='verdict' value='fail' class='btn-fail' "
        f"title='send back — add a note saying what is missing'>Needs work</button></form></article>")


def test_asks_grouped_by_ticket(rig):
    page = rig["client"].get("/ui/me", params={"as": "owner"}).text
    assert page.count("class='fold ask-group'") == 2  # one group per ticket
    epic, story = rig["epic"], rig["story"]
    summary = _one(page, r"<details class='fold ask-group' open><summary>.*?</summary>")
    assert summary == (
        f"<details class='fold ask-group' open><summary>"
        f"<a class='ticket-chip' href='/ui/ticket/{epic}'>{epic}</a> › "
        f"<a class='ticket-chip' href='/ui/ticket/{story}'>{story}</a>"
        f"<span class='muted'>fix the ship sheet</span><span class='count'>1</span></summary>")


def test_who_can_i_reach_seat_states(rig):
    page = rig["client"].get("/ui/me", params={"as": "owner"}).text
    seat, story = rig["seat"], rig["story"]
    # a live engineer seat: mono handle + ticket chip + "● up"
    assert (f"<span class='mono'>@{seat}</span>"
            f"<a class='ticket-chip' href='/ui/ticket/{story}'>{story}</a>"
            f"<span class='muted seat-up'>● up</span></div>") in page
    assert "title='a running engineer seat — steer it on its ticket thread'" in page
    # a human person row
    assert "<span class='mono'>@owner</span><span class='muted'>person</span></div>" in page
    assert "title='type @owner in a message to notify them'" in page


def test_conversations_rows(rig):
    page = rig["client"].get("/ui/me", params={"as": "owner"}).text
    story, epic = rig["story"], rig["epic"]
    assert (f"<a class='convo-row' href='/ui/ticket/{story}?as=owner' title='fix the ship sheet'>"
            f"<span class='unread-dot' title='waiting on you'></span>") in page
    assert f"<span class='convo-name'>{story}</span><span class='muted convo-snip'>one?</span></a>" in page
    assert f"<span class='convo-name'>{epic}</span><span class='muted convo-snip'>two?</span></a>" in page


# --------------------------------------------------------------------------- /ui


def test_epics_row_with_passed_total(rig):
    page = rig["client"].get("/ui").text
    epic = rig["epic"]
    frag = _mask(_one(page, r"<a class='epic-row'.*?</a>"))
    assert frag == (
        f"<a class='epic-row' href='/ui/epic/{epic}'><div class='epic-title'>"
        f"<span class='object-id'>{epic}</span>Galaxy site</div>"
        f"<div class='epic-meta'>0 / 0 passed<div class='progress'><span style='width:0%'></span></div></div>"
        f"<div class='epic-meta'>DATE</div><span class='badge s-drafted'>drafted</span>"
        f"<span class='chevron'>›</span></a>")


# --------------------------------------------------------------------------- /ui/tickets


def test_tickets_table_row(rig):
    page = rig["client"].get("/ui/tickets").text
    story, epic = rig["story"], rig["epic"]
    assert (
        f"<tr><td><a href='/ui/ticket/{story}' class='object-id'>{story}</a></td>"
        f"<td><a class='ticket-chip' href='/ui/ticket/{epic}'>{epic}</a></td>"
        f"<td title='fix the ship sheet'>fix the ship sheet</td><td>story/bug</td>"
        f"<td><span class='badge s-drafted'>drafted</span></td><td>—</td>"
        f"<td><span class=tag>assets</span></td><td>0/1</td></tr>") in page


# --------------------------------------------------------------------------- /ui/epic


def test_epic_kanban_columns(rig):
    page = rig["client"].get(f"/ui/epic/{rig['epic']}", params={"as": "owner"}).text
    story = rig["story"]
    assert "<div class='kanban-head'>Backlog <span class='count'>2</span></div>" in page
    assert (
        f"<a class='kanban-card' href='/ui/ticket/{story}?as=owner' title='fix the ship sheet'>"
        f"<div class='kanban-top'><span class='object-id'>{story}</span></div>"
        f"<div class='kanban-title'>fix the ship sheet</div>"
        f"<div class='kanban-meta'>bug<span class=tag>assets</span></div></a>") in page
    for empty in ("In progress", "In review", "Done"):
        assert f"<div class='kanban-head'>{empty} <span class='count'>0</span></div>" \
               "<div class=kanban-empty></div></div>" in page


# --------------------------------------------------------------------------- /ui/ticket


def test_ticket_page_criterion(rig):
    page = rig["client"].get(f"/ui/ticket/{rig['story']}", params={"as": "owner"}).text
    crit = rig["crit"]
    frag = _one(page, r"<article class='criterion pending'>.*?</article>")
    assert frag == (
        f"<article class='criterion pending'><div class='criterion-head'><span>·</span>"
        f"<span class='badge s-pending'>pending</span><span class='object-id'>{crit}</span></div>"
        f"<p>the ship sheet renders</p>"
        f"<div class='criterion-meta'>command · responsible: qa</div></article>")


# --------------------------------------------------------------------------- /ui/doc


def test_doc_page_html(rig):
    page = rig["client"].get(f"/ui/doc/{rig['doc']}").text
    frag = _one(page, r"<article class='document-reader doc-md'>.*?</article>")
    assert frag == (
        "<article class='document-reader doc-md'><h1>Walking skeleton</h1>\n<ul>\n"
        "<li>build the <strong>thin</strong> thread first</li>\n</ul></article>")


# --------------------------------------------------------------------------- /ui/activity


def test_activity_feed_lines(rig):
    page = rig["client"].get("/ui/activity", params={"as": "owner"}).text
    # feed_line for the two questions ravi asked the owner
    assert "ravi → owner: one?" in page
    assert "ravi → owner: two?" in page
    assert "<div class='system-event'>" in page
