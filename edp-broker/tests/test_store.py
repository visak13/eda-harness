"""TESTPLAN BRK-S store-level."""

from datetime import datetime, timedelta, timezone

import pytest
from edp_contracts import BrokerMessage

from edp_broker.store import BadRecipient, InboxStore


def _msg(to="neuron:r1", kind="done", ts=None):
    return BrokerMessage(
        msg_id="m1",
        ts=ts or datetime.now(timezone.utc),
        **{"from": "planner:p1"},
        to=to,
        kind=kind,
        body={"x": 1},
    )


def test_brk_s_1_roundtrip(tmp_path):
    s = InboxStore(tmp_path)
    s.append(_msg())
    got = s.read("neuron:r1")
    assert len(got) == 1 and got[0].from_ == "planner:p1"


def test_brk_s_3_since_filter(tmp_path):
    s = InboxStore(tmp_path)
    old = datetime.now(timezone.utc) - timedelta(hours=1)
    s.append(_msg(ts=old))
    s.append(_msg())
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
    assert len(s.read("neuron:r1", since=cutoff)) == 1


def test_brk_s_4_durability(tmp_path):
    InboxStore(tmp_path).append(_msg())
    # brand-new store over same dir sees prior message
    assert len(InboxStore(tmp_path).read("neuron:r1")) == 1


def test_brk_s_5_alias_resolution(tmp_path):
    s = InboxStore(tmp_path)
    s.aliases.put("neuron:r1", "my-planner", "planner:p9")
    s.append(_msg(to="neuron:r1/my-planner"))
    assert len(s.read("planner:p9")) == 1


def test_brk_s_5b_unresolved_alias_raises(tmp_path):
    s = InboxStore(tmp_path)
    with pytest.raises(BadRecipient):
        s.append(_msg(to="neuron:r1/ghost"))


def test_brk_s_6_bad_recipient_no_path_escape(tmp_path):
    s = InboxStore(tmp_path)
    with pytest.raises(BadRecipient):
        s.read("../etc/passwd")


# --- s16: colon-handle → dash-inbox absolute alias bridge -----------------

def test_brk_s16_absolute_alias_bridges_colon_handle_to_dash_inbox(tmp_path):
    """s16 ROOT-CAUSE FIX: a planner's colon EDP_HANDLE is bridged to the
    DASH inbox it actually reads on. A publish to the colon handle must
    land in the dash file (delivered) — not dead-letter into the
    colon-sanitized `<recipe>_<step>.jsonl` the planner never polls."""
    s = InboxStore(tmp_path)
    colon, dash = "rec-abc-s6:s1", "rec-abc-s6-s1"
    s.aliases.put_absolute(colon, dash)
    s.append(_msg(to=colon))
    # delivered to the dash inbox the planner's rx.broker/check_inbox poll
    assert len(s.read(dash)) == 1
    # read on the colon form converges to the SAME file (append/read symmetry)
    assert len(s.read(colon)) == 1
    # the dead colon-sanitized file was never written
    assert not (tmp_path / "rec-abc-s6_s1.jsonl").exists()


def test_brk_s16_resolve_unmapped_concrete_is_identity(tmp_path):
    """s16 NO-REGRESSION: relaxing resolve for non-slash recipients must
    keep identity routing for an ordinary unmapped concrete recipient."""
    s = InboxStore(tmp_path)
    assert s.aliases.resolve("neuron:r1") == "neuron:r1"
    s.append(_msg(to="neuron:r1"))
    assert len(s.read("neuron:r1")) == 1


def test_brk_s16_relative_ref_still_resolves(tmp_path):
    """s16 NO-REGRESSION: the existing owner/alias relative-ref bridge is
    untouched by the absolute-alias addition."""
    s = InboxStore(tmp_path)
    s.aliases.put("neuron:r1", "my-planner", "planner:p9")
    s.append(_msg(to="neuron:r1/my-planner"))
    assert len(s.read("planner:p9")) == 1
    # an unregistered relative ref still dead-letters (raises) — unchanged
    with pytest.raises(BadRecipient):
        s.append(_msg(to="neuron:r1/ghost"))


def test_channel_registry_roundtrip(tmp_path):
    # CHANNELS 2026-07-21: durable membership record over ordinary inboxes.
    from edp_broker.store import BadRecipient, ChannelStore
    import pytest
    cs = ChannelStore(tmp_path)
    row = cs.put("team-rec-s3", ["lead-s3", "coder-a4", "qa-r1"],
                 topic="grounding brief v1")
    assert row["members"] == ["coder-a4", "lead-s3", "qa-r1"]
    assert cs.get("team-rec-s3")["topic"] == "grounding brief v1"
    # topic survives a member-only update
    cs.put("team-rec-s3", ["lead-s3", "coder-a4"])
    assert cs.get("team-rec-s3")["topic"] == "grounding brief v1"
    assert cs.list(member="lead-s3")[0]["channel"] == "team-rec-s3"
    assert cs.list(member="nobody") == []
    assert cs.delete("team-rec-s3") is True
    assert cs.get("team-rec-s3") is None
    with pytest.raises(BadRecipient):
        cs.put("bad name!", ["x"])


# ── F34 R2 (2026-08-18) — broker store hardening ──────────────────────────

def test_f34_torn_line_does_not_poison_read(tmp_path):
    s = InboxStore(tmp_path)
    s.append(_msg())
    # simulate a torn append: half a JSON object, then a valid message
    p = s._file("neuron:r1")
    with open(p, "a", encoding="utf-8") as f:
        f.write('{"msg_id": "torn", "ts": "2026-')
        f.write("\n")
    m2 = _msg()
    m2.msg_id = "m2"
    s.append(m2)
    got = s.read("neuron:r1")
    assert [m.msg_id for m in got] == ["m1", "m2"]


def test_f34_colon_underscore_collision_filtered(tmp_path):
    s = InboxStore(tmp_path)
    a = _msg(to="plan:a1")
    b = _msg(to="plan_a1")
    b.msg_id = "mb"
    s.append(a)
    s.append(b)
    # both land in plan_a1.jsonl, but each recipient sees only its own mail
    assert [m.msg_id for m in s.read("plan:a1")] == ["m1"]
    assert [m.msg_id for m in s.read("plan_a1")] == ["mb"]


def test_f34_append_stamps_monotonic_ts(tmp_path):
    s = InboxStore(tmp_path)
    now = datetime.now(timezone.utc)
    first = _msg(ts=now)
    s.append(first)
    # a second message whose sender clock is BEHIND the first must not be
    # hidden behind a ts>cursor read — the broker stamps it forward.
    late = _msg(ts=now - timedelta(seconds=5))
    late.msg_id = "late"
    s.append(late)
    got = s.read("neuron:r1", since=now - timedelta(microseconds=1))
    assert {m.msg_id for m in got} == {"m1", "late"}
    assert got[-1].ts > first.ts


def test_f34_monotonic_survives_process_restart(tmp_path):
    now = datetime.now(timezone.utc)
    s1 = InboxStore(tmp_path)
    s1.append(_msg(ts=now))
    s2 = InboxStore(tmp_path)          # fresh process: cache seeded from file
    late = _msg(ts=now - timedelta(seconds=5))
    late.msg_id = "late"
    s2.append(late)
    got = s2.read("neuron:r1")
    assert got[0].ts < got[1].ts
