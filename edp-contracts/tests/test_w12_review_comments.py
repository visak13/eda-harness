"""W12 — `review_comments` must be a CORE kind, registered in every process.

The broker validates every inbound message against `_REGISTRY` in ITS OWN
process and fails CLOSED on an unregistered kind (`BrokerMessage._kind_
registered`). A kind registered only inside the MCP server is therefore
accepted there and REJECTED at the broker — the exact defect the `grounding`
and `fyi` entries were added to CORE_KINDS to fix.

Without this registration the panel's entire plan-review feature is rejected on
arrival, and the failure surfaces as a validation error from a component nobody
was looking at.
"""

import pytest
from pydantic import ValidationError

from edp_contracts import BrokerMessage, is_registered
from edp_contracts.broker import CORE_KINDS

_MSG = {
    "msg_id": "m1",
    "ts": "2026-07-10T12:00:00+00:00",
    "from": "panel",
    "to": "recipe-x",
    "kind": "review_comments",
    "body": {"brief": "1.md",
             "comments": [{"anchor_quote": "the FSM advises",
                           "comment": "say why"}]},
}


def test_review_comments_is_a_core_kind():
    assert "review_comments" in CORE_KINDS
    assert is_registered("review_comments")


def test_a_review_comments_message_validates():
    m = BrokerMessage.model_validate(_MSG)
    assert m.kind == "review_comments"
    assert m.body["comments"][0]["anchor_quote"] == "the FSM advises"


def test_the_registry_still_fails_closed_on_an_unregistered_kind():
    """The property that made the registration necessary. If this ever passes
    vacuously, `review_comments` proves nothing."""
    with pytest.raises(ValidationError, match="unregistered BrokerKind"):
        BrokerMessage.model_validate({**_MSG, "kind": "panel_comments_v2"})
