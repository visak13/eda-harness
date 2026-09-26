"""S14 (s-42a72db3dd, design-e963c656f5 §4.14(c)-(e)): the server half of the Design tab.

- c-e9d095f3a3: custom roles — Validate refuses a role with no card, no bundle or no spawner, and a
  self-checking or escalating permission set; a custom role's seat is served the bundle its pinned version
  declares (clipped by its permissions, kernel tools always included);
- c-faeeb32860: role templates, the dry run (a synthetic epic on a throwaway board; a stall names the step
  and blocks Publish), the diff against the source version, and "upstream changed" with a three-way merge
  into a new draft (including Standard@N → Standard@N+1);
- c-4e99b1d4d7 (API half): the list carries pins, editing is admin-only, a non-admin reads.
Board + Store(':memory:') directly, and the service through TestClient.
"""
from __future__ import annotations

import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

from edp8 import mcp_server
from edp8 import workflow as wf
from edp8 import workflow_design as wd
from edp8.board import Board
from edp8.schemas import Role, TicketKind, WorkType
from edp8.service import create_app
from edp8.store import Store


class _Pool:
    def __init__(self):
        self.spawned: list[tuple[str, str]] = []

    def spawn(self, role, pid, **_):
        self.spawned.append((role, pid))
        return {"ok": True}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_AGENT_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def board(home):
    b = Board(Store(":memory:"), pool=_Pool(), free_mb=lambda: 10_000)
    b.participant_create("human", Role.owner, "owner", id_="owner")
    return b


def _draft(board, new_id="crew") -> dict:
    return wf.dump(board.workflows.duplicate("standard@1", new_id=new_id, by="owner"))


def _designer(**over) -> dict:
    return {"id": "designer", "card_md": "You design the screens.", "bundle": ["ticket_read", "doc_create"],
            "spawnable": True, "capacity_class": "planner", **over}


def _with_role(d: dict, role: dict, spawner: str | None = "architect") -> dict:
    d["roles"].append(role)
    for r in d["roles"]:
        if r["id"] == spawner:
            r["may_spawn"] = sorted(set(r["may_spawn"]) | {role["id"]})
    return d


def _codes(d, severity="error") -> list[str]:
    return [p["code"] for p in wf.validate(d) if p["severity"] == severity]


# ---- c-e9d095f3a3: Validate on custom roles -------------------------------------------------------

def test_presets_have_no_custom_role_errors():
    for build in wf.BUILTIN_BUILDERS.values():
        assert _codes(build()) == []


def test_a_custom_role_needs_a_card_a_bundle_and_a_spawner(board):
    assert _codes(_with_role(_draft(board), _designer())) == []
    assert "card_missing" in _codes(_with_role(_draft(board, "a"), _designer(card_md="")))
    assert "bundle_missing" in _codes(_with_role(_draft(board, "b"), _designer(bundle=[])))
    assert "role_without_spawner" in _codes(_with_role(_draft(board, "c"), _designer(), spawner=None))


def test_self_checking_and_escalating_permission_sets_are_refused(board):
    selfie = _with_role(_draft(board), _designer(criterion_checker=True, criterion_author=True))
    assert "self_check" in _codes(selfie)
    builder_checker = _with_role(_draft(board, "b2"), _designer(criterion_checker=True, capacity_class="builder"))
    assert "self_check" in _codes(builder_checker)
    gatekeeper = _with_role(_draft(board, "g"), _designer(gate_answerer=True))
    assert "escalation" in _codes(gatekeeper)
    spawner = _with_role(_draft(board, "s"), _designer(bundle=["ticket_read", "spawn"]))
    probs = [p for p in wf.validate(spawner) if p["code"] == "escalation"]
    assert probs and "spawn" in probs[0]["message"] and probs[0]["why"] and probs[0]["fix"]
    # a tool the board would refuse anyway is a warning, not an error
    dead = _with_role(_draft(board, "d"), _designer(bundle=["ticket_read", "criterion_create"]))
    assert "unusable_tool" in _codes(dead, "warning") and "unusable_tool" not in _codes(dead)


def test_a_custom_roles_bundle_is_clipped_by_its_permissions_and_keeps_the_kernel(board):
    d = _with_role(_draft(board), _designer(bundle=["ticket_read", "spawn", "criterion_create", "doc_create"]))
    w = wf.Workflow(wf.WorkflowDef.model_validate(d))
    got = w.bundle("designer")
    assert "spawn" not in got and "criterion_create" not in got  # no may_spawn, not a criterion author
    assert {"ticket_read", "doc_create"} <= set(got) and set(wf.KERNEL_TOOLS) <= set(got)
    # a built-in role's shipped bundle is left as it is (the adversary keeps criterion_create)
    adversary = next(r for r in wf.build_standard().roles if r.id == "adversary")
    assert set(w.bundle("adversary")) == set(adversary.bundle or []) | set(wf.KERNEL_TOOLS)


def test_the_proxy_serves_a_custom_role_its_declared_bundle_never_more():
    declared = ["ticket_read", "doc_create", *wf.KERNEL_TOOLS]
    got = mcp_server.allowed_tool_names(mcp_server.CUSTOM_PATH, "designer", declared)
    assert {"ticket_read", "doc_create"} <= got and set(wf.KERNEL_TOOLS) <= got
    assert "spawn" not in got and "gate_answer" not in got
    # without a declared bundle (whoami failed to say) it is the identity + kernel tools only
    bare = mcp_server.allowed_tool_names(mcp_server.CUSTOM_PATH, "designer", None)
    assert set(wf.KERNEL_TOOLS) <= bare and "doc_create" not in bare
    # built-in roles are unchanged: the intersection of the path's and the caller's bundles
    assert mcp_server.allowed_tool_names("engineer", "engineer") == {
        t.name for t in mcp_server.tools_for_role("engineer")}
    assert mcp_server.allowed_tool_names("engineer", "expert") == set()


def test_a_custom_role_seat_spawns_and_boots_with_its_card(board, home):
    d = _with_role(_draft(board), _designer())
    board.workflows.save(d, by="owner")
    ref = board.workflows.publish("crew", 1, by="owner").ref
    epic = board.ticket_create(board.participant("owner"), kind=TicketKind.epic, work_type=WorkType.feature,
                               title="E", workflow=ref)
    assert "designer" in board.workflow_of(epic).spawnable
    spec = board.seat_spawn_spec(epic.id, "designer")
    card = home / ".claude" / "commands" / f"{spec['env']['EDP_CARD']}.md"
    assert card.read_text(encoding="utf-8").endswith("You design the screens.")
    assert spec["capacity"]["capacity_class"] == "planner"


# ---- c-faeeb32860: templates, dry run, diff, upstream merge ---------------------------------------

def test_role_templates_validate_once_spawned(board):
    for name in wd.ROLE_TEMPLATES:
        role = wd.role_from_template(name, f"my-{name}")
        d = _with_role(_draft(board, f"t-{name}"), role)
        assert [c for c in _codes(d) if c not in ("self_check",)] == [], name


@pytest.mark.parametrize("preset", sorted(wf.BUILTIN_BUILDERS))
def test_every_preset_dry_runs_to_done(preset, home):
    run = wd.dry_run(wf.BUILTIN_BUILDERS[preset]())
    assert run["ok"] and run["stall"] is None
    kinds = [e["kind"] for e in run["timeline"]]
    assert kinds[-1] == "done" and "gate" in kinds and "wake" in kinds and "spawn" in kinds


def test_the_standard_dry_run_is_faithful(home):
    texts = [e["text"] for e in wd.dry_run(wf.build_standard())["timeline"] if e["kind"] != "wake"]
    assert "owner spawns architect" in texts and "architect spawns engineer" in texts
    assert any(t.startswith("board pairs qa.") for t in texts)
    assert "owner: answer design_signoff" in texts


def test_a_stall_names_the_step_and_blocks_publish(board):
    d = _draft(board)
    for r in d["roles"]:  # nobody may spawn an engineer: the story is never built
        r["may_spawn"] = [x for x in r["may_spawn"] if x != "engineer"]
        if r["id"] == "sme":
            r["spawnable"] = False
    for r in d["roles"]:
        if r["id"] == "engineer":
            r["spawnable"] = True
    # the lint also sees it (role_without_spawner); the dry run says where the walk stops
    run = wd.dry_run(d)
    assert run["stall"] is not None and run["stall"]["step"] == "assign the story"
    assert any("spawn" in t["refusal"] for t in run["stall"]["tried"])
    assert run["timeline"][-1]["kind"] == "stall"


def test_a_lint_clean_draft_that_stalls_cannot_publish(board):
    d = _draft(board)
    d["hooks"]["criteria_auto_done"]["params"]["epic_checker"] = "owner"  # epics need owner criteria …
    board.workflows.save(d, by="owner")  # … but the checker map still gives epics to qa
    assert [c for c in _codes(d)] == []
    with pytest.raises(wf.WorkflowError) as e:
        board.workflows.publish("crew", 1, by="owner")
    assert e.value.problems[0]["code"] == "dry_run_stall" and "epic" in e.value.problems[0]["message"]


def test_diff_against_the_source_version(board):
    d = _draft(board)
    d["caps"]["stories_per_epic"] = 3
    d = _with_role(d, _designer())
    changes = {c["path"]: c for c in wd.diff(wf.build_standard(), d)}
    assert changes["caps.stories_per_epic"]["op"] == "changed" and changes["caps.stories_per_epic"]["after"] == 3
    assert changes["roles.designer"]["op"] == "added"
    assert changes["roles.architect.may_spawn"]["op"] == "changed"
    assert wd.diff(wf.build_standard(), wf.build_standard()) == []


def _publish(board, d):
    board.workflows.save(d, by="owner")
    return board.workflows.publish(d["id"], d["version"], by="owner").ref


def test_upstream_changed_and_three_way_merge_into_a_new_draft(board):
    team1 = _publish(board, _draft(board, "team"))
    mine = wf.dump(board.workflows.duplicate(team1, new_id="mine", by="owner"))
    assert mine["source"] == "team@1"
    mine["caps"]["tasks_per_story"] = 2  # ours
    mine["name"] = "Mine"
    board.workflows.save(mine, by="owner")
    assert board.workflows.upstream("mine@1")["changed"] is False
    team2 = wf.dump(board.workflows.duplicate(team1, by="owner"))
    assert team2["source"] == "standard@1"  # a new version keeps the upstream its line tracks
    team2["caps"]["criteria_per_story"] = 4  # theirs
    team2["caps"]["tasks_per_story"] = 7  # theirs too: a conflict with ours
    _publish(board, team2)
    up = board.workflows.upstream("mine@1")
    assert up["changed"] and up["latest"] == "team@2"
    assert {c["path"] for c in up["diff"]} == {"caps.criteria_per_story", "caps.tasks_per_story"}
    out = board.workflows.merge_upstream("mine@1", by="owner")
    new = out["draft"]
    assert (new["id"], new["version"], new["published"], new["source"]) == ("mine", 2, False, "team@2")
    assert new["caps"]["criteria_per_story"] == 4 and new["name"] == "Mine"  # theirs taken, ours kept
    assert new["caps"]["tasks_per_story"] == 2  # the conflict keeps ours …
    assert [c["path"] for c in out["conflicts"]] == ["caps.tasks_per_story"]  # … and says so
    assert board.workflows.upstream("mine@2")["changed"] is False


def test_standard_n_plus_1_shows_upstream_changed(board, monkeypatch):
    mine = _draft(board, "mine")
    mine["caps"]["stories_per_epic"] = 5
    board.workflows.save(mine, by="owner")

    def standard_v2():
        d = wf.build_standard()
        d = d.model_copy(update={"version": 2})
        d.caps["criteria_per_story"] = d.caps["criteria_per_story"] + 1
        return d

    monkeypatch.setitem(wf.BUILTIN_BUILDERS, "standard", standard_v2)
    board.workflows._builtin.clear()
    up = board.workflows.upstream("mine@1")
    assert up["changed"] and up["latest"] == "standard@2"
    assert [c["path"] for c in up["diff"]] == ["caps.criteria_per_story"]  # base = the snapshot of @1
    out = board.workflows.merge_upstream("mine@1", by="owner")
    assert out["conflicts"] == [] and out["draft"]["caps"]["stories_per_epic"] == 5
    assert out["draft"]["caps"]["criteria_per_story"] == wf.build_standard().caps["criteria_per_story"] + 1


# ---- REST: templates, dry run, diff, upstream, pins, admin-only edits ----------------------------

@pytest.fixture
def client(home):
    b = Board(Store(":memory:"), pool=_Pool(), free_mb=lambda: 10_000)
    c = TestClient(create_app(b, admin_token="t"))
    for pid, role, typ in (("owner", "owner", "human"), ("bob", "owner", "human"), ("eng", "engineer", "agent")):
        assert c.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                      headers={"X-Admin": "t"}).json()["ok"]
    return c


def test_the_design_api(client):
    c, O, B, E = client, {"X-Participant": "owner"}, {"X-Participant": "bob"}, {"X-Participant": "eng"}
    t = c.get("/v1/workflows/templates", headers=E).json()["value"]
    assert set(t["roles"]) == {"builder", "checker", "reviewer"} and "epic_auto_advance" in t["hooks"]
    # a non-admin human reads but cannot edit
    assert c.post("/v1/workflows/duplicate", json={"ref": "standard@1", "new_id": "x"}, headers=B).status_code == 400
    assert "read-only" in c.get("/v1/workflows", headers=B).json()["hint"]
    d = c.post("/v1/workflows/duplicate", json={"ref": "standard@1", "new_id": "team"}, headers=O).json()["value"]
    assert d["source"] == "standard@1"
    run = c.post("/v1/workflows/dryrun", json=d, headers=B).json()["value"]
    assert run["ok"] and run["timeline"][-1]["kind"] == "done"
    d["caps"]["stories_per_epic"] = 3
    assert c.put("/v1/workflows", json=d, headers=O).json()["ok"]
    assert c.put("/v1/workflows", json=d, headers=B).status_code == 400
    diff = c.get("/v1/workflows/team@1/diff", headers=B).json()["value"]
    assert diff["against"] == "standard@1"
    assert [x["path"] for x in diff["changes"]] == ["caps.stories_per_epic", "name"]  # "Standard (copy)"
    stalled = {**d, "hooks": {**d["hooks"], "criteria_auto_done": {"on": True, "params": {"epic_checker": "owner"}}}}
    v = c.post("/v1/workflows/validate", json=stalled, headers=B).json()["value"]
    assert v["valid"] is False and [p["code"] for p in v["problems"] if p["severity"] == "error"] == ["dry_run_stall"]
    assert c.post("/v1/workflows/team@1/publish", headers=O).json()["ok"]
    epic = c.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "E", "workflow": "team@1"},
                  headers=O).json()["value"]
    rows = {r["ref"]: r for r in c.get("/v1/workflows", headers=B).json()["value"]}
    assert rows["team@1"]["pinned_by"] == [epic["id"]] and rows["team@1"]["source"] == "standard@1"
    assert c.get("/v1/workflows/team@1/upstream", headers=B).json()["value"]["changed"] is False
    assert c.post("/v1/workflows/team@1/merge-upstream", headers=O).status_code == 409


def test_a_definition_named_like_a_preset_walks_as_written(home):
    d = wf.dump(wf.build_standard())  # e.g. the Design tab dry-running an edited copy before it is renamed
    d["hooks"]["criteria_auto_done"]["params"]["epic_checker"] = "owner"
    assert wd.dry_run(d)["stall"] is not None
