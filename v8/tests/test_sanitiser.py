"""nh3 allowlist sanitiser tests (views.render_markdown, design §18.1 / S21).

render_markdown is the ONE renderer both /ui HTML and the JSON doc endpoint call, so a doc that
gets past it reaches every reader. These prove the allowlist's teeth: scripts, handlers, iframes,
SVG/MathML and javascript:/data: links never survive — while headings, lists, tables, code and
http/https/mailto links do. Malformed input is tolerated, not crashed.
"""

from __future__ import annotations

import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest

from edp8 import views


def _html(md: str) -> str:
    return views.render_markdown(md)


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
    out = _html(payload).lower()
    for bad in ("<script", "onerror", "onload", "<iframe", "<svg", "<math", "javascript:",
                "data:text/html", "<object", "<style"):
        assert bad not in out, f"{bad!r} survived: {out!r}"


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
