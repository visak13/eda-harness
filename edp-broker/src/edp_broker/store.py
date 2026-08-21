"""Durable inbox + alias stores (LLD §2). Append-only JSONL per recipient."""

import json
import os
import re
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path

from edp_contracts import BrokerMessage

_RECIPIENT_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class BadRecipient(Exception):
    """Recipient name is not filesystem-safe — surfaced as broker_no_route."""


def _safe(recipient: str) -> str:
    if not _RECIPIENT_RE.match(recipient or ""):
        raise BadRecipient(f"invalid recipient {recipient!r}")
    # 2026-05-21: filenames must be portable. Windows treats `:` as the
    # NTFS Alternate Data Stream separator (so `foo:bar.jsonl` writes
    # to ADS-stream `bar.jsonl` attached to file `foo`, invisible to
    # glob). Sanitize to `_` for the on-disk name; the recipient
    # identity in messages stays unchanged.
    return recipient.replace(":", "_")


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class AliasStore:
    """Relative-ref → concrete recipient. Populated by the pool (#4)."""

    def __init__(self, data: Path):
        self.path = Path(data) / "aliases.json"

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def put(self, owner: str, alias: str, target: str) -> None:
        d = self._load()
        d[f"{owner}/{alias}"] = target
        _write_atomic(self.path, json.dumps(d, indent=2))

    def put_absolute(self, alias: str, target: str) -> None:
        """Register an OWNERLESS (absolute) identity alias `alias → target`.

        s16 (2026-06-07): the pool registers a planner's colon EDP_HANDLE
        (`<recipe>:<step>`) → its dash inbox (`<recipe>-<step>`, the
        `whoami().self_address` it actually reads on). Unlike `put`, the
        key is the bare alias (no `owner/` prefix), so a sender targeting
        the visible colon handle is bridged to the live inbox instead of
        dead-lettering into the colon-sanitized `<recipe>_<step>.jsonl`."""
        d = self._load()
        d[alias] = target
        _write_atomic(self.path, json.dumps(d, indent=2))

    def resolve(self, recipient: str) -> str | None:
        """Concrete recipient → itself (or its absolute alias target if one
        is registered); 'owner/alias' relative ref → target or None.

        s16: a non-slash recipient now consults the alias map before
        falling back to identity, so an absolute colon→dash bridge (see
        `put_absolute`) reroutes a colon-handle publish to the live inbox.
        Backward-compatible: an unmapped concrete recipient → itself."""
        if "/" not in recipient:
            return self._load().get(recipient, recipient)
        return self._load().get(recipient)


class ChannelStore:
    """CHANNELS (topology 2026-07-21): a channel is an ordinary inbox
    PROMOTED to multi-reader by a durable membership record. The broker
    already makes any inbox multi-reader (reads are non-consuming); this
    registry is the source of truth for WHO is a member — the engine
    derives delivery (per-member cursors + `for:` filter) and the pool
    derives wakes (member-addressed mail resumes a parked member) from
    it. Registry only: creating a channel does not create the inbox
    file (the first message does, exactly like any recipient)."""

    def __init__(self, data: Path):
        self.path = Path(data) / "channels.json"
        # F45#7 — merge mutations serialize here so a member-add can never
        # be built from a stale row (the caller-side GET→PUT protocol let
        # two concurrent spawns erase each other's registration, and the
        # resume watchdog trusts this registry for @all wakes).
        self._merge_lock = threading.Lock()

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def put(self, name: str, members: list[str],
            topic: str = "") -> dict:
        if not _RECIPIENT_RE.match(name or ""):
            raise BadRecipient(f"invalid channel name {name!r}")
        d = self._load()
        row = {"members": sorted(set(m for m in members if m)),
               "topic": topic or d.get(name, {}).get("topic", "")}
        d[name] = row
        _write_atomic(self.path, json.dumps(d, indent=2))
        return {"channel": name, **row}

    def merge(self, name: str, add: list[str] | None = None,
              remove: list[str] | None = None,
              topic: str | None = None) -> dict:
        """F45#7 — atomic member/topic delta against the CURRENT row.
        Callers send what changed, never a whole membership list read
        moments ago (the stale GET→PUT protocol dropped concurrent
        registrations). Creates the channel when absent, like put."""
        if not _RECIPIENT_RE.match(name or ""):
            raise BadRecipient(f"invalid channel name {name!r}")
        with self._merge_lock:
            d = self._load()
            row = d.get(name) or {"members": [], "topic": ""}
            members = set(row.get("members", []))
            members |= {m for m in (add or []) if m}
            members -= set(remove or [])
            new_row = {"members": sorted(members),
                       "topic": (topic if topic is not None
                                 else row.get("topic", ""))}
            d[name] = new_row
            _write_atomic(self.path, json.dumps(d, indent=2))
        return {"channel": name, **new_row}

    def get(self, name: str) -> dict | None:
        row = self._load().get(name)
        return {"channel": name, **row} if row else None

    def list(self, member: str | None = None) -> list[dict]:
        d = self._load()
        out = [{"channel": k, **v} for k, v in sorted(d.items())]
        if member:
            out = [c for c in out if member in c["members"]]
        return out

    def delete(self, name: str) -> bool:
        d = self._load()
        if name not in d:
            return False
        del d[name]
        _write_atomic(self.path, json.dumps(d, indent=2))
        return True


class InboxStore:
    def __init__(self, data: Path):
        self.data = Path(data)
        self.aliases = AliasStore(self.data)
        self.channels = ChannelStore(self.data)
        # F34 R2 #6: per-inbox high-water ts cache, seeded lazily from the
        # file's last line. F44#4: appends are NO LONGER serialized on the
        # event loop (F36 moved store IO to worker threads), so the whole
        # tail-read/stamp/cache/append transaction takes this lock — two
        # concurrent publishes could both read tail T, both stamp T+1µs,
        # and the strict `ts > cursor` reader would hide one forever.
        self._last_ts: dict[Path, datetime] = {}
        self._append_lock = threading.Lock()

    def _file(self, recipient: str) -> Path:
        return self.data / f"{_safe(recipient)}.jsonl"

    def _tail_ts(self, p: Path) -> datetime | None:
        if p in self._last_ts:
            return self._last_ts[p]
        if not p.exists():
            return None
        last = None
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                last = BrokerMessage.model_validate_json(line).ts
            except Exception:  # noqa: BLE001 — torn line, keep scanning
                continue
        if last is not None:
            self._last_ts[p] = last
        return last

    def append(self, msg: BrokerMessage) -> None:
        target = self.aliases.resolve(msg.to)
        if target is None:
            raise BadRecipient(f"unresolved relative ref {msg.to!r}")
        p = self._file(target)
        p.parent.mkdir(parents=True, exist_ok=True)
        # F34 R2 #6 (2026-08-18): cursors are `ts > last_seen`, so a message
        # whose SENDER-stamped ts is <= an already-delivered one would be
        # hidden FOREVER (in-flight overlap, equal microseconds, a slow
        # sender). Stamp the ts forward at append so every inbox file is
        # strictly monotonic — the ts becomes "when the broker accepted it",
        # which is the order readers actually need.
        with self._append_lock:
            prev = self._tail_ts(p)
            if prev is not None and msg.ts <= prev:
                msg.ts = prev + timedelta(microseconds=1)
            self._last_ts[p] = msg.ts
            with open(p, "a", encoding="utf-8") as f:
                f.write(msg.model_dump_json(by_alias=True) + "\n")

    def read(
        self, recipient: str, since: datetime | None = None
    ) -> list[BrokerMessage]:
        # s16: resolve through the alias map so a read on the colon handle
        # (or any aliased form) lands on the same file `append` wrote to —
        # full append/read symmetry. Unmapped → identity (unchanged).
        recipient = self.aliases.resolve(recipient) or recipient
        p = self._file(recipient)
        if not p.exists():
            return []
        out: list[BrokerMessage] = []
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            # F34 R2 #11 (2026-08-18): a torn/corrupt line must not poison
            # the whole inbox — one half-written append used to make every
            # later valid message unreadable. Skip it; the valid mail flows.
            try:
                m = BrokerMessage.model_validate_json(line)
            except Exception:  # noqa: BLE001 — malformed line, not fatal
                continue
            # F34 R2 #7: colon→underscore sanitization is not injective
            # ('plan:a1' and 'plan_a1' share a file), so filter by the
            # message's RESOLVED destination — cross-delivery would let one
            # shell act on another's steer/answer.
            dest = self.aliases.resolve(m.to) or m.to
            if dest != recipient:
                continue
            if since is None or m.ts > since:
                out.append(m)
        return out

    def query(
        self,
        to: str | None = None,
        from_: str | None = None,
        kind: str | None = None,
        since: datetime | None = None,
    ) -> list[BrokerMessage]:
        """Cross-inbox GET query (object-model `message` reader). Scans
        every recipient inbox and filters server-side by to/from/kind/
        since — the inspect surface the neuron/planner use to see broker
        traffic they did NOT directly receive. Recipient-scoped `read`
        stays the hot path; this is the wide lens.

        Same O(N) scan caveat as get_message — fine at current volumes;
        TODO(broker-msg-index) covers both."""
        if not self.data.exists():
            return []
        if to is not None:
            files = [self._file(to)]
        else:
            files = sorted(self.data.glob("*.jsonl"))
        out: list[BrokerMessage] = []
        for p in files:
            if not p.exists():
                continue
            for line in p.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:  # F34 R2 #11 — torn line never poisons the query
                    m = BrokerMessage.model_validate_json(line)
                except Exception:  # noqa: BLE001
                    continue
                if from_ is not None and m.from_ != from_:
                    continue
                if kind is not None and m.kind != kind:
                    continue
                if since is not None and not (m.ts > since):
                    continue
                out.append(m)
        out.sort(key=lambda m: m.ts)
        return out

    def get_message(self, msg_id: str) -> BrokerMessage | None:
        """Look up a previously-sent message by id. Used by the
        `reply()` MCP tool to route an answer back to the original
        sender without the agent typing addressing.

        Scans inbox files (one per recipient). For high message
        volumes this should be indexed, but for now message counts
        per recipient are small. TODO(broker-msg-index): add an
        in-memory msg_id → file index for O(1) lookup."""
        if not self.data.exists():
            return None
        for p in self.data.glob("*.jsonl"):
            for line in p.read_text(encoding="utf-8").splitlines():
                if not line.strip() or msg_id not in line:
                    continue
                try:  # F34 R2 #11 — torn line never poisons the lookup
                    m = BrokerMessage.model_validate_json(line)
                except Exception:  # noqa: BLE001
                    continue
                if m.msg_id == msg_id:
                    return m
        return None
