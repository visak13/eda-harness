"""S13 reopen (steer m-b5e1c4478f, qa m-6399de5a1b on c-e7cba464fc; owner m-30023429f7 "any workflow"):
every seat's MCP tools come from its epic's pinned workflow role, not from the static ROLE_BUNDLES.

A duplicate of Standard drops one tool from the engineer and adds one to qa. Seats on an epic pinned to it
get the changed bundles in tools/list and at call time (the refusal names the workflow); seats on a
Standard epic, and a seat with no epic, are unchanged. The kernel tools always stay in.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest

from edp8 import mcp_server
from edp8 import workflow as wf
from edp8.board import Board
from edp8.bundles import ALL_TOOLS, tools_for_role
from edp8.schemas import Role, TicketKind, WorkType
from edp8.service import create_app
from edp8.store import Store

from test_mcp_http import _Server, _call, _free_port, _run

DROP, ADD = "find", "ticket_query"  # engineer loses find; qa gains ticket_query (S20 trimmed it from qa)


@pytest.fixture
def stack(monkeypatch):
    board = Board(Store(":memory:"))
    owner = board.participant_create("human", Role.owner, "owner", id_="owner")
    d = wf.dump(board.workflows.duplicate("standard@1", new_id="trim", by="owner"))
    for r in d["roles"]:
        if r["id"] == "engineer":
            r["bundle"] = [t for t in r["bundle"] if t != DROP]
        if r["id"] == "qa":
            r["bundle"] = [*r["bundle"], ADD]
    board.workflows.save(d, by="owner")
    ref = board.workflows.publish("trim", 1, by="owner").ref
    pinned = board.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="P", workflow=ref)
    std = board.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="S")
    for epic in (pinned, std):
        for role in (Role.engineer, Role.qa):
            board.participant_create("agent", role, f"{role.value}.{epic.id}", id_=f"{role.value}.{epic.id}")
    board.participant_create("agent", Role.engineer, "engineer.bare", id_="engineer.bare")
    bport, mport = _free_port(), _free_port()
    monkeypatch.setenv("EDP8_BOARD_URL", f"http://127.0.0.1:{bport}")
    monkeypatch.setenv("EDP8_ADMIN_TOKEN", "t")
    with _Server(create_app(board, admin_token="t"), bport), _Server(mcp_server.build_http_app(), mport):
        yield {"mcp": f"http://127.0.0.1:{mport}", "ref": ref, "pinned": pinned.id, "std": std.id}


def _tools(stack, role: str, pid: str, tool: str | None = None, **args):
    names, res = _run(_call(f"{stack['mcp']}/mcp/{role}", {"X-Participant": pid}, tool, **args))
    return set(names), (json.loads(res.content[0].text) if res is not None else None)


def test_a_pinned_workflow_changes_the_listed_bundles(stack):
    p = stack["pinned"]
    eng, who = _tools(stack, "engineer", f"engineer.{p}", "whoami")
    qa, _ = _tools(stack, "qa", f"qa.{p}")
    std_eng = {t.name for t in tools_for_role("engineer")}
    std_qa = {t.name for t in tools_for_role("qa")}
    assert eng == std_eng - {DROP}
    assert qa == std_qa | {ADD}
    assert set(wf.KERNEL_TOOLS) <= eng and set(wf.KERNEL_TOOLS) <= qa
    assert who["value"]["workflow"] == stack["ref"] and DROP not in who["value"]["bundles_available"]


def test_a_pinned_workflow_gates_calls_and_the_refusal_names_it(stack):
    p = stack["pinned"]
    _, out = _tools(stack, "engineer", f"engineer.{p}", DROP, query="x")
    assert out["ok"] is False and out["error"]["code"] == "forbidden"
    assert stack["ref"] in out["error"]["message"] and "'engineer'" in out["error"]["message"]
    _, out = _tools(stack, "qa", f"qa.{p}", ADD)
    assert out["ok"] is True, out


def test_a_standard_epic_and_a_bare_seat_are_unchanged(stack):
    s = stack["std"]
    std_eng = {t.name for t in tools_for_role("engineer")}
    for pid in (f"engineer.{s}", "engineer.bare"):
        eng, _ = _tools(stack, "engineer", pid)
        assert eng == std_eng, pid
    qa, _ = _tools(stack, "qa", f"qa.{s}")
    assert qa == {t.name for t in tools_for_role("qa")} and ADD not in qa
    _, out = _tools(stack, "qa", f"qa.{s}", ADD)
    assert out["error"]["code"] == "forbidden" and "standard@1" in out["error"]["message"]


def test_another_roles_path_still_shares_only_its_standard_tools(stack):
    p = stack["pinned"]
    names, _ = _tools(stack, "owner", f"qa.{p}")
    assert names == ({t.name for t in tools_for_role("qa")} | {ADD}) & {t.name for t in tools_for_role("owner")}


def test_kernel_tools_survive_a_bundle_that_drops_them():
    got = mcp_server.allowed_tool_names("engineer", "engineer", ["ticket_read"])
    assert got == {"ticket_read", *wf.KERNEL_TOOLS} & set(ALL_TOOLS)


def test_role_bundles_is_read_only_as_the_standard_source():
    """grep: outside its own module, only workflow.build_standard reads ROLE_BUNDLES in src/edp8."""
    src = Path(__file__).resolve().parents[1] / "src" / "edp8"
    readers = {}
    for f in src.rglob("*.py"):
        lines = [i for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
                 if re.search(r"\bROLE_BUNDLES\b", line) and not line.lstrip().startswith("#")]
        if lines:
            readers[f.relative_to(src).as_posix()] = lines
    assert set(readers) == {"bundles.py", "workflow.py"}, readers
    lines = (src / "workflow.py").read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines, 1) if line.startswith("def build_standard("))
    end = next(i for i, line in enumerate(lines, 1) if i > start and line.startswith("def "))
    docstring_end = next(i for i, line in enumerate(lines, 1) if i > 1 and '"""' in line)
    assert all(n <= docstring_end or start < n < end for n in readers["workflow.py"]), readers["workflow.py"]
