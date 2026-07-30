"""Durable inbox + alias stores (LLD §2). Append-only JSONL per recipient."""

import json
import os
import re
import tempfile
from datetime import datetime
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

    def _file(self, recipient: str) -> Path:
        return self.data / f"{_safe(recipient)}.jsonl"

    def append(self, msg: BrokerMessage) -> None:
        target = self.aliases.resolve(msg.to)
        if target is None:
            raise BadRecipient(f"unresolved relative ref {msg.to!r}")
        p = self._file(target)
        p.parent.mkdir(parents=True, exist_ok=True)
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
            m = BrokerMessage.model_validate_json(line)
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
                m = BrokerMessage.model_validate_json(line)
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
                m = BrokerMessage.model_validate_json(line)
                if m.msg_id == msg_id:
                    return m
        return None
