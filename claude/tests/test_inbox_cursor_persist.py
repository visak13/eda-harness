"""s17 RP-C — check_inbox cursor PERSISTENCE (cursor-persist only).

Before RP-C the per-recipient cursor (`_INBOX_CURSORS`) was module-level
in-process ONLY: a FRESH shell (new worker/planner, cron-resumed/compacted
neuron) started with an empty dict and polled `since_ts=None`, so the broker
re-streamed the recipient's ENTIRE retained inbox — polluting the shell's
first post-restart turn with stale history.

RP-C backs the dict with a per-recipient cursor file under
`<agent_home>/.inbox_cursors/`, so a fresh shell resumes from last-seen.

The hard gate proven here:
  * persisted-cursor path delivers EXACTLY the messages a zero-cursor path
    would, minus the already-seen prefix;
  * NO unseen message is ever dropped;
  * explicit `replay=True` opt-in still re-polls the full history;
  * message bodies stay UNTRUNCATED (body-cap withdrawn).

A "fresh shell" is simulated by popping the recipient from the in-process
`_INBOX_CURSORS` while leaving the on-disk cursor file in place — exactly
what a new MCP-server process sees.
"""

import uuid
from datetime import datetime, timezone

from edp_contracts import BrokerMessage, ToolOk

from edp_claude.tools import _tools as T


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


async def _send(env, to, body, kind="answer", frm="curiosity-x"):
    await env.ctx.broker.send(BrokerMessage.model_validate({
        "msg_id": str(uuid.uuid4()), "ts": datetime.now(timezone.utc),
        "from": frm, "to": to, "kind": kind, "body": body,
    }))


def _fresh_shell(recipient):
    """Drop the in-process cursor cache for `recipient` — what a brand-new
    MCP-server process starts with. The on-disk cursor file is untouched."""
    T._INBOX_CURSORS.pop(recipient, None)


# ---------------------------------------------------------------------------
# core equivalence
# ---------------------------------------------------------------------------

async def test_fresh_shell_resumes_from_disk_not_replay(env):
    """Shell A consumes 3 msgs; a fresh shell B (empty in-proc cursor) must
    resume from the PERSISTED cursor — only the single NEW msg, never the
    3-message history replay."""
    rcpt = "plan-rpc:act-1"          # a worker handle (colon → fs-unsafe)
    for q in ("one", "two", "three"):
        await _send(env, rcpt, {"q": q})
    a = _ok(await env.call("check_inbox", handle=rcpt))
    assert [m["body"]["q"] for m in a["messages"]] == ["one", "two", "three"]

    _fresh_shell(rcpt)                # shell B starts cold
    await _send(env, rcpt, {"q": "four"})   # one genuinely new message
    b = _ok(await env.call("check_inbox", handle=rcpt))
    # disk cursor prevented the whole-history replay: only the new msg
    assert [m["body"]["q"] for m in b["messages"]] == ["four"]


async def test_fresh_shell_no_new_messages_returns_empty(env):
    """The pure pollution-fix proof: after a shell consumes the inbox, a
    fresh shell with NOTHING new pulls an EMPTY list — not a re-dump of the
    retained history."""
    rcpt = "plan-rpc:act-2"
    for q in ("a", "b"):
        await _send(env, rcpt, {"q": q})
    _ok(await env.call("check_inbox", handle=rcpt))   # consume both

    _fresh_shell(rcpt)
    again = _ok(await env.call("check_inbox", handle=rcpt))
    assert again["messages"] == []     # zero replay, clean window


async def test_no_unseen_message_dropped(env):
    """Equivalence stated as a partition: the union of what shell A and the
    fresh shell B deliver equals the FULL zero-cursor set, with no message
    omitted and none delivered twice."""
    rcpt = "plan-rpc:act-3"
    sent = [f"m{i}" for i in range(5)]
    for q in sent[:3]:
        await _send(env, rcpt, {"q": q})
    a = [m["body"]["q"] for m in
         _ok(await env.call("check_inbox", handle=rcpt))["messages"]]

    _fresh_shell(rcpt)
    for q in sent[3:]:
        await _send(env, rcpt, {"q": q})
    b = [m["body"]["q"] for m in
         _ok(await env.call("check_inbox", handle=rcpt))["messages"]]

    assert a + b == sent               # full coverage, in order
    assert set(a).isdisjoint(b)        # no double-delivery (seen prefix gone)


# ---------------------------------------------------------------------------
# explicit replay opt-in
# ---------------------------------------------------------------------------

async def test_replay_opt_in_returns_full_history(env):
    """replay=True ignores the persisted cursor and re-polls EVERYTHING —
    the catch-up/audit escape hatch, mirroring rx.broker(replay=True)."""
    rcpt = "plan-rpc:act-4"
    for q in ("x", "y", "z"):
        await _send(env, rcpt, {"q": q})
    _ok(await env.call("check_inbox", handle=rcpt))    # advance cursor past all

    _fresh_shell(rcpt)
    # default poll → nothing (cursor on disk)
    assert _ok(await env.call("check_inbox", handle=rcpt))["messages"] == []
    # explicit replay → the full retained history returns
    full = _ok(await env.call("check_inbox", handle=rcpt, replay=True))
    assert [m["body"]["q"] for m in full["messages"]] == ["x", "y", "z"]


async def test_replay_then_resumes_from_advanced_cursor(env):
    """After a replay the cursor still advances to the newest seen, so the
    NEXT default poll resumes correctly (replay is not a sticky mode)."""
    rcpt = "plan-rpc:act-5"
    await _send(env, rcpt, {"q": "old"})
    _ok(await env.call("check_inbox", handle=rcpt, replay=True))
    await _send(env, rcpt, {"q": "new"})
    nxt = _ok(await env.call("check_inbox", handle=rcpt))
    assert [m["body"]["q"] for m in nxt["messages"]] == ["new"]


# ---------------------------------------------------------------------------
# persistence mechanics
# ---------------------------------------------------------------------------

async def test_cursor_file_is_written_under_agent_home(env):
    """A cursor file actually lands under <agent_home>/.inbox_cursors after a
    delivery — the durable artifact a fresh shell reads."""
    rcpt = "plan-rpc:act-6"
    await _send(env, rcpt, {"q": "hi"})
    _ok(await env.call("check_inbox", handle=rcpt))
    root = env.ctx.recipes.root.parent / ".inbox_cursors"
    files = list(root.glob("*.ts"))
    assert files, f"no cursor file written under {root}"
    # the persisted value parses back to a timestamp
    ts = datetime.fromisoformat(files[0].read_text(encoding="utf-8").strip())
    assert ts.tzinfo is not None


async def test_colon_handle_filename_is_safe_and_distinct(env):
    """Worker handles contain ':' (illegal on Windows). Two handles that
    differ only by an fs-unsafe char must NOT collide onto one cursor
    file, and neither raises."""
    a, b = "plan-rpc:act-7", "plan-rpc_act-7"   # ':' vs '_' → same slug
    fa = T._inbox_cursor_file(env.ctx, a)
    fb = T._inbox_cursor_file(env.ctx, b)
    assert ":" not in fa.name                    # sanitized, Windows-safe
    assert fa != fb                              # sha suffix disambiguates
    # and a real round-trip through check_inbox does not error on the colon
    await _send(env, a, {"q": "ok"})
    assert _ok(await env.call("check_inbox", handle=a))["messages"]


async def test_corrupt_cursor_file_degrades_gracefully(env):
    """An unreadable/garbage cursor file must not break inbox delivery — it
    falls back to a wider poll (pre-RP-C behavior), never an exception."""
    rcpt = "plan-rpc:act-8"
    await _send(env, rcpt, {"q": "present"})
    _ok(await env.call("check_inbox", handle=rcpt))      # writes a cursor
    # corrupt it
    f = T._inbox_cursor_file(env.ctx, rcpt)
    f.write_text("not-a-timestamp", encoding="utf-8")
    _fresh_shell(rcpt)
    # no crash; corrupt cursor → None → full poll returns the history
    res = _ok(await env.call("check_inbox", handle=rcpt))
    assert [m["body"]["q"] for m in res["messages"]] == ["present"]


# ---------------------------------------------------------------------------
# body-cap WITHDRAWN
# ---------------------------------------------------------------------------

async def test_message_bodies_not_truncated(env):
    """RP-C is cursor-persist ONLY — bodies are returned in full. A large
    payload survives the round-trip byte-for-byte."""
    rcpt = "plan-rpc:act-9"
    big = "Z" * 20_000
    await _send(env, rcpt, {"q": big})
    res = _ok(await env.call("check_inbox", handle=rcpt))
    assert res["messages"][0]["body"]["q"] == big        # untruncated
