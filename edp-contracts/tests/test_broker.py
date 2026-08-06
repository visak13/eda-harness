"""TESTPLAN §4 — broker.py."""

from datetime import datetime, timezone

import pytest

from edp_contracts import CORE_KINDS, BrokerMessage, register_kind
from edp_contracts.broker import is_registered, registered_kinds


def _msg(**over):
    base = dict(
        msg_id="m1",
        ts=datetime.now(timezone.utc),
        to="b",
        kind="done",
        body={},
    )
    base.update(over)
    base.setdefault("from", "a")
    return BrokerMessage(**base)


def test_brk_1_roundtrip():
    """BRK-1 MUST."""
    m = _msg()
    d = m.model_dump(by_alias=True)
    m2 = BrokerMessage.model_validate(d)
    assert m2 == m
    assert m2.ts.tzinfo is not None


def test_brk_2_from_alias():
    """BRK-2 MUST — wire key is 'from', not 'from_'."""
    d = _msg().model_dump(by_alias=True)
    assert "from" in d and "from_" not in d
    assert BrokerMessage.model_validate(d).from_ == "a"


def test_brk_3_unregistered_kind_rejected():
    """BRK-3 MUST."""
    with pytest.raises(ValueError, match="unregistered BrokerKind"):
        _msg(kind="frobnicate")


def test_brk_4_core_kinds_registered():
    """BRK-4 MUST — all CORE_KINDS present with non-empty docs.
    2026-05-21: 11 → 14 with team-architecture Phase 2 (progress,
    observation, alert — upward notification kinds).
    2026-07-05: 14 → 16 with DESIGN-v6 W2/a5 (grounding, fyi — a child's upward
    assumption-surface and the planner's courtesy-CC cross the shell↔broker
    process boundary; they were in-process-only register_kinds the broker
    rejected as unregistered, so they too MUST be CORE kinds).
    2026-07-05: 17 → 16 with DESIGN-v6 d29 (verify_result removed — the detached
    acceptance-verify pool runner is gone; record_action_status is a pure write
    that runs no command, so nothing posts a cross-process verify outcome).
    2026-07-10: 16 → 17 with DESIGN-v6 W12 (review_comments — the panel's batched
    anchored plan-review message. Same reason as grounding/fyi: the broker
    validates kinds in its OWN process and fails closed, so a kind registered
    only in the MCP server is rejected on arrival).
    2026-07-12: 17 → 18 with steer_ack (receiver restates a steer in its own
    terms; sender verifies the restatement — defense against a directive being
    absorbed unread).
    2026-08-05: 18 → 19 with challenge (v7 WS1 adversarial layer: findings-only
    data from adversarial_challenge, published by the challenging shell;
    adjudicated, never obeyed).
    2026-08-05b: 19 → 20 with ground_delta (v7 WS3 scoped invalidation: a
    decision revision wakes ONLY the handles in its transitive impact
    closure, as a digest delta — never a fleet-wide re-ground)."""
    reg = registered_kinds()
    assert len(CORE_KINDS) == 20
    assert {"progress", "observation", "alert",
            "grounding", "fyi"} <= set(CORE_KINDS)
    for k, doc in CORE_KINDS.items():
        assert reg.get(k) == doc and doc


def test_brk_4a_steer_ack_validates():
    """steer_ack is a CORE kind — a BrokerMessage with it must validate."""
    m = _msg(kind="steer_ack",
             body={"restatement": "pause s3 until eval lands",
                   "steer_msg_id": "m0"})
    assert m.kind == "steer_ack"


def test_brk_5_register_idempotent_and_conflict():
    """BRK-5 MUST."""
    register_kind("done", CORE_KINDS["done"])  # same doc -> no-op
    with pytest.raises(ValueError, match="different doc"):
        register_kind("done", "a different meaning")


def test_brk_6_extensible():
    """BRK-6 SHOULD."""
    register_kind("custom_probe", "test-only kind")
    assert _msg(kind="custom_probe").kind == "custom_probe"


def test_brk_7_register_rejects_empty():
    """ST-4 closure — empty kind/doc guard."""
    with pytest.raises(ValueError, match="non-empty"):
        register_kind("", "")
    with pytest.raises(ValueError, match="non-empty"):
        register_kind("k", "")


def test_brk_8_is_registered_helper():
    """ST-4 closure — is_registered() both branches."""
    assert is_registered("done") is True
    assert is_registered("definitely-not-a-kind") is False
