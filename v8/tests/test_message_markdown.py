"""S17 c-b1f32f8b33: chat messages render Markdown through the docs" renderer + nh3 allowlist, with
raw HTML escaped (shown as typed) and single newlines kept as line breaks."""

from __future__ import annotations

import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

from edp8 import views


def test_table_code_bold_list_link_render():
    html = views.render_message_markdown(
        "Status for **S17**:\n\n| Item | State |\n|---|---|\n| gap | fixed |\n\n"
        "```ts\nconst ok = 1 < 2;\n```\n\n- first\n- second\n\nSee [docs](https://example.com/d)")
    assert "<strong>S17</strong>" in html
    assert "<table>" in html and "<td>gap</td>" in html
    assert '<pre><code class="language-ts">const ok = 1 &lt; 2;' in html
    assert "<ul>" in html and "<li>first</li>" in html
    assert '<a href="https://example.com/d" rel="noopener noreferrer">docs</a>' in html


def test_raw_html_is_escaped_not_parsed():
    html = views.render_message_markdown('hi <b>raw</b> <script>window.x=1</script> <img src=x onerror="y()">')
    assert "<b>" not in html and "<script" not in html and "<img" not in html
    assert "&lt;b&gt;raw&lt;/b&gt;" in html and "&lt;script&gt;" in html


def test_unsafe_link_schemes_are_dropped():
    html = views.render_message_markdown("[x](javascript:alert(1)) [y](data:text/html,hi)")
    assert "javascript:" not in html and "data:" not in html


def test_single_newline_is_a_line_break():
    assert views.render_message_markdown("line one\nline two") == "<p>line one<br>\nline two</p>"


def test_thread_rows_carry_html():
    from edp8.board import Board
    from edp8.schemas import MessageKind, Role, TicketKind, WorkType
    from edp8.store import Store

    board = Board(Store(":memory:"))
    board.participant_create("human", Role.owner, "owner", id_="owner")
    owner = board.participant("owner")
    epic = board.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    board.message_send(owner, ticket_id=epic.id, to=None, kind=MessageKind.note, text="**bold** <i>x</i>")
    row = views.thread_page(board, epic.id)["thread"][-1]
    assert row["text"] == "**bold** <i>x</i>"
    assert row["html"] == "<p><strong>bold</strong> &lt;i&gt;x&lt;/i&gt;</p>"
