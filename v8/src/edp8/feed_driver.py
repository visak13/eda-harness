"""edp8 feed driver — CLI that tails the board feed (SSE) and, when a broker is
configured, the participant's edp-broker inbox (SSE) — merged into one NDJSON
stream. Meant to run under the Monitor tool: every printed line wakes the shell.

One line per item: `{"event": {...}}` (board) or `{"broker_msg": {...}}`
(broker inbox). Each stream reconnects on loss with backoff 1s -> 30s, resuming
from its own cursor (board seq / broker since_ts). Prints `{"error": "..."}` on
a failure it cannot recover from within a reconnect attempt, then keeps
retrying.

A third source is the driver's own heartbeat (EDP8_HEARTBEAT_S, default 1800 s; 0 = off): it polls
context_delta itself and prints `{"heartbeat": {...}}` only for a change the feed did not deliver, a cursor
resync, or a liveness ping for a doing seat whose ticket is in_progress. A quiet tick prints nothing — it
replaces the model-run cron, whose idle turns cost a model call each.

Every line is byte-capped (EDP8_FEED_EVENT_B, default 2000): an over-long line has its longest
strings clipped and carries `omitted` with the call that fetches the full item (S20 token-cost
rework: each line becomes a seat's turn input verbatim).
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from . import settings

_out_lock = threading.Lock()
_EVENT_BUDGET_B = 2_000     # default byte cap per printed line (env-overridable)
_OMITTED_RESERVE = 300      # room for the `omitted` receipt the cut adds
_MESSAGE_BUDGET_B = 32_000  # a message addressed to the seat (`msg`, `broker_msg`) keeps its whole text up to this


def _event_budget() -> int:
    try:
        return max(600, int(settings.get("EDP8_FEED_EVENT_B")))
    except ValueError:
        return _EVENT_BUDGET_B


def _message_budget() -> int:
    """The cap for a line that carries a message addressed to the seat: its whole text is the point of the wake
    (c-12f6fce800: "carrying its full text, with no message_read call"), so it is not held to the event budget."""
    return max(_event_budget(), _MESSAGE_BUDGET_B)


def _budget_for(obj: dict) -> int:
    return _message_budget() if ("msg" in obj or "broker_msg" in obj) else _event_budget()


def _dumps(obj: dict) -> str:
    return json.dumps(obj, default=str)


def _fetch_hint(obj: dict) -> str:
    """The call that returns the full item a capped line was cut from."""
    m = obj.get("msg")
    if isinstance(m, dict) and m.get("id"):
        return f"message_read(id={m['id']!r})"
    ev = obj.get("event")
    if isinstance(ev, dict):
        data = ev.get("data") or {}
        if data.get("message"):
            return f"message_read(id={data['message']!r})"
        return f"events_query(subject_id={ev.get('subject_id')!r}, since={max(0, int(ev.get('seq') or 1) - 1)})"
    msg = obj.get("broker_msg")
    if isinstance(msg, dict):
        body = msg.get("body") if isinstance(msg.get("body"), dict) else {}
        if body.get("board_msg_id"):
            return f"message_read(id={body['board_msg_id']!r})"
        if body.get("ticket_id"):
            return f"inbox(), or message_query(ticket_id={body['ticket_id']!r}) for the full text"
    return "inbox()"


def cap_line(obj: dict, budget: int | None = None) -> dict:
    """obj unchanged when its JSON line fits `budget` bytes; else a copy whose longest strings are
    clipped (`…[+N chars]`) until it fits, plus `omitted` naming the cap and the fetch call."""
    budget = budget or _event_budget()
    if len(_dumps(obj).encode()) <= budget:
        return obj
    out = copy.deepcopy(obj)
    target = budget - _OMITTED_RESERVE
    for _ in range(64):
        leaves: list[tuple[Any, Any, str]] = []

        def walk(node: Any) -> None:
            items = node.items() if isinstance(node, dict) else enumerate(node) if isinstance(node, list) else ()
            for k, v in items:
                if isinstance(v, str):
                    leaves.append((node, k, v))
                else:
                    walk(v)

        walk(out)
        excess = len(_dumps(out).encode()) - target
        if excess <= 0 or not leaves:
            break
        node, key, text = max(leaves, key=lambda leaf: len(_dumps({"": leaf[2]})))
        # JSON bytes per char of this string (escapes, multi-byte) so one clip lands under target
        per_char = max(1.0, (len(_dumps({"": text})) - 6) / max(1, len(text)))
        keep = max(0, len(text) - int(excess / per_char) - 24)  # 24 ≈ the marker's own bytes
        if keep >= len(text) or len(text) <= 24:
            break
        node[key] = f"{text[:keep]}…[+{len(text) - keep} chars]"
    out["omitted"] = {"truncated": True, "why": f"line capped at EDP8_FEED_EVENT_B={budget} bytes", "fetch": _fetch_hint(obj)[:200]}
    return out


def _print(obj: dict) -> None:
    line = _dumps(cap_line(obj, _budget_for(obj)))
    with _out_lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def _headers(participant: str) -> dict[str, str]:
    """Identity headers for the board: the seat handle plus its per-seat secret (S20 mints
    EDP8_TOKEN into the spawn env; a tokened board 401s a bare X-Participant)."""
    h = {"X-Participant": participant}
    token = settings.get("EDP8_TOKEN")
    if token:
        h["X-Token"] = token
    return h


_LISTENING_ROLES = {"architect", "owner"}   # a listening seat idles on a quiet board; the rest are doing seats
_RESYNC_AFTER_S = 12 * 3600                 # a quiet cursor is re-based well before the board's 24 h expiry
_MAX_PAGES = 5
_DELIVERED_KEEP = 4000

_LIVENESS_NEXT = ("heartbeat: you are mid-plan. context_delta(cursor=your last valid cursor) for anything new, "
                  "answer it, then RESUME THE NEXT UNBUILT ITEM of your plan doc — a quiet board is not a reason to "
                  "stop. End the turn silently only when your ticket is in_review/done or you are blocked "
                  "(record_status(status=blocked) and a deviation first).")
_CHANGES_NEXT = ("heartbeat: the board changed for you after your feed last woke you. "
                 "context_delta(cursor=your last valid cursor), answer what is new, then continue your plan.")
_RESYNC_NEXT = ("heartbeat: your orientation changed (scope, retention or a board reset). "
                "context() for a new baseline, then continue your plan.")


class Heartbeat:
    """The seat's 30-minute heartbeat, run by the feed driver instead of a model cron: the tick polls
    context_delta itself and prints a wake line ONLY when something needs the seat. A quiet board costs
    no model turn (S8; measured: idle cron turns were 658 of 978 heartbeat turns).

    A tick wakes for exactly one of: (changes) a delta row, or an asks/orientation change, that the live feed
    did not already deliver; (resync) the board refused the cursor, e.g. the seat's scope changed;
    (liveness) a doing seat whose ticket is in_progress — NEVER IDLE MID-PLAN stays. Listening seats
    (architect, owner) get no liveness ping. `fetch(path, params)` returns the board's JSON envelope."""

    def __init__(self, participant: str, fetch: Any, *, clock: Any = time.monotonic, emit: Any = None) -> None:
        self.participant = participant
        self.role = participant.split(".", 1)[0]
        self._fetch = fetch
        self._clock = clock
        self._emit = emit or _print
        self._lock = threading.Lock()
        self.cursor: str | None = None
        self._based_at = 0.0
        self._delivered: set[int] = set()   # event seqs the live feed already printed
        self._woken_since_tick = False      # any feed line (event or broker) since the last tick

    def note_wake(self, seq: int | None = None) -> None:
        """Called for every feed line printed: those changes are not the tick's to repeat."""
        with self._lock:
            self._woken_since_tick = True
            if isinstance(seq, int):
                self._delivered.add(seq)
                if len(self._delivered) > _DELIVERED_KEEP:
                    for old in sorted(self._delivered)[: _DELIVERED_KEEP // 2]:
                        self._delivered.discard(old)

    def baseline(self) -> bool:
        got = self._fetch("/v1/context", {})
        cursor = (got.get("value") or {}).get("cursor") if got.get("ok") else None
        if cursor:
            self.cursor, self._based_at = cursor, self._clock()
        return bool(cursor)

    def _doing_in_progress(self) -> str | None:
        """The id of an in_progress ticket of this doing seat, else None (a light read: whoami + chain)."""
        if self.role in _LISTENING_ROLES:
            return None
        who = self._fetch("/v1/whoami", {})
        for tid in (who.get("value") or {}).get("tickets") or []:
            got = self._fetch(f"/v1/tickets/{tid}", {"include": "chain", "thread_limit": 0})
            if (got.get("value") or {}).get("status") == "in_progress":
                return tid
        return None

    def tick(self) -> dict | None:
        """One heartbeat. Returns (and prints) the wake line, or None on a quiet board."""
        with self._lock:
            woken, self._woken_since_tick = self._woken_since_tick, False
            delivered = set(self._delivered)
        if self.cursor is None:
            if not self.baseline():
                return None   # board unreachable: nothing known, nothing to wake for
            return self._liveness()
        novel, resync, cursor = 0, False, self.cursor
        for _ in range(_MAX_PAGES):
            got = self._fetch("/v1/context_delta", {"cursor": cursor, "limit": 100})
            if not got.get("ok"):
                if (got.get("error") or {}).get("code") == "resync_required":
                    resync = True
                    break
                return None   # transient error: keep the cursor, try the next tick
            val = got["value"]
            novel += sum(1 for c in val.get("changes") or [] if c.get("seq") not in delivered)
            if not woken and (val.get("asks_changed") or val.get("orientation_changed")):
                novel += 1
            cursor = val.get("next_cursor") or cursor
            if not val.get("has_more"):
                break
        if resync:
            self.cursor = None
            self.baseline()
            return self._wake({"reason": "resync", "next": _RESYNC_NEXT})
        self.cursor = cursor
        if novel:
            return self._wake({"reason": "changes", "changes": novel, "next": _CHANGES_NEXT})
        if self._clock() - self._based_at > _RESYNC_AFTER_S:
            self.baseline()   # nothing changed through now, so re-basing loses nothing
        return self._liveness()

    def _liveness(self) -> dict | None:
        try:
            tid = self._doing_in_progress()
        except Exception:  # noqa: BLE001 — a failed read never wakes a seat
            return None
        if tid:
            return self._wake({"reason": "liveness", "ticket": tid, "next": _LIVENESS_NEXT})
        return None

    def _wake(self, body: dict) -> dict:
        line = {"heartbeat": body}
        self._emit(line)
        return line


def _http_fetch(board: str, participant: str) -> Any:
    client = httpx.Client(timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0))

    def fetch(path: str, params: dict) -> dict:
        try:
            r = client.get(f"{board}{path}", params={k: v for k, v in params.items() if v is not None},
                           headers=_headers(participant))
            return r.json()
        except Exception as e:  # noqa: BLE001 — a tick must never kill the driver
            return {"ok": False, "error": {"code": "unreachable", "message": f"{type(e).__name__}: {e}"}}
    return fetch


def _http_receipt(board: str, participant: str) -> Any:
    """POST /v1/messages/seen as the seat itself, off the wake path (a daemon thread per call: a slow board never delays a line)."""
    client = httpx.Client(timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0))

    def send(ids: list[str]) -> None:
        def post() -> None:
            try:
                client.post(f"{board}/v1/messages/seen", json={"ids": ids}, headers=_headers(participant))
            except Exception:  # noqa: BLE001 — best effort
                pass
        threading.Thread(target=post, name="seen-receipt", daemon=True).start()
    return send


def _heartbeat_loop(hb: Heartbeat, interval_s: int) -> None:
    hb.baseline()
    while True:
        time.sleep(interval_s)
        try:
            hb.tick()
        except Exception as e:  # noqa: BLE001
            _print({"error": f"heartbeat: {type(e).__name__}: {e}"})


_HB: Heartbeat | None = None


def _note_wake(seq: int | None = None) -> None:
    if _HB is not None:
        _HB.note_wake(seq)


def _heartbeat_interval() -> int:
    try:
        return max(0, int(settings.get("EDP8_HEARTBEAT_S")))
    except ValueError:
        return 1_800


_STATUS_PAGES = {"blocked", "failed", "deferred"}   # board.py _architect_courtesy_copy: the only status copies that page
_SEEN_KEEP = 600


class FeedState:
    """What survives a listener restart (e0cec s-e60c3d42ad): both plane cursors, whether the banner
    already printed, and the message ids already printed. A restart resumes from these, so nothing posted
    while the listener was down is lost and nothing already printed prints twice. `path=None` keeps it in memory."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.board_seq: int | None = None
        self.broker_ts: str | None = None
        self.banner = False
        self.seen: list[str] = []          # delivered: durable
        self.partial: list[str] = []       # delivered as a truncated preview; the full text is still owed
        self._reserved: set[str] = set()   # being delivered right now: in memory only, so a failed emit replays
        if path and path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                self.board_seq = raw.get("board_seq")
                self.broker_ts = raw.get("broker_ts")
                self.banner = bool(raw.get("banner"))
                self.seen = [str(x) for x in raw.get("seen") or []][-_SEEN_KEEP:]
                self.partial = [str(x) for x in raw.get("partial") or []][-_SEEN_KEEP:]
            except (OSError, ValueError):
                pass   # a torn file is a fresh start, never a crash

    def _save(self) -> None:
        if not self.path:
            return
        body = {"board_seq": self.board_seq, "broker_ts": self.broker_ts, "banner": self.banner, "seen": self.seen,
                "partial": self.partial}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(body), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass   # losing the cursor file costs a replay window, never the stream

    def reserve(self, msg_id: str | None) -> bool:
        """True when the caller may deliver this message: it is neither delivered nor being delivered by the other
        plane. The reservation is memory only; `commit` makes it durable once the line was written, `release`
        drops it after a failed write so a restart replays the message."""
        if not msg_id:
            return True
        with self._lock:
            if msg_id in self.seen or msg_id in self._reserved:
                return False
            self._reserved.add(msg_id)
            return True

    def commit(self, msg_id: str | None, *, partial: bool = False) -> None:
        if not msg_id:
            return
        with self._lock:
            self._reserved.discard(msg_id)
            self.seen.append(msg_id)
            del self.seen[:-_SEEN_KEEP]
            if partial:
                self.partial.append(msg_id)
                del self.partial[:-_SEEN_KEEP]
            self._save()

    def release(self, msg_id: str | None) -> None:
        if msg_id:
            with self._lock:
                self._reserved.discard(msg_id)

    def is_partial(self, msg_id: str | None) -> bool:
        with self._lock:
            return bool(msg_id) and msg_id in self.partial

    def complete(self, msg_id: str | None) -> None:
        """The full text of a partial message was delivered."""
        with self._lock:
            if msg_id in self.partial:
                self.partial.remove(msg_id)
                self._save()

    def advance(self, *, board_seq: int | None = None, broker_ts: str | None = None) -> None:
        with self._lock:
            if board_seq is not None and (self.board_seq is None or board_seq > self.board_seq):
                self.board_seq = board_seq
            if broker_ts:
                self.broker_ts = broker_ts
            self._save()

    def mark_banner(self) -> bool:
        """True only on the first start ever: the banner prints once, not on every restart."""
        with self._lock:
            if self.banner:
                return False
            self.banner = True
            self._save()
            return True


class Health:
    """One `lost` line when the first plane drops and one `recovered` line when every plane is back, however many
    retries sit between (a 10-retry outage prints two lines, not ten)."""

    def __init__(self, emit: Any = None) -> None:
        self._emit = emit or _print
        self._lock = threading.Lock()
        self._down: dict[str, str] = {}

    def down(self, plane: str, why: str) -> None:
        with self._lock:
            first = not self._down
            self._down.setdefault(plane, why)
            if first:
                self._emit({"feed": "lost", "plane": plane, "why": why[:200]})

    def up(self, plane: str) -> None:
        with self._lock:
            if self._down.pop(plane, None) is not None and not self._down:
                self._emit({"feed": "recovered"})


def _message_id(obj: dict) -> str | None:
    """The id both planes share: a board message_sent event carries it in data.message, a broker copy in
    body.board_msg_id. A seat close has no message: both planes announce it, so it is keyed on (participant, session,
    run, state); `run` is the board's started_seq, so close -> resume -> close of one session is two wakes. Any other board event that names a message (a closed_seat_message hint, for one) is its own wake and is
    never deduped against that message (qa report-689ceb50f0 fail 2: the hint was swallowed)."""
    if isinstance(obj.get("data"), dict):
        d = obj["data"]
        if d.get("message") and obj.get("kind") == "message_sent":
            return d["message"]
        if obj.get("kind") in ("shell_dead", "shell_stalled") and d.get("session"):
            state = "dead" if obj["kind"] == "shell_dead" else "stalled"
            return f"close:{d.get('participant')}:{d['session']}:{d.get('run')}:{state}"
        return None
    body = obj.get("body")
    if not isinstance(body, dict):
        return None
    if body.get("board_msg_id"):
        return body["board_msg_id"]
    if obj.get("from") == "pool" and body.get("session_id") and body.get("state"):
        return f"close:{body.get('participant')}:{body['session_id']}:{body.get('run')}:{body['state']}"
    return None


_PREVIEW_CHARS = 280   # the board event cuts message text at this many characters


def _to_me(ev: dict, participant: str) -> bool:
    d = ev.get("data") or {}
    return ev.get("kind") == "message_sent" and d.get("to") == participant


def _compact_msg(ev: dict, text: str) -> dict:
    """ONE compact line for an addressed human message: its whole text plus the context that rides with it
    (attachments, quoted passages, the guest marker), so the seat needs no message_read call."""
    d = ev.get("data") or {}
    msg = {"id": d.get("message"), "ticket": ev.get("subject_id"), "kind": d.get("kind"),
           "from": d.get("from"), "to": d.get("to"), "text": text}
    for key in ("from_handle", "from_role", "artifacts", "quoted"):
        if d.get(key):
            msg[key] = d[key]
    return {"msg": msg}


def _broker_completion(msg: dict) -> dict | None:
    """The full text a broker copy carries for a message the board plane delivered as a truncated preview."""
    body = msg.get("body") if isinstance(msg.get("body"), dict) else {}
    if not body.get("text"):
        return None
    out = {"id": body.get("board_msg_id"), "ticket": body.get("ticket_id"), "kind": msg.get("kind"),
           "from": msg.get("from"), "to": msg.get("to"), "text": body["text"], "completes": True}
    for key in ("artifacts", "quoted"):
        if body.get(key):
            out[key] = body[key]
    return {"msg": out}


_BOARD_ACTS = ("shell_dead", "shell_stalled")   # the board's act on a seat, whoever the event names


def _own_act(obj: dict, participant: str) -> bool:
    """True when the listening participant caused this event itself (its own criterion verdict, status, message):
    it already knows, so it earns no turn. Board event: data.by / data.from / created_by; broker copy: from /
    body.by. A seat close and a board hint (by=board) are the board's act and stay."""
    if obj.get("kind") in _BOARD_ACTS:
        return False
    if isinstance(obj.get("data"), dict):
        d = obj["data"]
        actors = (d.get("by"), d.get("from"), obj.get("created_by"))
    else:
        body = obj.get("body") if isinstance(obj.get("body"), dict) else {}
        actors = (obj.get("from"), body.get("by"))
    return participant in actors


class Listener:
    """The two planes' print rules, free of I/O so tests drive them with plain dicts."""

    def __init__(self, participant: str, state: FeedState, *, emit: Any = None, fetch: Any = None,
                 note_wake: Any = None, receipt: Any = None) -> None:
        self.participant = participant
        self._receipt = receipt
        self.state = state
        self._emit = emit or _print
        self._fetch = fetch
        self._note = note_wake or (lambda seq=None: None)

    def _compose(self, ev: dict, mid: str | None) -> tuple[dict, bool]:
        """(line, partial): an addressed human message is expanded to its full text; when the fetch fails the
        preview goes out marked `truncated` with the call that fetches the rest, and `partial` stays True so the
        broker copy (which has the whole text) still completes it. A message the board cut at 280 characters is
        expanded the same way whoever it is addressed to (adversary report-b9c60aeff1 Q1: the architect is woken for
        every question on its epic, and a 604-character one arrived as its first 280 with no sign of the rest)."""
        if ev.get("kind") != "message_sent":
            return {"event": ev}, False
        d = ev.get("data") or {}
        preview = d.get("text") or ""
        if len(preview) < _PREVIEW_CHARS and not (_to_me(ev, self.participant) and d.get("from_type") == "human"):
            return {"event": ev}, False   # the board did not cut it: the event already holds it all
        full = None
        if self._fetch is not None and mid:
            try:
                got = self._fetch(f"/v1/messages/{mid}", {})
            except Exception:  # noqa: BLE001 — a failed expansion falls back to the preview, loudly
                got = {}
            if got.get("ok"):
                full = (got.get("value") or {}).get("text")
        if full:
            return _compact_msg(ev, full), False
        line = _compact_msg(ev, preview)
        if len(preview) < _PREVIEW_CHARS:   # the board did not cut it: the preview IS the whole text
            return line, False
        line["msg"]["truncated"] = True
        line["msg"]["fetch"] = f"message_read(id={mid!r})"
        return line, True

    def _seen(self, mid: str | None) -> None:
        """The line is printed into the seat's turn, so it read the message: tell the board (best effort, never raises). The
        board uses the receipt so a close does not hint a message the seat already had in front of it."""
        if self._receipt is None or not mid:
            return
        try:
            self._receipt([mid])
        except Exception:  # noqa: BLE001 — a receipt is a courtesy; the wake must never fail on it
            pass

    def on_board(self, ev: dict) -> None:
        seq = ev.get("seq")
        mid = _message_id(ev)
        if _own_act(ev, self.participant):
            pass   # the seat's own act: no wake, the cursor still moves
        elif self.state.reserve(mid):
            try:
                line, partial = self._compose(ev, mid)
                self._emit(line)
                if ev.get("kind") == "message_sent":
                    self._seen(mid)
            except BaseException:
                self.state.release(mid)   # nothing was delivered: a restart replays it
                raise
            self.state.commit(mid, partial=partial)
            self._note(seq)
        elif isinstance(seq, int):
            self._note(seq)
        if isinstance(seq, int):
            self.state.advance(board_seq=seq)

    def on_broker(self, msg: dict) -> None:
        body = msg.get("body") if isinstance(msg.get("body"), dict) else {}
        mid = _message_id(msg)
        stale_status = msg.get("kind") == "status" and body.get("status") not in _STATUS_PAGES
        if stale_status or _own_act(msg, self.participant):
            pass
        elif self.state.is_partial(mid):
            line = _broker_completion(msg)
            if line is not None:
                self._emit(line)
                self._seen(mid)
                self.state.complete(mid)
                self._note()
        elif self.state.reserve(mid):
            try:
                self._emit({"broker_msg": msg})
                if body.get("board_msg_id"):
                    self._seen(mid)
            except BaseException:
                self.state.release(mid)
                raise
            self.state.commit(mid)
            self._note()
        self.state.advance(broker_ts=msg.get("ts"))


_READY_REFRESH_S = 30
_READY_FRESH_S = 120


def _ready_path(participant: str) -> Path:
    return _state_path(participant).with_suffix(".ready.json")


class Readiness:
    """The listener's proof of life for `subscribe()`: once a stream is usable it writes {pid, ts, owner} and keeps
    the ts fresh. `owner` says who started this listener: `mod` (the edp-wake mod, `--wake-owner mod`) or
    `monitor` (the default, a Monitor-run driver). A seat is told its wake plane is the mod only while a file
    owned by the mod is fresh and its pid is alive."""

    def __init__(self, participant: str, path: Path | None = None, owner: str = "monitor") -> None:
        self.path = path or _ready_path(participant)
        self.owner = owner
        self._started = False
        self._lock = threading.Lock()

    def write(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"pid": os.getpid(), "ts": time.time(), "owner": self.owner}), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass

    def mark_ready(self) -> None:
        with self._lock:
            self.write()
            if self._started:
                return
            self._started = True

        def keep_fresh() -> None:
            while True:
                time.sleep(_READY_REFRESH_S)
                self.write()

        threading.Thread(target=keep_fresh, name="ready-refresh", daemon=True).start()


def listener_ready(participant: str, *, wait_s: float = 0.0, max_age_s: float = _READY_FRESH_S,
                   path: Path | None = None, owner: str | None = None) -> bool:
    """True when a feed listener for this participant proved itself usable lately (fresh file, live pid). With
    `owner`, only a listener that owner started counts; a file without an owner is a Monitor's. Waits up to
    `wait_s` for it, since a mod starts its listener while the seat boots."""
    import psutil

    target = path or _ready_path(participant)
    deadline = time.monotonic() + wait_s
    while True:
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
            if (time.time() - float(raw["ts"]) <= max_age_s and psutil.pid_exists(int(raw["pid"]))
                    and (owner is None or raw.get("owner", "monitor") == owner)):
                return True
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.25)


_READINESS: Readiness | None = None


def _stream_usable(plane: str, health: Health | None) -> None:
    """A stream delivered its first ready or data frame: the plane is back, and this listener is alive."""
    if health:
        health.up(plane)
    if _READINESS is not None:
        _READINESS.mark_ready()


def _stream_board_once(board: str, participant: str, since: int, listener: Listener | None = None,
                       health: Health | None = None) -> int:
    """Stream board events; returns the last seen seq (or `since` if none arrived)."""
    last = since
    listener = listener or Listener(participant, FeedState(), note_wake=_note_wake)
    headers = _headers(participant)
    with httpx.Client(timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)) as client:
        with client.stream("GET", f"{board}/v1/feed", params={"since": last}, headers=headers) as resp:
            resp.raise_for_status()
            usable = False   # headers prove nothing: a stalled body must not flip lost/recovered every retry
            for line in resp.iter_lines():
                # `: ready N` ends the server's catch-up replay; `: resync N` (S22: a bounded feed
                # queue overflowed) ends the stream. Either cursor is where a reconnect resumes.
                mark = re.match(r":\s*(?:ready|resync)\s+(\d+)", line or "")
                if mark or (line and line.startswith("data: ")):
                    if not usable:
                        usable = True
                        _stream_usable("board", health)
                if mark:
                    last = max(last, int(mark.group(1)))
                    listener.state.advance(board_seq=last)
                    continue
                if not line or not line.startswith("data: "):
                    continue
                payload = line[len("data: "):]
                try:
                    ev = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                last = ev.get("seq", last)
                listener.on_board(ev)
    return last


def _stream_broker_once(broker: str, participant: str, since_ts: str | None, listener: Listener | None = None,
                        health: Health | None = None) -> str | None:
    """Stream the participant's broker inbox; returns the last seen msg ts."""
    last = since_ts
    listener = listener or Listener(participant, FeedState(), note_wake=_note_wake)
    params: dict[str, str] = {"recipient": participant}
    if last:
        params["since_ts"] = last
    with httpx.Client(timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)) as client:
        with client.stream("GET", f"{broker}/v1/events", params=params) as resp:
            resp.raise_for_status()
            usable = False
            for line in resp.iter_lines():
                if line and (line.startswith("data: ") or line.startswith(":")) and not usable:
                    usable = True   # a keep-alive comment proves the body works as much as a message does
                    _stream_usable("broker", health)
                if not line or not line.startswith("data: "):
                    continue
                payload = line[len("data: "):]
                try:
                    msg = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                last = msg.get("ts", last)
                listener.on_broker(msg)
    return last


def _retry_loop(plane: str, step: Any, health: Health, *, sleep: Any = time.sleep, rounds: int | None = None) -> None:
    """Run `step()` forever; a failure marks the plane down (one line) and backs off 1s -> 30s. `rounds` bounds
    the loop for tests."""
    backoff = 1.0
    n = 0
    while rounds is None or n < rounds:
        n += 1
        try:
            step()
            backoff = 1.0
        except Exception as e:  # noqa: BLE001
            health.down(plane, f"{type(e).__name__}: {e}")
            sleep(backoff)
            backoff = min(backoff * 2, 30.0)


def _state_path(participant: str) -> Path:
    root = os.environ.get("EDP8_FEED_STATE_DIR") or str(Path(tempfile.gettempdir()) / "edp8-feed")
    return Path(root) / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', participant)}.json"


def _broker_loop(broker: str, participant: str, listener: Listener, health: Health) -> None:
    from datetime import UTC, datetime

    # first start only: "now" (the inbox file is append-only and never consumed, so a fresh listener must not
    # replay the historic backlog). Every later start resumes from the saved cursor.
    if listener.state.broker_ts is None:
        listener.state.advance(broker_ts=datetime.now(UTC).isoformat())

    def step() -> None:
        _stream_broker_once(broker, participant, listener.state.broker_ts, listener, health)

    _retry_loop("broker", step, health)


def run() -> None:
    p = argparse.ArgumentParser(description="tail an edp8 board's event feed (and broker inbox) as NDJSON")
    p.add_argument("--participant", required=True)
    p.add_argument("--board", default="http://127.0.0.1:9400")
    p.add_argument("--broker", default=None, help="edp-broker base url; when set, the participant's inbox is merged in")
    p.add_argument("--since", type=int, default=-1)
    p.add_argument("--state", default=None, help="cursor file (default: EDP8_FEED_STATE_DIR or the temp dir)")
    p.add_argument("--wake-owner", default="monitor", choices=("monitor", "mod"),
                   help="who started this listener; the edp-wake mod passes `mod` (subscribe() trusts only that)")
    args = p.parse_args()

    state = FeedState(Path(args.state) if args.state else _state_path(args.participant))
    global _READINESS
    _READINESS = Readiness(args.participant, owner=args.wake_owner)
    health = Health()
    listener = Listener(args.participant, state, fetch=_http_fetch(args.board, args.participant),
                        note_wake=_note_wake, receipt=_http_receipt(args.board, args.participant))

    # line 1 is the listening contract (design §16.2 rule 5): what wakes this seat. Printed on the FIRST start
    # only; a restart repeating it woke the seat for nothing. Best-effort — an old board omits the route.
    if state.mark_banner():
        try:
            with httpx.Client(timeout=10.0) as c:
                r = c.get(f"{args.board}/v1/listening", headers=_headers(args.participant))
                if r.status_code == 200 and r.json().get("ok"):
                    _print({"listening": r.json()["value"]})
        except Exception as e:  # noqa: BLE001 — the stream is the job; the contract line is a courtesy
            _print({"listening_error": f"{type(e).__name__}: {e}"})

    if args.broker:
        threading.Thread(target=_broker_loop, args=(args.broker, args.participant, listener, health),
                         name="broker-inbox", daemon=True).start()

    global _HB
    interval = _heartbeat_interval()
    if interval > 0:
        _HB = Heartbeat(args.participant, _http_fetch(args.board, args.participant))
        threading.Thread(target=_heartbeat_loop, args=(_HB, interval), name="heartbeat", daemon=True).start()

    def board_step() -> None:
        if state.board_seq is not None:
            since = state.board_seq
        else:
            since = args.since
        _stream_board_once(args.board, args.participant, since, listener, health)

    _retry_loop("board", board_step, health)


if __name__ == "__main__":
    run()
