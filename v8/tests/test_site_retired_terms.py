"""The site pages, docs/OPERATING.md and the README describe only what ships (design-63db8a7d42 item P,
s-bd0cf6288c): the owner's "Needs you" list, the asks ledger and the gates the architect now decides in chat are
gone, and a retired term must not return. Historical reports under docs/ are exempt."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGES = sorted((ROOT / "docs" / "site" / "docs").rglob("*.md"))
SITE = ROOT / "docs" / "site"
#: what the MCP tools page is rendered from (F1: a stale "Needs you" sat in an example reply)
GENERATED = [SITE / "tool-docs.yml", SITE / "tool-examples.json"]
OPERATOR = [ROOT / "v8" / "docs" / "OPERATING.md", ROOT / "v8" / "README.md", ROOT / "README.md"]

RETIRED = [
    r"needs you\b",
    r"waiting on you\b",
    r"asks?[ -]ledger",
    r"\bask_(?:triage|verdict)\b",
    r"\b(?:poc|proof[- ]of[- ]concept|demo|adversarial|budget|acceptance)[ -]gate",
    r"quick[- ]task design",
    r"board (?:starts|staffs|spawns) qa",
]
COVERED = {
    "Mark as requirement": "docs/site/docs/guide/work.md",
    "Close": "docs/site/docs/guide/work.md",
    "docs mirror": "v8/docs/OPERATING.md",
}


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_the_scanned_files_exist():
    assert len(PAGES) >= 10 and all(p.exists() for p in OPERATOR), (len(PAGES), [p for p in OPERATOR if not p.exists()])


def test_no_retired_term_returns():
    hits = [f"{p.relative_to(ROOT)}: {m.group(0)!r}" for p in [*PAGES, *OPERATOR, *GENERATED]
            for rx in RETIRED for m in re.finditer(rx, _text(p), re.I)]
    assert not hits, hits


def test_what_replaced_them_is_described():
    for phrase, rel in COVERED.items():
        assert phrase.lower() in _text(ROOT / rel).lower(), f"{rel} must cover {phrase!r}"


def test_the_generated_tools_page_carries_no_retired_term():
    import importlib
    import sys

    pytest = __import__("pytest")
    pytest.importorskip("yaml")
    sys.path.insert(0, str(SITE / "hooks"))
    try:
        md = importlib.import_module("sitegen").mcp_md()
    finally:
        sys.path.remove(str(SITE / "hooks"))
    hits = [m.group(0) for rx in RETIRED for m in re.finditer(rx, md, re.I)]
    assert not hits, hits
