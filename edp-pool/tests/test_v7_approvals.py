"""v7 follow-up — the panel approval queue (operator-mediated tool calls).

The PreToolUse hook parks a call via approval_request + approval_wait; the
panel lists approval_pending and posts approval_decide. Pinned here:
  * request → pending lists it; decide(allow|deny) unblocks the waiter with
    the verdict and CONSUMES the row;
  * wait TIMEOUT returns decision=None (the hook falls back to the shell's
    own prompt) and the row STAYS pending so the operator can still see what
    timed out;
  * unknown ids refuse/fall back instead of erroring;
  * summaries are bounded (never an unbounded blob in the panel).
"""

import threading
import time

from edp_pool.service import PoolService
from edp_pool.spawner import FakeSpawner


def _svc(tmp_path):
    return PoolService(FakeSpawner(), state_path=tmp_path / "state.json")


def test_request_pending_decide_allow_roundtrip(tmp_path):
    svc = _svc(tmp_path)
    aid = svc.approval_request({"handle": "p1:a1", "role": "worker",
                                "tool_name": "Bash",
                                "summary": "uv run pytest -q"})["id"]
    pend = svc.approval_pending()
    assert [p["id"] for p in pend] == [aid]
    assert pend[0]["tool_name"] == "Bash"

    got = {}
    t = threading.Thread(
        target=lambda: got.update(svc.approval_wait(aid, timeout_s=10)))
    t.start()
    time.sleep(0.1)
    svc.approval_decide(aid, "allow", "")
    t.join(timeout=5)
    assert got["decision"] == "allow"
    # consumed on delivery — the queue drains
    assert svc.approval_pending() == []


def test_deny_carries_the_operator_reason(tmp_path):
    svc = _svc(tmp_path)
    aid = svc.approval_request({"tool_name": "Write",
                                "summary": "C:/x.txt"})["id"]
    svc.approval_decide(aid, "deny", "wrong file — use docs/")
    out = svc.approval_wait(aid, timeout_s=1)
    assert out["decision"] == "deny"
    assert "wrong file" in out["reason"]


def test_timeout_returns_none_and_row_stays_visible(tmp_path):
    svc = _svc(tmp_path)
    aid = svc.approval_request({"tool_name": "Bash", "summary": "x"})["id"]
    out = svc.approval_wait(aid, timeout_s=0.05)
    assert out["decision"] is None, (
        "a lapse must fall back to the shell's own prompt, never block")
    # still listed: the operator can see what timed out into a console prompt
    assert [p["id"] for p in svc.approval_pending()] == [aid]


def test_unknown_ids_fall_back_not_crash(tmp_path):
    svc = _svc(tmp_path)
    assert svc.approval_wait("appr-nope", timeout_s=0.05)["decision"] is None
    assert "refused" in svc.approval_decide("appr-nope", "allow", "")
    assert "refused" in svc.approval_decide(
        svc.approval_request({"tool_name": "Bash"})["id"], "maybe", "")


def test_summary_is_bounded(tmp_path):
    svc = _svc(tmp_path)
    aid = svc.approval_request({"tool_name": "Bash",
                                "summary": "x" * 50_000})["id"]
    row = svc.approval_pending()[0]
    assert row["id"] == aid and len(row["summary"]) <= 2000
