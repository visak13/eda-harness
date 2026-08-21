"""QoL F19 — the MCP boundary emits structured text, never a JSON dump."""

from types import SimpleNamespace

from edp_claude.tools.render_text import render_payload, render_result


def test_scalars_lists_and_nesting_render_as_headed_lines():
    txt = render_payload({
        "recipe_id": "r-1",
        "count": 2,
        "flag": True,
        "steps": [{"step_id": "s1", "status": "done"},
                  {"step_id": "s2", "status": "pending"}],
        "tags": ["a", "b"],
        "meta": {"phase": "d", "empty": None},
    }, title="demo")
    assert txt.splitlines()[0] == "[demo]"
    assert "recipe_id: r-1" in txt
    assert "flag: true" in txt
    assert "tags: a, b" in txt
    assert "- step_id: s1" in txt
    assert "phase: d" in txt
    assert "{" not in txt and '"' not in txt      # no JSON leaked


def test_nulls_and_empties_are_dropped():
    txt = render_payload({"a": None, "b": "", "c": [], "d": {}, "e": "x"})
    assert txt == "e: x"


def test_long_string_renders_as_block():
    long = "line one\nline two"
    txt = render_payload({"note": long})
    assert txt.splitlines()[0] == "note:"
    assert "  line one" in txt and "  line two" in txt


def test_tool_error_renders_one_loud_line():
    err = SimpleNamespace(ok=False, code="tool_precondition",
                          message="no recipe 'x'")
    line = render_result("next_action", err)
    assert line.startswith("ERROR [next_action] (tool_precondition):")
    assert "no recipe 'x'" in line


def test_tool_ok_renders_payload_with_tool_title():
    ok = SimpleNamespace(ok=True, data={"outcome_id": "o1", "note": "n"})
    txt = render_result("record_outcome", ok)
    assert txt.splitlines()[0] == "[record_outcome]"
    assert "outcome_id: o1" in txt


def test_empty_payload_says_ok():
    ok = SimpleNamespace(ok=True, data=None)
    assert render_result("x", ok) == "[x] ok"
