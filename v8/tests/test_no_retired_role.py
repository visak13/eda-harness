"""Owner m-da9a2ae62f (t-cd4712c855): "reviewer role is removed. please remove it from everywhere ... i dont
want it to appear again ever."

This guard fails the moment "reviewer" (or another removed role) comes back as a role: in the Role enum, a
built-in workflow, the Add-role templates, the avatar templates, the spawn enum, models.json, a role card, the
schema's role parser, workflow validation, the SPA or the pool. A repo-wide grep backs it up; the only files
allowed to spell the word are the ones that keep old databases loading (the store's migration and its test),
the one constant that names removed roles (edp_contracts.roles), this guard, and frozen evidence, which,
like database rows, is a record and is not rewritten. The S1 concept archive was purged too (qa m-6399de5a1b).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from edp8 import avatar_templates, workflow as wflow, workflow_design as wd
from edp8.schemas import Role, SeatRole, SpawnRole, role_id
from edp_contracts.roles import NON_AGENT_ROLES, RETIRED_ROLES

V8 = Path(__file__).resolve().parents[1]
REPO = V8.parent
WORD = "reviewer"

#: may spell the word: they exist so an old database still loads, or they are the guard itself
ALLOWED = {
    "v8/src/edp8/store.py",  # Store._migrate_reviewer_locked: old rows -> qa at open
    "v8/tests/test_store.py",  # proves that migration
    "v8/tests/test_no_retired_role.py",  # this guard
    "edp-contracts/src/edp_contracts/roles.py",  # RETIRED_ROLES, the one place removed ids are named
}
#: frozen records, never rewritten (like database rows)
HISTORY = ("v8/docs/evidence/", "docs/evidence/")


def test_the_word_is_a_removed_role():
    assert WORD in RETIRED_ROLES


@pytest.mark.parametrize("rid", sorted(RETIRED_ROLES))
def test_no_code_registry_offers_a_removed_role(rid):
    assert rid not in {r.value for r in Role}
    assert rid not in {r.value for r in SeatRole} and rid not in {r.value for r in SpawnRole}
    assert rid not in wd.ROLE_TEMPLATES
    if rid == WORD:  # (the consultant/coordinator art still draws GPT seats and old rows; not a role offer)
        assert rid not in avatar_templates.BOT_TEMPLATES
    for wid, build in wflow.BUILTIN_BUILDERS.items():
        assert rid not in {r.id for r in build().roles}, wid
    with pytest.raises(ValueError):
        role_id(rid)


@pytest.mark.parametrize("rid", sorted(RETIRED_ROLES))
def test_workflow_validation_refuses_a_removed_role(rid):
    body = wflow.BUILTIN_BUILDERS[wflow.STANDARD_ID]().model_dump(by_alias=True)
    body["roles"].append({**wd.role_from_template("checker", "auditor"), "id": rid})
    for r in body["roles"]:
        if r["id"] == "architect":
            r["may_spawn"].append(rid)
    assert "retired_role" in {p["code"] for p in wflow.validate(body)}


def test_no_role_card_names_a_removed_or_person_role():
    stems = {p.stem.split("-")[0] for p in (V8 / ".claude" / "commands").glob("*.md")}
    assert not stems & (RETIRED_ROLES | NON_AGENT_ROLES), stems  # no reviewer.md, no owner.md


def test_models_json_binds_no_removed_or_person_role():
    raw = json.loads((V8 / "models.json").read_text(encoding="utf-8"))
    for col in [k for k in raw if k == "role_models" or k.startswith("roles")]:
        assert not set(raw[col]) & (RETIRED_ROLES | NON_AGENT_ROLES), col


def test_person_roles_are_human_and_never_spawnable_in_every_built_in_workflow():
    for wid, build in wflow.BUILTIN_BUILDERS.items():
        d = build()
        for r in d.roles:
            if r.id in NON_AGENT_ROLES:
                assert r.human and not r.spawnable, (wid, r.id)
        assert not wflow.Workflow(d).spawnable & NON_AGENT_ROLES, wid


def test_no_live_file_in_the_repo_names_the_removed_role():
    out = subprocess.run(["git", "grep", "-il", WORD, "--", "."],  # the committed tree is the app
                         cwd=REPO, capture_output=True, text=True, encoding="utf-8")
    assert out.returncode in (0, 1), out.stderr
    hits = [p for p in out.stdout.splitlines() if p and p not in ALLOWED and not p.startswith(HISTORY)]
    assert hits == [], f"{WORD!r} reappeared (owner m-da9a2ae62f): {hits}"

