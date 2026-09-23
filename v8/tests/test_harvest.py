"""S-HARVEST (s-043eb90ccc, design-34bf11cc07 §4.5): qa's last step is /harvest; /learn files a lesson
or a proposed doc version in the Library, addressed to nobody; the owner's approval makes the next
brief carry the new version, a reject leaves it unchanged. The skill text and the tool surface are
pinned together here so a later S20 trim cannot strand the skills again."""

from __future__ import annotations

import os
import re
from pathlib import Path

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

from edp8.board import Board
from edp8.bundles import ALL_TOOLS, set_client, tools_for_role
from edp8.client import BoardClient
from edp8.service import create_app
from edp8.store import Store

V8 = Path(__file__).resolve().parents[1]
ADMIN = {"X-Admin": "t"}
OWNER = {"X-Participant": "owner"}
LEARN_ROLES = ("architect", "engineer", "qa", "sme", "adversary")


def _read(rel: str) -> str:
    return (V8 / rel).read_text(encoding="utf-8")


# ----------------------------------------------------------------------------- skills and cards
def test_qa_card_ends_with_harvest_before_close():
    card = _read(".claude/commands/qa.md")
    skills = next(line for line in card.splitlines() if line.startswith("**SKILLS**"))
    assert "/harvest" in skills
    protocol = card.split("**PROTOCOL**", 1)[1]
    assert protocol.index("/harvest") < protocol.rindex("CLOSE")
    assert "LAST STEP" in protocol


def test_harvest_skill_is_qa_scoped_and_files_lessons_and_proposals():
    s = _read(".claude/skills/harvest/SKILL.md")
    assert "<!-- roles: qa -->" in s
    assert "record_lesson(" in s and 'status="proposed"' in s and "proposes=<its id>" in s
    assert "ticket_id=<epic>" in s  # the proposal's source is the qa seat + the epic
    assert "## Harvest" in s  # the records are listed in the qa report
    assert "consult(" not in s  # one bounded pass, no model fan-out


def test_learn_files_a_proposal_not_a_note_to_the_sme():
    s = _read(".claude/skills/learn/SKILL.md")
    assert "record_lesson(" in s and 'status="proposed"' in s
    assert "to=sme" not in s and "message_send" not in s
    sme = _read(".claude/commands/sme.md")
    assert "/learn notes addressed to you" not in sme and "/learn is not addressed to you" in sme


@pytest.mark.parametrize("role", LEARN_ROLES)
def test_every_learn_seat_carries_the_tools_the_skills_name(role):
    names = {t.name for t in tools_for_role(role)}
    assert {"record_lesson", "doc_create", "doc_read", "lookup"} <= names, role


def test_every_card_listing_learn_is_a_learn_role():
    for card in (V8 / ".claude" / "commands").glob("*.md"):
        skills = next((ln for ln in card.read_text(encoding="utf-8").splitlines() if ln.startswith("**SKILLS**")), "")
        if re.search(r"/learn\b", skills):
            assert card.stem in LEARN_ROLES, card.stem


# ----------------------------------------------------------------------------- the loop on a board
@pytest.fixture
def client():
    return TestClient(create_app(Board(Store(":memory:")), admin_token="t"))


@pytest.fixture
def rig(client):
    for pid, role, typ in [("owner", "owner", "human"), ("arch", "architect", "agent"), ("qa.e", "qa", "agent")]:
        assert client.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                           headers=ADMIN).json()["ok"]
    epics, stories = [], []
    for title in ("finished epic", "next epic"):
        e = client.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": title},
                        headers=OWNER).json()["value"]["id"]
        s = client.post("/v1/tickets", json={"kind": "story", "work_type": "feature", "title": "s", "parent_id": e},
                        headers={"X-Participant": "arch"}).json()["value"]["id"]
        epics.append(e), stories.append(s)
    doc = client.post("/v1/docs", json={"doc_type": "strategy_ll", "title": "craft", "scope": "global",
                                        "body_md": "## Enforced\n- run the spec you changed [required]"},
                      headers=OWNER).json()["value"]
    for e in epics:
        assert client.post("/v1/links", json={"from_id": e, "to_id": doc["id"], "relation": "uses_strategy"},
                           headers=OWNER).json()["ok"]
    return {"epics": epics, "stories": stories, "doc": doc}


def _call(client, who: str, name: str, **args):
    set_client(BoardClient(participant=who, client=client))
    tool = ALL_TOOLS[name]
    return tool.handler(tool.args_model(**args))


def _enforced(client, story: str) -> list[str]:
    out = _call(client, "owner", "assemble_ruleset", ticket_id=story)
    assert out["ok"], out
    return [line["text"] for line in out["value"]["enforced"]]


def test_qa_harvest_records_approve_carries_the_new_version_reject_leaves_it(client, rig):
    finished, _next = rig["epics"]
    doc = rig["doc"]
    les = _call(client, "qa.e", "record_lesson", domain="testing", topic="e2e",
                text="A full e2e run from a doer seat OOMs the host; run the spec you changed.", evidence=[finished])
    assert les["ok"] and les["value"]["created_by"] == "qa.e"
    new_bar = "- run the spec you changed; the full suite is qa's, one seat at a time [required]"
    prop = _call(client, "qa.e", "doc_create", doc_type="strategy_ll", title="craft", scope="global",
                 body_md=f"## Enforced\n{new_bar}", status="proposed", proposes=doc["id"], ticket_id=finished)
    assert prop["ok"], prop
    p = prop["value"]
    assert p["status"] == "proposed" and p["source"] == {"participant": "qa.e", "ticket": finished}
    diff = client.get(f"/v1/docs/{p['id']}/diff", headers=OWNER).json()["value"]["diff"]
    assert f"+{new_bar}" in diff
    # nothing changes before the owner rules
    assert _enforced(client, rig["stories"][1]) == ["- run the spec you changed [required]"]
    assert client.post(f"/v1/docs/{p['id']}/approve", headers=OWNER).json()["ok"]
    assert _enforced(client, rig["stories"][1]) == [new_bar]
    # a second proposal, rejected: retired, and the brief stays on the approved version
    bad = _call(client, "qa.e", "doc_create", doc_type="strategy_ll", title="craft", scope="global",
                body_md="## Enforced\n- skip tests [required]", status="proposed", proposes=doc["id"],
                ticket_id=finished)["value"]
    r = client.post(f"/v1/docs/{bad['id']}/reject", headers=OWNER).json()["value"]["doc"]
    assert r["status"] == "retired" and r["resolution"] == "rejected"
    assert _enforced(client, rig["stories"][1]) == [new_bar]


# ----------------------------------------------------------------------------- scripts/harvest_cost.py
def _cost():
    import importlib.util
    spec = importlib.util.spec_from_file_location("harvest_cost", V8 / "scripts" / "harvest_cost.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _asst(ts, mid, usage=None, tools=()):
    content = [{"type": "tool_use", "name": n, "input": i} for n, i in tools] or [{"type": "text", "text": "x"}]
    return {"type": "assistant", "timestamp": ts, "message": {"id": mid, "content": content,
                                                              "usage": usage or {"input_tokens": 1, "output_tokens": 1}}}


def test_harvest_cost_claude_window_counts_each_api_call_once():
    hc = _cost()
    u = {"input_tokens": 10, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 1000, "output_tokens": 5}
    rows = [_asst("2026-09-24T10:00:00Z", "m0", tools=[("mcp__edp8__criterion_update", {})]),  # verdicts: before
            _asst("2026-09-24T10:01:00Z", "m1", u, [("Skill", {"skill": "harvest"})]),
            _asst("2026-09-24T10:02:00Z", "m2", u, [("mcp__edp8__record_lesson", {})]),
            _asst("2026-09-24T10:02:00Z", "m2", u, [("mcp__edp8__doc_create", {"status": "proposed"})]),  # same call
            _asst("2026-09-24T10:03:00Z", "m3", u, [("mcp__edp8__close_self", {})]),
            _asst("2026-09-24T10:09:00Z", "m4", u)]  # after close: not counted
    start, end = hc.claude_window(rows)
    assert (hc._iso(start), hc._iso(end)) == ("2026-09-24T10:01:00Z", "2026-09-24T10:03:00Z")
    assert hc.claude_tokens(rows, start, end) == {"calls": 3, "input_tokens": 30, "cache_creation_input_tokens": 300,
                                                  "cache_read_input_tokens": 3000, "output_tokens": 15}


def test_harvest_cost_codex_window_is_a_total_delta_and_ignores_the_boot_skill_catalog():
    hc = _cost()

    def usage(ts, inp, out):
        return {"ts": ts, "msg": {"method": "thread/tokenUsage/updated", "params": {"tokenUsage": {"total": {
            "inputTokens": inp, "cachedInputTokens": 0, "outputTokens": out, "reasoningOutputTokens": 0,
            "totalTokens": inp + out}}}}}

    def item(ts, **it):
        return {"ts": ts, "msg": {"method": "item/started", "params": {"item": it}}}

    rows = [{"ts": 1, "msg": {"id": 3, "result": {"skills": [{"path": r"C:\v8\.claude\skills\harvest\SKILL.md"}]}}},
            usage(5, 1000, 50),
            item(10, type="commandExecution", command="Get-Content .claude/skills/harvest/SKILL.md"),
            item(11, type="mcpToolCall", tool="record_lesson", arguments={}),
            usage(12, 1600, 90),
            item(13, type="mcpToolCall", tool="close_self", arguments={}),
            usage(20, 9000, 900)]
    start, end = hc.codex_window(rows)
    assert (start, end) == (10, 13)
    t = hc.codex_tokens(rows, start, end)
    assert (t["inputTokens"], t["outputTokens"], t["calls"]) == (600, 40, 1)


def test_harvest_cost_splits_records_by_author():
    hc = _cost()
    view = {"lessons": [{"id": "les-1", "created_by": "qa.e", "created_at": "2026-09-24T10:02:00+00:00"},
                        {"id": "les-2", "created_by": "board", "created_at": "2026-09-24T10:02:30+00:00"},
                        {"id": "les-0", "created_by": "eng", "created_at": "2026-09-23T10:00:00+00:00"}],
            "docs": [{"id": "d-1", "status": "proposed", "proposes": "s-1", "source": {}, "created_by": "qa.e",
                      "created_at": "2026-09-24T10:02:10+00:00"},
                     {"id": "d-2", "status": "active", "source": None, "created_by": "owner",
                      "created_at": "2026-09-24T10:02:20+00:00"}]}
    recs = hc.records_in_window(view, hc._ts("2026-09-24T10:00:00Z"), hc._ts("2026-09-24T10:03:00Z"))
    assert sorted((r["id"], r["created_by"]) for r in recs) == [("d-1", "qa.e"), ("les-1", "qa.e"), ("les-2", "board")]
