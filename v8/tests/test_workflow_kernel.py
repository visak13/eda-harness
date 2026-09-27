"""S13 (s-461403ebd1, design-e963c656f5 §4.14(d)-(e)): capacity, cards, kernel and invariants as data.

- c-2c02d34d7f: every role declares its capacity; a spawn carries the pinned role's class and cap to the
  pool; a card edited in a new version reaches only epics pinned to it (a running epic's seat keeps the
  old card); the /epic and /ticket lifecycle is rendered from the pinned workflow;
- c-328185ac06: a custom role whose card and bundle omit the kernel still gets both; publish refuses on
  each invariant with what is wrong, why it matters and the fix; definitions carry schema_version with
  forward migrations and check_compat();
- c-0e2611c3f2 (API half): the REST workflow surface, a published version is immutable (PUT refused).
Board + Store(':memory:') directly, and the service through TestClient.
"""
from __future__ import annotations

import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

from edp8 import workflow as wf
from edp8.board import Board
from edp8.bundles import tools_for_role
from edp8.schemas import Role, TicketKind, WorkType
from edp8.service import create_app
from edp8.store import Store


class _Pool:
    def __init__(self):
        self.spawned: list[tuple[str, str, dict]] = []

    def spawn(self, role, pid, **kw):
        self.spawned.append((role, pid, kw))
        return {"ok": True}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_AGENT_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def board(home):
    return Board(Store(":memory:"), pool=_Pool(), free_mb=lambda: 10_000)


@pytest.fixture
def owner(board):
    board.participant_create("agent", Role.architect, "arch", id_="arch")
    return board.participant_create("human", Role.owner, "owner", id_="owner")


def _crew(board, *, version_card: str = "You design the screens.", new_id: str | None = "crew") -> dict:
    """Standard + a custom `designer` role whose card and bundle leave the kernel out."""
    d = wf.dump(board.workflows.duplicate("standard@1", new_id=new_id, by="owner"))
    d["roles"].append({"id": "designer", "card_md": version_card, "bundle": ["ticket_read"],
                       "spawnable": True, "capacity_class": "planner", "max_concurrent": 2})
    for r in d["roles"]:
        if r["id"] == "architect":
            r["may_spawn"] = sorted(set(r["may_spawn"]) | {"designer"})
    return d


def _publish(board, d: dict) -> str:
    board.workflows.save(d, by="owner")
    return board.workflows.publish(d["id"], d["version"], by="owner").ref


def _epic(board, owner, workflow=None):
    return board.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="E", workflow=workflow)


# ---- c-2c02d34d7f ------------------------------------------------------------------------------

def test_every_preset_role_declares_its_capacity():
    for build in wf.BUILTIN_BUILDERS.values():
        for r in build().roles:
            if r.spawnable:
                assert r.capacity_class or r.max_concurrent, (r.id, "declares no capacity")
    std = wf.Workflow(wf.build_standard())
    assert {r: std.capacity(r)["capacity_class"] for r in ("engineer", "sme", "architect", "qa", "adversary")} == {
        "engineer": "builder", "sme": "builder", "architect": "planner", "qa": "checker", "adversary": "checker"}


def test_a_spawn_carries_the_pinned_roles_class_and_cap_to_the_pool(board, owner):
    ref = _publish(board, _crew(board))
    crew, std = _epic(board, owner, ref), _epic(board, owner)
    assert board.seat_spawn_spec(crew.id, "designer")["capacity"] == {"capacity_class": "planner",
                                                                      "max_concurrent": 2}
    assert board.seat_spawn_spec(std.id, "engineer")["capacity"] == {"capacity_class": "builder",
                                                                     "max_concurrent": None}


def test_the_pairing_spawn_passes_the_pinned_capacity_and_card(board, owner):
    ref = _publish(board, _crew(board))
    epic = _epic(board, owner, ref)
    assert board._spawn_seat("designer", f"designer.{epic.id}", epic.id) is True
    role, pid, kw = board._pool_adapter().spawned[-1]
    assert (role, kw["capacity_class"], kw["max_concurrent"]) == ("designer", "planner", 2)
    assert kw["env"]["EDP_CARD"] == wf.card_name("crew", 1, "designer")  # S11 F6: prefix + hash
    assert kw["env"]["EDP_CARD"].startswith("wf-crew-1-designer-")
    std = _epic(board, owner)
    assert board._spawn_seat("qa", f"qa.{std.id}", std.id) is True
    _, _, kw = board._pool_adapter().spawned[-1]
    assert kw["capacity_class"] == "checker" and "EDP_CARD" not in (kw.get("env") or {})


def test_a_card_edit_in_a_new_version_reaches_only_new_epics(board, owner, home):
    v1 = _publish(board, _crew(board, version_card="Card v1: sketch first."))
    running = _epic(board, owner, v1)
    d2 = wf.dump(board.workflows.duplicate(v1, by="owner"))  # crew@2, a draft
    next(r for r in d2["roles"] if r["id"] == "designer")["card_md"] = "Card v2: prototype first."
    v2 = _publish(board, d2)
    fresh = _epic(board, owner, v2)
    old = board.seat_spawn_spec(running.id, "designer")["env"]["EDP_CARD"]
    new = board.seat_spawn_spec(fresh.id, "designer")["env"]["EDP_CARD"]
    assert (old, new) == (wf.card_name("crew", 1, "designer"), wf.card_name("crew", 2, "designer"))
    cmd = home / ".claude" / "commands"
    assert "Card v1" in (cmd / f"{old}.md").read_text(encoding="utf-8")
    assert "Card v2" in (cmd / f"{new}.md").read_text(encoding="utf-8")
    assert "Card v2" not in (cmd / f"{old}.md").read_text(encoding="utf-8")  # the running epic keeps its card
    # a Standard seat boots its shipped card: no env, nothing written (golden)
    assert board.seat_spawn_spec(_epic(board, owner).id, "engineer")["env"] == {}
    assert sorted(p.name for p in cmd.iterdir()) == [f"{old}.md", f"{new}.md"]


def test_the_lifecycle_is_rendered_from_the_pinned_workflow(board, owner):
    std = _epic(board, owner)
    lean = _epic(board, owner, "lean")
    std_md = board.ticket_view(std.id, include=["lifecycle"])["lifecycle"]
    lean_md = board.ticket_view(lean.id, include=["lifecycle"])["lifecycle"]
    assert "workflow standard@1" in std_md and "workflow lean@1" in lean_md
    assert "| drafted | designed | *board* |" in std_md
    assert "| designed | signed_off | owner, architect |" in std_md
    assert "| designed | signed_off | owner |" in lean_md  # Lean has no architect
    assert "**qa**" in std_md
    assert "lifecycle" not in board.ticket_view(std.id)  # opt-in: context stays the same size
    assert board.ticket_view(lean.id)["workflow"] == "lean@1"  # the pin, from the table


# ---- c-328185ac06: kernel ----------------------------------------------------------------------

def test_a_custom_role_without_the_kernel_still_boots_with_it(board, owner, home):
    ref = _publish(board, _crew(board, version_card="Only role text here."))
    epic = _epic(board, owner, ref)
    w = board.workflow_of(epic)
    assert set(wf.KERNEL_TOOLS) <= set(w.bundle("designer")) and "ticket_read" in w.bundle("designer")
    name = board.seat_spawn_spec(epic.id, "designer")["env"]["EDP_CARD"]
    text = (home / ".claude" / "commands" / f"{name}.md").read_text(encoding="utf-8")
    assert text.startswith(wf.KERNEL_PREAMBLE) and text.endswith("Only role text here.")
    # the MCP server serves an unknown (custom) role the kernel tools
    assert set(wf.KERNEL_TOOLS) <= {t.name for t in tools_for_role("designer")}
    # Standard bundles already hold the kernel: unchanged (golden)
    std = board.workflow_of(None)
    from edp8.bundles import ROLE_BUNDLES
    for r in ("engineer", "architect", "qa", "adversary", "sme"):
        assert std.bundle(r) == ROLE_BUNDLES[r]


# ---- c-328185ac06: one test per publish invariant ----------------------------------------------

def _refused(board, d: dict, code: str) -> dict:
    board.workflows.save(d, by="owner")
    with pytest.raises(wf.WorkflowError) as ei:
        board.workflows.publish(d["id"], d["version"], by="owner")
    e = ei.value
    assert e.code == "invalid"
    p = next(x for x in e.problems if x["code"] == code)
    assert p["message"] and p["why"] and p["fix"] and p["docs"]  # what, why, fix, docs
    assert code in e.message and p["why"] in e.message and p["fix"] in e.message
    return p


def test_invariant_unreachable_and_dead_end_status(board):
    d = wf.dump(board.workflows.duplicate("standard@1", new_id="dead", by="owner"))
    d["transitions"] = [t for t in d["transitions"] if not (t["from"] == "in_review")]
    assert "in_review" in _refused(board, d, "dead_end_status")["message"]
    d2 = wf.dump(board.workflows.duplicate("standard@1", new_id="unreach", by="owner"))
    d2["transitions"] = [t for t in d2["transitions"] if t["to"] != "partial"]
    assert "partial" in _refused(board, d2, "unreachable_status")["message"]


def test_invariant_kind_without_a_non_doer_checker(board):
    d = wf.dump(board.workflows.duplicate("standard@1", new_id="selfcheck", by="owner"))
    d["checkers"] = [{"role": "engineer"}]
    assert "builder" in _refused(board, d, "checker_is_doer")["message"]
    d2 = wf.dump(board.workflows.duplicate("standard@1", new_id="nochecker", by="owner"))
    d2["checkers"] = [{"when": {"kinds": ["epic"]}, "role": "qa"}]
    _refused(board, d2, "kind_without_checker")


def test_invariant_role_without_a_spawner(board):
    d = _crew(board, new_id="orphan")
    for r in d["roles"]:
        r["may_spawn"] = [x for x in r.get("may_spawn", []) if x != "designer"]
    assert "designer" in _refused(board, d, "role_without_spawner")["message"]


def test_invariant_a_gate_no_human_can_answer(board):
    d = wf.dump(board.workflows.duplicate("standard@1", new_id="nohuman", by="owner"))
    next(g for g in d["gates"] if g["id"] == "poc")["answerers"] = ["qa"]
    assert "poc" in _refused(board, d, "gate_unanswerable")["message"]


def test_invariant_self_approval(board):
    d = wf.dump(board.workflows.duplicate("standard@1", new_id="selfok", by="owner"))
    g = next(g for g in d["gates"] if g["id"] == "demo")
    g["requires"].append({"check": "role_in", "params": {"roles": ["owner"]}, "phase": "open"})
    assert "demo" in _refused(board, d, "self_approval")["message"]


def test_invariant_caps_at_least_one(board):
    d = wf.dump(board.workflows.duplicate("standard@1", new_id="zerocap", by="owner"))
    d["caps"]["stories_per_epic"] = 0
    assert "stories_per_epic" in _refused(board, d, "cap_below_1")["message"]
    d2 = _crew(board, new_id="zerorole")
    next(r for r in d2["roles"] if r["id"] == "designer")["max_concurrent"] = 0
    _refused(board, d2, "cap_below_1")


def test_invariant_the_kernel_is_intact(board):
    d = _crew(board, new_id="nokernel")
    next(r for r in d["roles"] if r["id"] == "designer")["kernel"] = False
    assert "designer" in _refused(board, d, "kernel_stripped")["message"]


# ---- c-328185ac06: schema_version, migrations, check_compat ------------------------------------

def test_schema_version_migrates_forward_and_check_compat_uses_a_scratch_copy(board, monkeypatch):
    ref = _publish(board, _crew(board))
    assert wf.dump(board.workflows.get("crew", 1))["schema_version"] == wf.SCHEMA_VERSION
    assert wf.check_compat(board.workflows)["ok"] is True
    before = board.store._conn.execute("SELECT body FROM workflow_defs").fetchall()

    # an app update ships schema 2 whose migration renames the designer's card text
    def to_v2(body):
        for r in body["roles"]:
            if r["id"] == "designer":
                r["card_md"] = r["card_md"] + " (migrated)"
        return body
    monkeypatch.setattr(wf, "SCHEMA_VERSION", 2)
    monkeypatch.setattr(wf, "MIGRATIONS", {1: to_v2})
    board.workflows._resolved.clear()
    report = wf.check_compat(board.workflows)
    assert report == {"ok": True, "schema_version": 2, "report": [{"ref": ref, "ok": True, "problems": []}]}
    assert board.workflows.get("crew", 1).roles[-1].card_md.endswith("(migrated)")  # read through the chain
    assert board.store._conn.execute("SELECT body FROM workflow_defs").fetchall() == before  # nothing written

    # a broken migration: the check fails per workflow and still changes nothing
    monkeypatch.setattr(wf, "MIGRATIONS", {1: lambda body: {**body, "caps": {**body["caps"], "tasks_per_story": 0}}})
    bad = wf.check_compat(board.workflows)
    assert bad["ok"] is False and bad["report"][0]["ref"] == ref
    assert bad["report"][0]["problems"][0]["code"] == "cap_below_1"
    assert board.store._conn.execute("SELECT body FROM workflow_defs").fetchall() == before


def test_a_definition_from_a_newer_app_is_refused_by_name(board):
    d = _crew(board, new_id="future")
    d["schema_version"] = wf.SCHEMA_VERSION + 1
    assert [p["code"] for p in wf.validate(d)] == ["schema_version"]
    with pytest.raises(wf.WorkflowError, match="newer than this app"):
        board.workflows.save(d, by="owner")


# ---- the REST surface (c-0e2611c3f2: a published version is immutable) --------------------------

def test_the_workflow_api(home):
    board = Board(Store(":memory:"), pool=_Pool(), free_mb=lambda: 10_000)
    c = TestClient(create_app(board, admin_token="t"))
    for pid, role, typ in (("owner", "owner", "human"), ("eng", "engineer", "agent")):
        assert c.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                      headers={"X-Admin": "t"}).json()["ok"]
    O, E = {"X-Participant": "owner"}, {"X-Participant": "eng"}
    listed = c.get("/v1/workflows", headers=E).json()["value"]
    assert {(x["id"], x["builtin"]) for x in listed} >= {("standard", True), ("lean", True), ("solo", True)}
    std = c.get("/v1/workflows/standard@1", headers=E).json()["value"]
    assert std["published"] and [p for p in std["problems"] if p["severity"] == "error"] == []
    assert c.get("/v1/workflows/nope@1", headers=E).status_code == 404
    # only the owner or an architect edits
    assert c.post("/v1/workflows/duplicate", json={"ref": "standard@1", "new_id": "t"}, headers=E).status_code == 400
    draft = c.post("/v1/workflows/duplicate", json={"ref": "standard@1", "new_id": "team"}, headers=O).json()
    assert draft["ok"] and draft["value"]["published"] is False
    body = draft["value"]
    body["caps"]["stories_per_epic"] = 3
    assert c.put("/v1/workflows", json=body, headers=O).json()["ok"]
    bad = {**body, "caps": {**body["caps"], "tasks_per_story": 0}}
    v = c.post("/v1/workflows/validate", json=bad, headers=E).json()["value"]
    errs = [p for p in v["problems"] if p["severity"] == "error"]
    assert v["valid"] is False and [p["code"] for p in errs] == ["cap_below_1"] and errs[0]["fix"]
    pub = c.post("/v1/workflows/team@1/publish", headers=O)
    assert pub.json()["ok"] and pub.json()["value"]["published"] is True
    put = c.put("/v1/workflows", json=body, headers=O)  # published → immutable
    assert put.status_code == 409 and put.json()["error"]["code"] == "immutable"
    assert c.put("/v1/workflows", json={**body, "id": "standard"}, headers=O).status_code == 409  # built in
    lc = c.get("/v1/workflows/team@1/lifecycle?kind=story", headers=E).json()["value"]
    assert "workflow team@1" in lc["markdown"]
    epic = c.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "E", "workflow": "team"},
                  headers=O).json()["value"]
    got = c.get(f"/v1/tickets/{epic['id']}", headers=E).json()["value"]
    assert got["workflow"] == "team@1" and not any(tag.startswith("workflow:") for tag in got.get("tags") or [])
    who = c.get("/v1/whoami", headers=E).json()["value"]
    assert who["workflow"] == "standard@1" and set(wf.KERNEL_TOOLS) <= set(who["bundle"])


# ---- the update gate's CLI (steer m-f0835edaca): `heronry workflows check --db <path> --json` -----

def test_workflows_check_cli_names_a_new_invariant_and_never_writes_the_db(tmp_path, capsys, monkeypatch):
    import json
    import sqlite3

    from edp8.workflows_cli import main as workflows_main  # S3's cli.py: "workflows" → this main
    main = lambda argv: workflows_main(argv[1:])  # noqa: E731 - argv here includes the word `workflows`
    monkeypatch.setenv("EDP_AGENT_HOME", str(tmp_path))
    db = tmp_path / "live.db"
    board = Board(Store(str(db)), pool=_Pool(), free_mb=lambda: 10_000)
    board.participant_create("human", Role.owner, "owner", id_="owner")
    good = _publish(board, _crew(board, new_id="good"))
    _epic(board, board.participant("owner"), good)
    # a version published before a newer kernel invariant existed: written straight to the table
    bad = _crew(board, new_id="older")
    next(r for r in bad["roles"] if r["id"] == "designer")["kernel"] = False
    board.workflows._put(wf.WorkflowDef.model_validate({**bad, "published": True}), "test")
    board.store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    board.store._conn.close()
    before = db.read_bytes()

    assert main(["workflows", "check", "--db", str(db), "--json"]) == 1
    rows = json.loads(capsys.readouterr().out)
    by = {(r["workflow"], r["version"]): r for r in rows}
    assert by[("good", 1)] == {"workflow": "good", "version": 1, "ok": True, "errors": []}
    assert by[("older", 1)]["ok"] is False and by[("older", 1)]["errors"][0].startswith("kernel_stripped:")
    assert "why:" in by[("older", 1)]["errors"][0] and "fix:" in by[("older", 1)]["errors"][0]
    assert db.read_bytes() == before  # the live DB is never written
    assert sqlite3.connect(db).execute("SELECT count(*) FROM workflow_defs").fetchone()[0] == 2

    # all ok → exit 0; usage errors → exit 2
    with sqlite3.connect(db) as c:
        c.execute("DELETE FROM workflow_defs WHERE id='older'")
    assert main(["workflows", "check", "--db", str(db), "--json"]) == 0
    capsys.readouterr()
    assert main(["workflows", "check"]) == 2
    assert main(["workflows", "check", "--db", str(tmp_path / "nope.db")]) == 2
    assert main(["workflows"]) == 2
