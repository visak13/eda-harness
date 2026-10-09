"""e0cec S9 (s-8ca20e8543) task 4: the tool-definition audit, as a test.

les-a5b22ca20d: an audit that never makes a SUCCESSFUL call proves nothing. So every ToolDef in ALL_TOOLS gets at least
one realistic call, made through `invoke()` (the MCP path) as a seat of a role that holds the tool, against a hermetic
in-memory board; the result must be ok. The pool (spawn/resume/reap/release_self) and the web fetch behind
topic_research are the only canned parts, and the matrix row says so. A tool without a row fails
`test_the_table_covers_every_tool`, so a new tool cannot ship unaudited.

p-7fc6b2a2 part 2: a failing call must name the accepted args and, for an enum, the accepted values; one failing call
per tool shape (unknown arg, missing required arg, bad enum value) is checked through the same path.

The matrix (tool, role, args, ok, first 120 chars of the result, args without a description) is written to
$EDP_S9_MATRIX when set (JSON), for the report.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

import edp8.bundles as bundles_mod
from edp8 import topics
from edp8.board import Board
from edp8.bundles import ALL_TOOLS, ROLE_BUNDLES, accepted_args, enum_fields, invoke, set_client
from edp8.client import BoardClient
from edp8.schemas import (Check, DocType, MessageKind, Role, TicketKind, TicketStatus, WorkType)
from edp8.search import Index, make_embedder
from edp8.service import create_app
from edp8.store import Store

OWNER_TOKEN = "owner-secret"
OWNER = {"X-Participant": "owner", "X-Token": OWNER_TOKEN}


class StubPool:
    def spawn(self, role, participant_id, **kw):
        return {"ok": True, "participant_id": participant_id}

    def close(self, participant_id, reason="", **_):
        return {"ok": True}

    def reap(self, participant_id, **_):
        return {"ok": True}


# the only canned parts: the pool process control plane, and the page fetch behind topic_research
_POOL_REPLY = {"spawn": {"ok": True, "value": {"session_id": "sess-1", "participant_id": "x"}},
               "resume": {"ok": True, "value": {"resumed": True}},
               "reap": {"ok": True, "value": {"reaped": True}},
               "release_self": {"ok": True, "value": {"released": True}}}


def _pool_call(fn, kwargs):
    return dict(_POOL_REPLY.get(fn, {"ok": True, "value": {}}))


_PAGE = b"<html><body><h1>Python testing patterns</h1><p>Arrange, Act, Assert.</p></body></html>"


def _fetch(url):
    if url.startswith("https://skills.sh/"):
        return 308, b"", url.replace("https://skills.sh/", "https://www.skills.sh/")
    if url.startswith("https://www.skills.sh/api/search"):
        return 200, json.dumps({"skills": [{"id": "a/b/c", "name": "c", "installs": 1}]}).encode(), None
    if url.startswith("https://www.skills.sh/"):
        return 200, _PAGE, None
    return 404, b"", None


class World:
    """The seeded board plus one BoardClient per role."""

    def __init__(self, monkeypatch, tmp_path):
        monkeypatch.setattr(bundles_mod, "_pool_call", _pool_call)
        monkeypatch.setattr(topics, "FETCH", _fetch)
        monkeypatch.setattr(topics, "RESOLVE", lambda host: ["76.76.21.21"], raising=False)
        self.tmp = tmp_path
        tokens = tmp_path / "tokens.json"  # token mode: the owner is the admin human (teammate), seats are header-only
        tokens.write_text(json.dumps({"owner": OWNER_TOKEN, "agents": {}}), encoding="utf-8")
        monkeypatch.setenv("EDP8_TOKENS", str(tokens))
        monkeypatch.setenv("EDP8_OWNER", "owner")
        self.board = b = Board(Store(":memory:"), Index(embedder=make_embedder()), pool=StubPool(),
                               free_mb=lambda: 4096)
        self.http = TestClient(create_app(b, admin_token="t"))
        owner = b.participant_create("human", Role.owner, "owner", id_="owner")
        epic = b.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="Showroom site",
                               description="a showcase site for the galaxy game")
        E = epic.id
        mk = lambda role, pid: b.participant_create("agent", role, pid, id_=pid)  # noqa: E731
        arch = mk(Role.architect, f"architect.{E}")
        qa = mk(Role.qa, f"qa.{E}")
        adv = mk(Role.adversary, f"adversary.{E}")
        sme = mk(Role.sme, f"sme.{E}")
        doctor = mk(Role.doctor, "doctor")
        story = b.ticket_create(arch, kind=TicketKind.story, work_type=WorkType.feature, title="S1 ship sheet",
                                parent_id=E, description="build the ship selection sheet")
        eng = mk(Role.engineer, f"engineer.{story.id}")
        crit = b.criterion_create(arch, ticket_id=story.id, text="the sheet renders four ships", check=Check.command)
        design = b.doc_create(arch, doc_type=DocType.design, title="Ship sheet design", body_md="four ships on a grid",
                              scope=E)
        b.ticket_update(arch, story.id, design_ref=design.id)
        b.ticket_update(arch, story.id, status=TicketStatus.designed)
        b.ticket_update(owner, story.id, status=TicketStatus.signed_off)
        b.ticket_update(arch, story.id, status=TicketStatus.ready)
        b.ticket_update(arch, story.id, assignee=eng.id)
        b.ticket_update(eng, story.id, status=TicketStatus.in_progress)
        evidence = b.doc_create(eng, doc_type=DocType.report, title="Run output", body_md="4 ships rendered", scope=E)
        question = b.message_send(eng, ticket_id=story.id, to=arch.id, kind=MessageKind.question,
                                  text="grid or list for the ships?")

        def say(text):
            m = b.message_send(owner, ticket_id=E, to=None, kind=MessageKind.note, text=text)
            return b.requirement_mark(owner, message_id=m.id)
        self.X: dict[str, Any] = {
            "E": E, "S": story.id, "C": crit.id, "D": design.id, "EV": evidence.id, "Q": question.id,
            "A_cover": say("the sheet must show four ships").id, "A_not": say("make it feel great").id,
            "A_serve": say("also capture the renders").id,
            "eng": eng.id, "arch": arch.id, "qa": qa.id, "adv": adv.id, "sme": sme.id, "doctor": doctor.id,
            "tmp": str(tmp_path),
        }
        self.pid = {"owner": "owner", "architect": arch.id, "engineer": eng.id, "qa": qa.id, "adversary": adv.id,
                    "sme": sme.id, "doctor": "doctor"}
        self.topic = self.http.post("/v1/topics", json={"title": "Python testing", "tags": ["python"],
                                                        "seed_url": "https://skills.sh/"},
                                    headers=OWNER).json()
        if self.topic.get("ok"):
            self.X["T"] = self.topic["value"]["topic"]["id"]
            b.run_pending_pairings()
            self.pid["topic_sme"] = f"sme.{self.X['T']}"
        # a strategy the story uses, so ticket_read lists a layer doc
        strat = b.doc_create(sme, doc_type=DocType.strategy_ll, title="Web craft", body_md="- [required] measure at 1024px",
                             scope=E)
        b.link_create(arch, from_id=story.id, to_id=strat.id, relation="uses_strategy")
        # a finished epic for `close`, and the help thread the doctor seat owns (propose_fix)
        e2 = b.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="Old site")
        e2.status = TicketStatus.done
        b.store.put("ticket", e2)
        self.X["E2"] = e2.id
        from edp8 import help as help_mod
        asked = help_mod.ask(b, owner, "the board feels slow")
        self.X["H"] = asked["topic"]["id"]
        b.run_pending_pairings()
        self.pid["doctor"] = asked["seat"]["id"] if isinstance(asked["seat"], dict) and asked["seat"].get("id") else f"doctor.{self.X['H']}"
        # a seat transcript harvest_cost can find
        logs = tmp_path / "harvest-logs"
        logs.mkdir()
        whoami = {"ok": True, "value": {"participant": {"id": eng.id, "role": "engineer"}}}
        use = lambda ts, mid, tools: {"type": "assistant", "timestamp": ts, "message": {"id": mid, "content": [  # noqa: E731
            {"type": "tool_use", "name": n, "input": i} for n, i in tools], "usage": {
                "input_tokens": 10, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 1000, "output_tokens": 5}}}
        rows = [{"type": "user", "timestamp": "2026-09-24T09:59:00Z", "message": {"content": [
            {"type": "tool_result", "content": json.dumps(whoami)}]}},
            use("2026-09-24T10:01:00Z", "m1", [("Skill", {"skill": "harvest"})]),
            use("2026-09-24T10:03:00Z", "m2", [("mcp__edp8__close_self", {})])]
        (logs / "seat.jsonl").write_text(chr(10).join(json.dumps(r) for r in rows) + chr(10), encoding="utf-8")
        monkeypatch.setenv("EDP8_HARVEST_LOG_ROOTS", str(logs))

    def _token(self, pid: str) -> str:
        """The seat's own secret, as the board minted it when it spawned or paired the seat (header-only before)."""
        if pid == "owner":
            return OWNER_TOKEN
        agents = json.loads((self.tmp / "tokens.json").read_text(encoding="utf-8")).get("agents") or {}
        return str(agents.get(pid, ""))

    def call(self, role: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
        pid = self.pid[role]
        set_client(BoardClient(participant=pid, admin_token="t", client=self.http, token=self._token(pid),
                               workspace_root=self.tmp))
        return invoke(ALL_TOOLS[name], args, seat=pid)


class Row:
    def __init__(self, tool, role, args, grab=None, canned=""):
        self.tool, self.role, self.args, self.grab, self.canned = tool, role, args, grab, canned


def _g(key, path: Callable[[dict], Any]):
    return lambda out, X: X.__setitem__(key, path(out["value"]))


def _roles_holding(name):
    return sorted(r for r, tools in ROLE_BUNDLES.items() if name in tools)


# Order matters: a row may use ids an earlier row grabbed. `close`, `close_self` run last.
ROWS: list[Row] = [
    # --- identity
    Row("whoami", "engineer", lambda X: {}),
    Row("preflight", "engineer", lambda X: {}),
    Row("subscribe", "engineer", lambda X: {}),
    Row("context", "engineer", lambda X: {"ticket_id": X["S"]}, _g("cursor", lambda v: v.get("cursor"))),
    Row("context_delta", "engineer", lambda X: {"ticket_id": X["S"], "cursor": X["cursor"]}),
    Row("describe", "engineer", lambda X: {"type": "enums"}),
    Row("describe_objects", "engineer", lambda X: {}),
    Row("get_guide", "engineer", lambda X: {"name": "shared-host-rules"}),
    Row("resume_self", "engineer", lambda X: {}, canned="pool resume"),
    # --- tickets
    Row("ticket_create", "architect",
        lambda X: {"kind": "task", "work_type": "feature", "title": "T1 capture renders", "parent_id": X["S"],
                   "assignee": X["eng"], "serves": [X["A_serve"]]},
        _g("T1", lambda v: (v.get("ticket") or v)["id"])),
    Row("ticket_read", "engineer", lambda X: {"ticket_id": X["S"], "include": "children"}),
    Row("ticket_query", "architect", lambda X: {"epic_id": X["E"], "kind": "story"}),
    Row("ticket_update", "architect", lambda X: {"ticket_id": X["S"], "description": "build the ship selection sheet"}),
    # --- criteria
    Row("criterion_create", "architect", lambda X: {"ticket_id": X["S"], "text": "the sheet keeps four ships in a row",
                                                    "check": "look"}, _g("C2", lambda v: (v.get("criterion") or v)["id"])),
    Row("criterion_query", "engineer", lambda X: {"ticket_id": X["S"]}),
    Row("criterion_update", "engineer", lambda X: {"id": X["C"], "evidence_ref": X["EV"]}),
    # --- requirements (s-aa76c83998)
    Row("requirements", "architect", lambda X: {"epic": X["E"], "state": "open"}),
    Row("requirements", "qa", lambda X: {"epic": X["E"]}),
    Row("requirement_link", "architect", lambda X: {"id": X["A_cover"], "criterion": X["C"]}),
    # --- docs and links
    Row("doc_create", "architect", lambda X: {"doc_type": "design", "title": "Grid layout", "body_md": "ships sit on a 2x2 grid",
                                              "scope": X["E"]}, _g("D2", lambda v: (v.get("doc") or v)["id"])),
    Row("doc_read", "engineer", lambda X: {"id": X["D2"]}),
    Row("doc_query", "engineer", lambda X: {"scope": X["E"], "doc_type": "design"}),
    Row("doc_update", "architect", lambda X: {"id": X["D2"], "body_md": "ships sit on a 2x2 grid, 8px gap"}),
    Row("doc_edit", "architect", lambda X: {"id": X["D2"], "expected_version": 2,
                                            "edits": [{"old_text": "8px gap", "new_text": "12px gap"}]}),
    Row("link_create", "architect", lambda X: {"from_id": X["T1"], "to_id": X["D2"], "relation": "designed_by"},
        _g("L", lambda v: (v.get("link") or v)["id"])),
    Row("link_query", "architect", lambda X: {"from_id": X["T1"]}),
    Row("link_delete", "architect", lambda X: {"id": X["L"]}),
    # --- messages and gates
    Row("message_send", "architect", lambda X: {"ticket_id": X["S"], "kind": "answer", "to": X["eng"],
                                                "text": "a grid, two by two", "reply_to": X["Q"], "resolves": [X["Q"]]},
        _g("M", lambda v: (v.get("message") or v)["id"])),
    Row("message_query", "engineer", lambda X: {"ticket_id": X["S"], "kind": "answer"}),
    Row("message_read", "engineer", lambda X: {"id": X["M"]}),
    Row("inbox", "engineer", lambda X: {}),
    Row("gate_open", "engineer", lambda X: {"ticket_id": X["S"], "gate": "scope", "note": "four ships render"}),
    Row("gates", "owner", lambda X: {"ticket_id": X["S"]}),
    Row("gate_answer", "owner", lambda X: {"ticket_id": X["S"], "gate": "scope", "answer": "looks right"}),
    # --- records
    Row("record_decision", "architect", lambda X: {"scope": X["E"], "text": "ships render on a 2x2 grid",
                                                   "detail": "the owner picked it over a list"},
        _g("DEC", lambda v: (v.get("decision") or v)["id"])),
    Row("set_binding", "architect", lambda X: {"decision_id": X["DEC"], "binding": True, "reason": "the owner ruled"}),
    Row("record_claim", "engineer", lambda X: {"scope": X["S"], "text": "the grid fits 1280px", "basis": "measured",
                                               "evidence": [X["EV"]]}, _g("CLM", lambda v: (v.get("claim") or v)["id"])),
    Row("withdraw_claim", "architect", lambda X: {"claim_id": X["CLM"], "reason": "re-measured at 1024px"}),
    Row("record_lesson", "engineer", lambda X: {"domain": "web", "topic": "grids", "text": "measure the grid at 1024px too",
                                                "ticket_id": X["S"]}, _g("LES", lambda v: (v.get("lesson") or v)["id"])),
    Row("retire_lesson", "architect", lambda X: {"lesson_id": X["LES"], "reason": "folded into the web craft"}),
    Row("withdraw_decision", "engineer", lambda X: {"decision_id": X["DEC"], "reason": "superseded by the list layout"}),
    Row("lookup", "engineer", lambda X: {"scope": X["E"], "question": "which layout did the owner pick for the ships"}),
    Row("dense_search", "architect", lambda X: {"scope": X["E"], "question": "ship grid layout", "k": 3}),
    Row("find", "architect", lambda X: {"query": "ship sheet", "k": 5, "epic_id": X["E"]}),
    # --- artifacts
    Row("artifact_create", "engineer", lambda X: {"form": "url", "uri": "https://example.com/preview", "note": "preview",
                                                  "ticket_id": X["S"]}, _g("ART", lambda v: (v.get("artifact") or v)["id"])),
    Row("artifact_read", "engineer", lambda X: {"id": X["ART"]}),
    Row("artifact_upload", "engineer", lambda X: {"path": X["upload"], "note": "run log"}),
    # --- board, people, events, sessions
    Row("board", "owner", lambda X: {"epic_id": X["E"]}),
    Row("participants", "architect", lambda X: {"role": "engineer", "type": "agent"}),
    Row("events_query", "architect", lambda X: {"subject_id": X["S"], "limit": 5}),
    Row("session_query", "owner", lambda X: {"ticket_id": X["S"]}),
    # --- pool (canned)
    Row("spawn", "owner", lambda X: {"role": "engineer", "ticket_id": X["S"], "steer": "start with the tests"}, canned="pool spawn"),
    Row("resume", "owner", lambda X: {"participant_id": X["eng"]}, canned="pool resume"),
    Row("reap", "owner", lambda X: {"participant_id": X["eng"]}, canned="pool reap"),
    # --- pain
    Row("pain", "engineer", lambda X: {"action": "file", "severity": "low", "area": "get_guide",
                                       "symptom": "the index lists a guide twice", "expected": "once",
                                       "evidence": "get_guide() output, 2026-10-02"}, _g("PAIN", lambda v: v["id"])),
    Row("pain", "engineer", lambda X: {"action": "query", "q": "guide"}),
    Row("pain", "engineer", lambda X: {"action": "read", "id": X["PAIN"]}),
    Row("pain", "owner", lambda X: {"action": "resolve", "id": X["PAIN"], "status": "invalid",
                                  "note": "could not reproduce"}),
    # --- framework (owner)
    Row("workflow", "owner", lambda X: {"action": "list"}, _g("WF", lambda v: ((v.get("workflows") if isinstance(v, dict) else v) or [{}])[0].get("ref") or "standard@1")),
    Row("workflow", "owner", lambda X: {"action": "read", "ref": X["WF"]}),
    Row("teammate", "owner", lambda X: {"action": "list"}),
    Row("service_status", "owner", lambda X: {}),
    Row("harvest_cost", "owner", lambda X: {"participant_id": X["eng"]}),
    # --- doctor
    Row("doctor_health", "doctor", lambda X: {}),
    Row("doctor_pool", "doctor", lambda X: {}),
    Row("doctor_feed_lag", "doctor", lambda X: {}),
    Row("doctor_dead_mail", "doctor", lambda X: {}),
    Row("doctor_pains", "doctor", lambda X: {}),
    Row("doctor_logs", "doctor", lambda X: {"service": "board", "lines": 20}),
    Row("why_stuck", "doctor", lambda X: {"ticket_id": X["S"]}),
    Row("workflow_check", "doctor", lambda X: {"ref": "standard@1"}),
    Row("propose_fix", "doctor", lambda X: {"topic_id": X["H"], "action": {"kind": "service.restart", "service": "board"},
                                            "effect": "restarts the board service"}),
    # --- topic seat (canned fetch)
    Row("topic_research", "topic_sme", lambda X: {"topic_id": X["T"], "query": "python testing"}, canned="page fetch"),
    Row("topic_research", "topic_sme", lambda X: {"topic_id": X["T"], "url": "https://skills.sh/a/b/c"}, canned="page fetch"),
    Row("topic_propose", "topic_sme", lambda X: {"topic_id": X["T"], "title": "Python testing: AAA",
                                                 "body_md": "- [required] tests follow Arrange-Act-Assert",
                                                 "source_url": "https://skills.sh/a/b/c"}),
    # --- close (last: they end the seats / the epic)
    Row("record_status", "adversary", lambda X: {"status": "done", "note": "nothing to review yet"}),
    Row("close_self", "adversary", lambda X: {}, canned="pool release_self"),
    Row("close", "owner", lambda X: {"epic_id": X["E2"]}, canned="epic E2 set to done in the store"),
]


@pytest.fixture
def matrix(monkeypatch, tmp_path):
    w = World(monkeypatch, tmp_path)
    up = Path(w.X["tmp"]) / "run.log"
    up.write_text("4 ships rendered\n", encoding="utf-8")
    w.X["upload"] = str(up)
    if "T" not in w.X:  # the topic could not be created: its rows report that, the rest still run
        w.X["T"] = "topic-missing"
    help_topic = w.http.get("/v1/help", headers={"X-Participant": "doctor"}).json() if False else None
    rows: list[dict[str, Any]] = []
    for r in ROWS:
        try:
            args = r.args(w.X)
        except KeyError as e:  # an earlier row did not yield the id this one needs
            args = {}
            out = {"ok": False, "error": {"code": "dependency", "message": f"needs {e} from an earlier row"}}
        else:
            role = r.role if r.role in w.pid else "owner"
            out = w.call(role, r.tool, args)
        if out.get("ok") and r.grab:
            try:
                r.grab(out, w.X)
            except Exception as e:  # a grab failure is its own finding, not a crash of the module
                out = {"ok": False, "error": {"code": "grab", "message": f"{type(e).__name__}: {e}"}}
        tool = ALL_TOOLS[r.tool]
        props = tool.input_schema.get("properties", {})
        rows.append({
            "tool": r.tool, "role": r.role, "args": args, "ok": bool(out.get("ok")), "canned": r.canned,
            "result": json.dumps(out.get("value") if out.get("ok") else out.get("error"), default=str)[:120],
            "roles_holding": _roles_holding(r.tool), "role_holds_tool": r.role in _roles_holding(r.tool)
            or (r.role == "topic_sme" and "sme" in _roles_holding(r.tool)),
            "args_without_description": sorted(k for k, v in props.items() if not v.get("description")
                                               and k != "idempotency_key"),
        })
    dest = os.environ.get("EDP_S9_MATRIX")
    if dest:
        Path(dest).write_text(json.dumps(rows, indent=1, default=str), encoding="utf-8")
    return rows


def test_the_table_covers_every_tool():
    assert {r.tool for r in ROWS} == set(ALL_TOOLS)


def test_every_realistic_call_succeeds(matrix):
    failed = [(r["tool"], r["role"], r["result"]) for r in matrix if not r["ok"]]
    assert not failed, failed


# FINDING (S9 audit): these two tools are registered in ALL_TOOLS but sit in no role's bundle, so no seat can call them.
# The audit calls them as an architect to prove they work; when a bundle takes them, delete them from this set.
UNBUNDLED = {"dense_search", "withdraw_claim"}


def test_the_calling_role_holds_the_tool(matrix):
    odd = [(r["tool"], r["role"], r["roles_holding"]) for r in matrix if not r["role_holds_tool"] and r["tool"] not in UNBUNDLED]
    assert not odd, odd


def test_the_unbundled_set_is_exact():
    assert {n for n in ALL_TOOLS if not _roles_holding(n)} == UNBUNDLED


# ----------------------------------------------------------------------------- failing calls name the fix
_TOOLS = sorted(ALL_TOOLS)


def _fail(name, args):
    out = invoke(ALL_TOOLS[name], args, seat="s9-probe")
    assert out["ok"] is False and out["error"]["code"] == "schema", (name, out)
    return out


@pytest.mark.parametrize("name", _TOOLS)
def test_an_unknown_arg_names_the_accepted_args(name):
    out = _fail(name, {"zz_not_an_arg": 1})
    err = out["error"]
    assert "zz_not_an_arg" in err["message"] and err["accepted"] == accepted_args(ALL_TOOLS[name].args_model)


@pytest.mark.parametrize("name", [n for n in _TOOLS if any(f.is_required() for f in ALL_TOOLS[n].args_model.model_fields.values())])
def test_a_missing_required_arg_names_it_and_the_required_list(name):
    tool = ALL_TOOLS[name]
    required = [k for k, f in tool.args_model.model_fields.items() if f.is_required()]
    out = _fail(name, {})
    assert set(out["error"]["missing"]) == set(required)
    assert all(k in out["hint"] for k in required) and out["error"]["accepted"] == accepted_args(tool.args_model)


def _valid_required(tool):
    """A well-typed value for every required arg, so the one bad enum is the only error."""
    props = tool.input_schema.get("properties", {})
    out: dict[str, Any] = {}
    for k, f in tool.args_model.model_fields.items():
        if not f.is_required():
            continue
        node = props[k]
        kind = node.get("type")
        out[k] = (node["enum"][0] if node.get("enum") else {"integer": 1, "boolean": True, "array": [], "object": {}}.get(kind, "x"))
    return out


def _enum_cases():
    for n in _TOOLS:
        for field, values in enum_fields(ALL_TOOLS[n].args_model).items():
            yield n, field, values


@pytest.mark.parametrize("name,field,values", list(_enum_cases()))
def test_a_bad_enum_value_names_the_accepted_values(name, field, values):
    tool = ALL_TOOLS[name]
    out = _fail(name, {**_valid_required(tool), field: "zz_not_a_value"})
    assert out["error"]["field"] == field and out["error"]["allowed"] == values
    assert all(v in out["hint"] for v in values)


def test_matrix_is_json_serialisable(matrix):
    json.dumps(matrix, default=str)


# ----------------------------------------------------------------------------- action tools refuse before the board
class _NoBoard:
    participant = "probe"

    def __getattr__(self, name):
        raise AssertionError(f"reached the board: {name}")


@pytest.mark.parametrize("name,args,missing", [
    ("pain", {"action": "file"}, ["severity", "area", "symptom", "expected", "evidence"]),
    ("pain", {"action": "read"}, ["id"]),
    ("pain", {"action": "resolve"}, ["id", "status"]),
    ("workflow", {"action": "read"}, ["ref"]),
    ("workflow", {"action": "duplicate"}, ["ref"]),
    ("teammate", {"action": "create"}, ["handle"]),
])
def test_an_action_tool_names_the_args_its_action_needs(name, args, missing):
    set_client(_NoBoard())
    out = invoke(ALL_TOOLS[name], args, seat="s9-probe")
    assert out["ok"] is False and out["error"]["missing"] == missing
    assert all(m in out["hint"] for m in missing) and f"describe('{name}')" in out["hint"]
