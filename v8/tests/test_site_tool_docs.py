"""The site's tool reference (s-bd0cf6288c, owner m-b46ace6688: "the tool layer documentation ... just the input,
output"). Every tool's input is explained from docs/site/tool-docs.yml, a docs-only file the agents never read
(m-eda819eb17), and its output shows a reply captured on the made-up demo board (docs/site/tool-examples.json)."""

from __future__ import annotations

import getpass
import importlib
import re
import sys
from pathlib import Path

import pytest

from edp8 import bundles

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "docs" / "site"
yaml = pytest.importorskip("yaml")


@pytest.fixture(scope="module")
def sitegen():
    sys.path.insert(0, str(SITE / "hooks"))
    try:
        yield importlib.import_module("sitegen")
    finally:
        sys.path.remove(str(SITE / "hooks"))


def _args(tool) -> list[str]:
    return list(tool.input_schema.get("properties", {}))


def test_every_tool_and_argument_is_explained_and_nothing_stale(sitegen):
    docs = sitegen.tool_docs()
    assert set(docs) == set(bundles.ALL_TOOLS), (
        f"missing: {sorted(set(bundles.ALL_TOOLS) - set(docs))}; stale: {sorted(set(docs) - set(bundles.ALL_TOOLS))}")
    for name, tool in bundles.ALL_TOOLS.items():
        assert set(docs[name]) == set(_args(tool)), f"{name}: docs {sorted(docs[name])} vs args {sorted(_args(tool))}"
        blank = [a for a, text in docs[name].items() if not str(text or "").strip()]
        assert not blank, f"{name}: no explanation for {blank}"


def test_every_tool_has_a_captured_example(sitegen):
    examples = sitegen.tool_examples()
    assert set(examples) == set(bundles.ALL_TOOLS), (
        f"missing: {sorted(set(bundles.ALL_TOOLS) - set(examples))}; stale: {sorted(set(examples) - set(bundles.ALL_TOOLS))}")
    for name, ex in examples.items():
        assert {"caller", "args", "reply"} <= set(ex), name
        assert ex["reply"].get("ok") or ex.get("note"), f"{name}: a failed capture needs a note saying why"


def test_the_examples_carry_nothing_real():
    text = (SITE / "tool-examples.json").read_text(encoding="utf-8")
    needles = [re.escape(getpass.getuser()), r"tail[0-9a-f]{4,}", r"\.ts\.net\b", r"[A-Za-z]:(?:\\\\|\\|/)+Users(?:\\\\|\\|/)",
               r"[A-Za-z]:(?:\\\\|\\|/)+Projects(?:\\\\|\\|/)", r"\beda-base\d?\b", r"epic-0cec8d1c31",
               r"[\w.+-]+@(?!example\.(?:com|invalid)\b)[\w-]+\.[\w.]+"]
    hits = [m.group(0) for rx in needles for m in re.finditer(rx, text, re.I)]
    assert not hits, hits


def test_the_page_gives_every_tool_an_input_and_an_output(sitegen):
    md = sitegen.mcp_md()
    n = len(bundles.ALL_TOOLS)
    assert md.count("**Input**") == n and md.count("**Output**") == n
    assert md.count('??? note "Example: called by') == n


def test_agents_never_read_the_docs_only_files():
    src = ROOT / "v8" / "src"
    readers = [p for p in src.rglob("*.py") if re.search(r"tool-docs\.yml|tool-examples\.json", p.read_text(encoding="utf-8"))]
    assert not readers, readers
