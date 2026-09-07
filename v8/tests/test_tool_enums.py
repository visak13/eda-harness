"""Design §19 rules 3, 5 and 6 (criteria c-a5343681f9, c-93929858f6):

- every strict-valued tool argument is an Enum, and a wrong value returns the envelope
  {code, message, field, allowed} + a hint naming the fix (rule 3/5);
- describe('enums') / describe('enum:<Name>') answer every enum (rule 3);
- ticket_update/ticket_read take `ticket_id` (old `id` accepted with a deprecation hint);
- the third consecutive failure of one tool by one seat inlines that tool's full schema
  in the hint (rule 6).
"""

from __future__ import annotations

import typing

import pytest

from edp8.bundles import (
    ALL_TOOLS,
    _deprecation_note,
    enum_fields,
    invoke,
)
from edp8.schemas import ENUMS

# ---------------------------------------------------------------- enum coverage

# (tool name, field) for every enum-typed argument across the whole registry
_ENUM_ARGS = [(name, field, values)
              for name, tool in ALL_TOOLS.items()
              for field, values in enum_fields(tool.args_model).items()]


def _dummy_for(annotation: typing.Any) -> typing.Any:
    base = annotation
    args = [a for a in typing.get_args(annotation) if a is not type(None)]
    if args:
        base = args[0]
    if base is int:
        return 0
    if base is bool:
        return False
    if typing.get_origin(base) is list:
        return []
    return "x"


def _valid_kwargs(tool) -> dict[str, typing.Any]:
    """Type-valid values for every required field, so a single bad enum is the only error."""
    ef = enum_fields(tool.args_model)
    kw: dict[str, typing.Any] = {}
    for fname, field in tool.args_model.model_fields.items():
        if not field.is_required():
            continue
        kw[fname] = ef[fname][0] if fname in ef else _dummy_for(field.annotation)
    return kw


def test_every_strict_arg_is_an_enum():
    """The strict vocabularies §19 rule 3 names are enums somewhere in the registry."""
    covered = {f for _, f, _ in _ENUM_ARGS}
    for expected in ("status", "kind", "work_type", "check", "checked_by", "verdict",
                     "relation", "gate", "form", "role", "purpose", "profile", "model"):
        assert expected in covered, f"strict arg {expected!r} is not an enum on any tool"


@pytest.mark.parametrize("name,field,values", _ENUM_ARGS)
def test_bad_enum_value_names_field_and_allowed(name: str, field: str, values: list[str]):
    tool = ALL_TOOLS[name]
    kwargs = _valid_kwargs(tool)
    kwargs[field] = "__definitely_not_valid__"
    resp = invoke(tool, kwargs, seat=f"seat-{name}-{field}")
    assert resp["ok"] is False, (name, field)
    err = resp["error"]
    assert err["code"] == "schema"
    assert err["field"] == field, f"{name}: envelope named {err.get('field')!r}, expected {field!r}"
    assert err["allowed"] == values, f"{name}.{field}: allowed set mismatch"
    for v in values:
        assert v in resp["hint"], f"{name}.{field}: hint omits allowed value {v!r}"


# ---------------------------------------------------------------- describe(enums)

def test_describe_enums_lists_every_enum():
    resp = ALL_TOOLS["describe"].handler(ALL_TOOLS["describe"].args_model(type="enums"))
    assert resp["ok"] is True
    listed = resp["value"]["enums"]
    for name, enum in ENUMS.items():
        assert listed[name] == [m.value for m in enum]


def test_describe_single_enum():
    resp = ALL_TOOLS["describe"].handler(ALL_TOOLS["describe"].args_model(type="enum:Verdict"))
    assert resp["ok"] is True
    assert resp["value"]["values"] == ["pending", "pass", "fail"]


def test_describe_unknown_enum_names_field_and_allowed():
    resp = ALL_TOOLS["describe"].handler(ALL_TOOLS["describe"].args_model(type="enum:Nope"))
    assert resp["ok"] is False
    assert resp["error"]["field"] == "type"
    assert "ConsultPurpose" in resp["error"]["allowed"]


# ---------------------------------------------------------------- ticket_id rename

def test_ticket_update_accepts_ticket_id_and_legacy_id():
    m = ALL_TOOLS["ticket_update"].args_model
    assert m(ticket_id="t-1").ticket_id == "t-1"
    assert m(id="t-1").ticket_id == "t-1"          # legacy alias still validates


def test_ticket_read_accepts_ticket_id_and_legacy_id():
    m = ALL_TOOLS["ticket_read"].args_model
    assert m(ticket_id="t-1").ticket_id == "t-1"
    assert m(id="t-1").ticket_id == "t-1"


def test_legacy_id_carries_a_deprecation_note():
    tool = ALL_TOOLS["ticket_update"]
    assert _deprecation_note(tool, {"id": "t-1"}) is not None
    assert "ticket_id" in _deprecation_note(tool, {"id": "t-1"})
    assert _deprecation_note(tool, {"ticket_id": "t-1"}) is None


# ---------------------------------------------------------------- rule 6: tripwire

def test_third_consecutive_failure_inlines_full_schema():
    tool = ALL_TOOLS["ticket_update"]
    seat = "engineer.tripwire-A"
    bad = {"ticket_id": "t", "status": "not-a-status"}
    r1 = invoke(tool, bad, seat=seat)
    r2 = invoke(tool, bad, seat=seat)
    r3 = invoke(tool, bad, seat=seat)
    assert "full schema" not in r1["hint"]
    assert "full schema" not in r2["hint"]
    assert "full schema" in r3["hint"], "third failure must inline the schema"
    assert tool.schema_inline() in r3["hint"]


def test_tripwire_is_per_seat_and_per_tool():
    tool = ALL_TOOLS["ticket_update"]
    other = ALL_TOOLS["criterion_update"]
    bad = {"ticket_id": "t", "status": "nope"}
    invoke(tool, bad, seat="seatX")
    invoke(tool, bad, seat="seatX")
    # a different seat starts fresh
    r_other_seat = invoke(tool, bad, seat="seatY")
    assert "full schema" not in r_other_seat["hint"]
    # a different tool for the same seat starts fresh
    r_other_tool = invoke(other, {"id": "c", "verdict": "nope"}, seat="seatX")
    assert "full schema" not in r_other_tool["hint"]
