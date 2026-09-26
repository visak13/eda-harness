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


# CommonMark-style nesting (3 spaces under `1. `, 2 under `- `): the live s-ca39f10643 description
# showed its sub-items as literal `- ` lines until the renderer re-indented them to Python-Markdown's 4.
@pytest.mark.parametrize("text, expected", [
    ("1. **a** item:\n   - one\n   - two\n2. next\n",
     "<ol>\n<li><strong>a</strong> item:<ul>\n<li>one</li>\n<li>two</li>\n</ul>\n</li>\n<li>next</li>\n</ol>"),
    ("- a\n  - b\n    - c\n- d\n",
     "<ul>\n<li>a<ul>\n<li>b<ul>\n<li>c</li>\n</ul>\n</li>\n</ul>\n</li>\n<li>d</li>\n</ul>"),
])
def test_commonmark_nested_lists_nest(text, expected):
    assert views.render_message_markdown(text) == expected
    assert views.render_markdown(text) == expected.replace("<br>", "")


@pytest.mark.parametrize("text, expected", [
    ("Para\n\n    code line\n    - not a list\n", "<p>Para</p>\n<pre><code>code line\n- not a list\n</code></pre>"),
    ("- a\n\n```\n  - keep\n```\n", "<ul>\n<li>a</li>\n</ul>\n<pre><code>  - keep\n</code></pre>"),
])
def test_nested_list_indent_leaves_code_alone(text, expected):
    assert views.render_message_markdown(text) == expected
