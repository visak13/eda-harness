"""t-994970028d (owner m-3fa1996dea): ticket and epic descriptions reach the SPA as `description_html`,
rendered by the thread's escaping markdown renderer + nh3 — `**`, backticks and list markers format,
raw HTML is escaped (shown as typed), never parsed. Board + Store(':memory:') directly.
"""
from __future__ import annotations

import pytest

from edp8 import views
from edp8.board import Board
from edp8.schemas import Role, TicketKind, WorkType
from edp8.store import Store

DESC = ("**Cause:** the pop-up renders `{ticket.description}` raw.\n\n"
        "- first item\n- second item\n\n"
        "<script>alert(1)</script>")

EXPECTED = ("<p><strong>Cause:</strong> the pop-up renders <code>{ticket.description}</code> raw.</p>\n"
            "<ul>\n<li>first item</li>\n<li>second item</li>\n</ul>\n"
            "<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>")


@pytest.fixture
def rig():
    board = Board(Store(":memory:"))
    owner = board.participant_create("human", Role.owner, "owner")
    arch = board.participant_create("agent", Role.architect, "architect")
    epic = board.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="an epic")
    story = board.ticket_create(arch, kind=TicketKind.story, work_type=WorkType.bug, title="a story",
                                parent_id=epic.id, description=DESC)
    board.ticket_update(arch, epic.id, description=DESC)
    return board, epic, story


def test_ticket_page_description_html_is_escaping_markdown(rig):
    board, _, story = rig
    page = views.ticket_page(board, story.id)
    assert page["ticket"]["description"] == DESC  # raw text unchanged for editors/tools
    assert page["description_html"] == EXPECTED
    assert "<script" not in page["description_html"]


def test_epic_page_description_html_is_escaping_markdown(rig):
    board, epic, _ = rig
    page = views.epic_page(board, epic.id)
    assert page["description"] == DESC
    assert page["description_html"] == EXPECTED


def test_empty_description_renders_empty():
    board = Board(Store(":memory:"))
    owner = board.participant_create("human", Role.owner, "owner")
    epic = board.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="bare epic")
    assert views.epic_page(board, epic.id)["description_html"] == ""
