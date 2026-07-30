"""TESTPLAN §3 — skill.py. Fixtures written to tmp_path."""

from edp_contracts import validate_skill
from edp_contracts.skill import SkillRule, parse_skill_header

_GOOD = """---
skill: ocak
hosts: [neuron]
inputs:
  recipe_id: str
outputs:
  writes: [recipe.comprehension.branches, recipe.steps]
  via: [record_recipe, record_step]
unload: after writing comprehension, end skill
---
You are OCAK. Walk the checks.
Persist via record_recipe(recipe) and record_step(recipe_id, step).
When the comprehension is written, end skill (unload).
"""


def _write(tmp_path, text, name="s.md"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_skl_1_clean(tmp_path):
    """SKL-1 MUST."""
    assert validate_skill(_write(tmp_path, _GOOD)) == []


def test_skl_2_missing_header(tmp_path):
    """SKL-2 MUST."""
    v = validate_skill(_write(tmp_path, "no front matter here\nend skill"))
    assert len(v) == 1 and v[0].rule == SkillRule.R1


def test_skl_3_undeclared_record_tool(tmp_path):
    """SKL-3 MUST — body calls record_plan but via only has record_recipe."""
    bad = _GOOD.replace(
        "via: [record_recipe, record_step]", "via: [record_recipe]"
    ).replace("record_step", "record_plan")
    v = validate_skill(_write(tmp_path, bad))
    rules = {x.rule for x in v}
    assert SkillRule.R2 in rules
    assert any("record_plan" in x.detail for x in v if x.rule == SkillRule.R2)


def test_skl_4_missing_unload(tmp_path):
    """SKL-4 MUST."""
    no_unload = _GOOD.replace(
        "When the comprehension is written, end skill (unload).", "Done."
    )
    v = validate_skill(_write(tmp_path, no_unload))
    assert any(x.rule == SkillRule.R3 for x in v)


def test_skl_5_bad_host(tmp_path):
    """SKL-5 MUST."""
    bad = _GOOD.replace("hosts: [neuron]", "hosts: [orchestrator]")
    v = validate_skill(_write(tmp_path, bad))
    assert any(x.rule == SkillRule.R4 for x in v)


def test_skl_6_worker_spawn(tmp_path):
    """SKL-6 MUST."""
    bad = _GOOD.replace("hosts: [neuron]", "hosts: [worker]")
    bad += "\nThen pool.spawn_worker(plan_id, action_id).\n"
    v = validate_skill(_write(tmp_path, bad))
    assert any(x.rule == SkillRule.R5 for x in v)


def test_skl_7_over_declare_ok(tmp_path):
    """SKL-7 SHOULD — declaring a tool the body never calls is allowed."""
    over = _GOOD.replace(
        "via: [record_recipe, record_step]",
        "via: [record_recipe, record_step, record_decision]",
    )
    assert validate_skill(_write(tmp_path, over)) == []


def test_parse_returns_three_tuple(tmp_path):
    """LLD-amended signature: (header, body, parse_error)."""
    header, body, err = parse_skill_header(_GOOD)
    assert header is not None and err == ""
    assert "You are OCAK" in body
    h2, b2, e2 = parse_skill_header("garbage")
    assert h2 is None and e2 != ""
