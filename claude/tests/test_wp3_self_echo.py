"""WP3 sensory self-echo filter — a shell is never woken by its own writes.

Covers effects.is_self_echo (authorship + bookkeeping detection, both handle
spellings) and driver.run(owner=...) dropping self-authored emissions from
the NDJSON stream while foreign events still flow.
"""

from __future__ import annotations

import io
import json

import reactivex as rx

from edp_claude.reactive.driver import run
from edp_claude.reactive.effects import is_self_echo

OWNER_COLON = "recipe-x-s1:a2"
OWNER_DASH = "recipe-x-s1-a2"


class TestIsSelfEcho:
    def test_broker_from_matches_either_handle_spelling(self):
        assert is_self_echo({"from": OWNER_COLON, "kind": "progress"}, OWNER_DASH)
        assert is_self_echo({"from": OWNER_DASH, "kind": "progress"}, OWNER_COLON)

    def test_author_field_under_body_matches(self):
        event = {"kind": "done", "body": {"from": OWNER_DASH}}
        assert is_self_echo(event, OWNER_DASH)

    def test_foreign_author_is_not_an_echo(self):
        assert not is_self_echo({"from": "someone-else", "kind": "done"}, OWNER_DASH)

    def test_message_received_bookkeeping_is_always_self(self):
        # written on the reader's own check_inbox delivery path — never signal
        assert is_self_echo({"kind": "message_received", "from": "other"}, OWNER_DASH)

    def test_no_owner_never_filters(self):
        assert not is_self_echo({"from": OWNER_DASH}, "")

    def test_non_dict_events_pass_through(self):
        assert not is_self_echo("plain string", OWNER_DASH)

    def test_role_names_in_by_field_do_not_false_positive(self):
        assert not is_self_echo({"by": "neuron", "kind": "decision"}, OWNER_DASH)


class TestDriverOwnerFilter:
    def _run_collect(self, events, owner: str) -> list[dict]:
        out = io.StringIO()
        run(rx.from_iterable(events), out=out, owner=owner)
        return [json.loads(line) for line in out.getvalue().splitlines()]

    def test_self_authored_events_are_dropped_foreign_kept(self):
        events = [
            {"kind": "done", "from": "worker-1", "body": {}},
            {"kind": "progress", "from": OWNER_DASH, "body": {}},   # self
            {"kind": "message_received", "msg": "x"},               # bookkeeping
        ]
        lines = self._run_collect(events, OWNER_DASH)
        emitted = [ln["event"] for ln in lines if "event" in ln]
        assert len(emitted) == 1
        assert emitted[0]["from"] == "worker-1"

    def test_without_owner_everything_flows(self):
        events = [{"kind": "progress", "from": OWNER_DASH}]
        lines = self._run_collect(events, "")
        assert any("event" in ln for ln in lines)
