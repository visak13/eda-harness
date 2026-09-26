"""nh3 allowlist sanitiser tests (views.render_markdown, design §18.1 / S21).

render_markdown is the ONE renderer both /ui HTML and the JSON doc endpoint call, so a doc that
gets past it reaches every reader. These prove the allowlist's teeth: scripts, handlers, iframes,
SVG/MathML and javascript:/data: links never survive — while headings, lists, tables, code and
http/https/mailto links do. Malformed input is tolerated, not crashed.
"""

from __future__ import annotations

import os
from html.parser import HTMLParser

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest

from edp8 import views


def _html(md: str) -> str:
    return views.render_markdown(md)


class _LiveMarkup(HTMLParser):
    """The tags and attributes a browser would actually build from the output; escaped text
    (`&lt;script&gt;`) is data here, as it is to the browser."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.attrs: list[tuple[str, str]] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attrs += [(k, v or "") for k, v in attrs]


def _live(out: str) -> _LiveMarkup:
    p = _LiveMarkup()
    p.feed(out)
    p.close()
    return p


@pytest.mark.parametrize("payload", [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "<iframe src='https://evil.test'></iframe>",
    "<svg onload=alert(1)><circle r=10></svg>",
    "<math><mtext>x</mtext></math>",
    "<a href=\"javascript:alert(1)\">x</a>",
    "<a href=\"data:text/html;base64,PHNjcmlwdD4=\">x</a>",
    "[click](javascript:alert(1))",
    "[click](data:text/html,<script>alert(1)</script>)",
    "<a href=\"javascript&#58;alert(1)\">x</a>",
    "<a href=\"jAvAsCrIpT:alert(1)\">x</a>",
    "<object data=evil></object>",
    "<style>body{background:url(javascript:alert(1))}</style>",
])
def test_dangerous_markup_is_stripped(payload):
    # raw HTML is escaped to inert text (t-f0ec383cff), so check the LIVE markup, not substrings
    out = _html(payload)
    live = _live(out)
    for bad in ("script", "iframe", "svg", "math", "object", "style", "img"):
        assert bad not in live.tags, f"<{bad}> survived: {out!r}"
    for k, v in live.attrs:
        assert not k.lower().startswith("on"), f"handler {k!r} survived: {out!r}"
        assert not v.strip().lower().startswith(("javascript:", "data:")), f"{k}={v!r} survived: {out!r}"


def test_raw_html_placeholders_are_escaped_not_parsed():
    """t-f0ec383cff: `Needs you → <card> → <button>` in a blank-line-free block became an HTML
    block, its markdown went unparsed and nh3 dropped the unknown tags and what they swallowed."""
    # the shape of design-e963c656f5 v24 §4.16: the placeholder sits inside a blank-line-free list
    md = ("Flow: a <card> b <button> c\n\n"
          "- **Waits:** click path (\"Needs you → <card> → <button> → Pass/Fail\").\n"
          "- first bullet\n"
          "- second bullet\n\n"
          "## Later heading\n\n"
          "tail text")
    out = _html(md)
    assert "a &lt;card&gt; b &lt;button&gt; c" in out
    assert "<ul>" in out and "<li>first bullet</li>" in out and "<li>second bullet</li>" in out
    assert "<h2>Later heading</h2>" in out and "tail text" in out
    assert "card" not in _live(out).tags and "button" not in _live(out).tags


def test_safe_content_survives():
    md = ("# Heading\n\n"
          "- one\n- two\n\n"
          "| a | b |\n|---|---|\n| 1 | 2 |\n\n"
          "```python\nprint('hi')\n```\n\n"
          "text with **bold**, _em_, `code`, [ok](https://ok.test) and [mail](mailto:a@b.co).")
    out = _html(md)
    for good in ("<h1>Heading</h1>", "<li>one</li>", "<table>", "<th>a</th>", "<td>1</td>",
                 "<pre>", "<code", "<strong>bold</strong>", "<em>em</em>",
                 "https://ok.test", "mailto:a@b.co"):
        assert good in out, f"{good!r} missing from {out!r}"


def test_malformed_html_does_not_crash():
    out = _html("<b><i>bold but never closed <a href='https://ok.test'>link")
    assert "https://ok.test" in out and "<script" not in out
    assert "bold but never closed" in out


def test_empty_and_none_bodies():
    assert _html("") == ""
    assert views.render_markdown(None) == ""  # type: ignore[arg-type]
