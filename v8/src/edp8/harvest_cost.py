"""Harvest token accounting (s-043eb90ccc; S23 moved it into the package so the board serves it as the
`harvest_cost` tool — scripts/harvest_cost.py is now a thin CLI over this module).

What one /harvest cost, measured from the seat's own session log, and who else wrote self-improvement
records in that window:

- the seat's log: a Claude seat's transcript (<pool claude config>/projects/**.jsonl, the one whose whoami
  result names the participant) or a codex seat's app-server mirror (<shell log dir>/**/codex-seat.<handle>.jsonl);
  the roots follow the settings, so an installed pool (data/claude-pool, data/logs) is searched as well as the
  old repo layout (edp-pool/.claude-pool, .logs) and the operator's own ~/.claude;
- the window: from the harvest trigger (Claude: the Skill("harvest") call or a Read of harvest/SKILL.md;
  codex: the first item naming harvest/SKILL.md; else the first harvest record call) to the seat's
  close_self (else the end of the log); since/until override it;
- tokens: Claude — usage summed over the assistant API calls in the window (one per message id);
  codex — thread/tokenUsage total at the window's end minus the total before it.
"""

from __future__ import annotations


import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from . import settings

BOARD_AUTHOR = "board"


def _dedupe(paths) -> tuple[Path, ...]:
    return tuple(dict.fromkeys(Path(p) for p in paths if p))


def default_roots() -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """(claude roots, codex roots) from the settings, read per call (S15: p-c98f480b, p-60fe5eac).
    Claude: the pool's CLAUDE_CONFIG_DIR/projects (dev <repo>/edp-pool/.claude-pool, installed <data>/claude-pool),
    the old edp-pool layout beside the agent home, and the operator's ~/.claude/projects.
    Codex: the pool's shell log dir (installed <data>/logs, dev <repo>/.logs; the mirror sits in its codex/ subdir),
    the platform log dir, and the old .logs beside and inside the agent home."""
    home = Path(settings.agent_home())
    claude = _dedupe([Path(settings.get("EDP_CLAUDE_CONFIG_DIR")) / "projects",
                      home.parent / "edp-pool" / ".claude-pool" / "projects",
                      Path.home() / ".claude" / "projects"])
    codex = _dedupe([settings.get("EDP_POOL_SHELL_LOG_DIR"), settings.logs_dir(), settings.data_dir() / "logs",
                     home.parent / ".logs", home / ".logs"])
    return claude, codex


def _roots() -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """(claude roots, codex roots): EDP8_HARVEST_LOG_ROOTS (os.pathsep list) overrides both — a board
    whose home is not the fleet agent home (a private audit board) still finds the host's seat logs."""
    extra = [Path(x) for x in (settings.get("EDP8_HARVEST_LOG_ROOTS") or "").split(os.pathsep) if x]
    return (tuple(extra), tuple(extra)) if extra else default_roots()


class NoLog(LookupError):
    """No session log for the seat under any searched root (T6 N4: the error names the roots, and `since`
    cannot help, so the hint never suggests it)."""

    def __init__(self, participant: str, roots: tuple[Path, ...]):
        self.roots = roots
        super().__init__(f"no session log found for {participant} under "
                         f"{', '.join(str(r) for r in roots) or 'no configured root'}")


class NoWindow(LookupError):
    """The log exists but holds no harvest trigger and no `since` was given."""


class LogUnreadable(LookupError):
    """The log was found but could not be read (locked, removed or denied)."""


class BadTime(ValueError):
    """`since` or `until` is not an ISO-8601 time or epoch seconds (a client mistake, never a server error)."""


def _ts(value: str | float | int | None) -> float | None:
    """ISO-8601 (Z or offset) or epoch seconds -> epoch seconds; None stays None."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
    except ValueError as exc:
        raise BadTime(f"{value!r} is not an ISO-8601 time or epoch seconds") from exc


def _row_ts(value: str | float | int | None) -> float | None:
    """A transcript row's time; a missing or garbled stamp is None (the row is skipped), never an error."""
    try:
        return _ts(value)
    except (BadTime, OverflowError, OSError):
        return None


def _iso(t: float | None) -> str | None:
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z") if t is not None else None


def _rows(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


# ----------------------------------------------------------------------------- finding the log
def _mtime(p: Path) -> float | None:
    try:
        return p.stat().st_mtime
    except OSError:  # the pool rotated or removed it while we scanned
        return None


def find_log(participant: str, claude_roots=None, codex_roots=None) -> tuple[str, Path] | None:
    """The participant's newest session log as (kind, path), kind 'claude' | 'codex'; None if none found."""
    if claude_roots is None or codex_roots is None:
        d_claude, d_codex = _roots()
        claude_roots = d_claude if claude_roots is None else claude_roots
        codex_roots = d_codex if codex_roots is None else codex_roots
    found: list[tuple[float, str, Path]] = []
    for root in codex_roots:
        if root.is_dir():
            found += [(m, "codex", p) for p in root.rglob(f"codex-seat.{participant}.jsonl")
                      if (m := _mtime(p)) is not None]
    needles = tuple(n.encode() for n in (f'"participant": {{"id": "{participant}"',
                                         f'\\"participant\\": {{\\"id\\": \\"{participant}\\"'))
    for root in claude_roots:
        if not root.is_dir():
            continue
        for p in root.rglob("*.jsonl"):
            try:
                data = p.read_bytes()
            except OSError:
                continue
            if any(n in data for n in needles) and (m := _mtime(p)) is not None:
                found.append((m, "claude", p))
    if not found:
        return None
    _, kind, path = max(found)
    return kind, path


# ----------------------------------------------------------------------------- Claude transcripts
def _claude_calls(rows: list[dict]):
    """(ts, tool name, input) for every tool_use block in assistant rows."""
    for r in rows:
        msg = r.get("message") or {}
        if r.get("type") != "assistant" or not isinstance(msg.get("content"), list):
            continue
        for b in msg["content"]:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                yield _row_ts(r.get("timestamp")), str(b.get("name") or ""), b.get("input") or {}


def _is_harvest_record(name: str, args: dict) -> bool:
    base = name.rsplit("__", 1)[-1]
    return base == "record_lesson" or (base == "doc_create" and args.get("status") == "proposed")


def claude_window(rows: list[dict]) -> tuple[float | None, float | None]:
    start = end = None
    first_record = None
    for ts, name, args in _claude_calls(rows):
        trigger = (name == "Skill" and str(args.get("skill", "")).endswith("harvest")) or \
                  (name == "Read" and str(args.get("file_path", "")).replace("\\", "/").endswith("harvest/SKILL.md"))
        if ts is None:  # no usable stamp: the call cannot anchor or close a window
            continue
        if start is None and trigger:
            start = ts
        if first_record is None and _is_harvest_record(name, args):
            first_record = ts
        if name.rsplit("__", 1)[-1] == "close_self" and (start or first_record) and ts >= (start or first_record):
            end = ts
    return (start or first_record), end


def claude_tokens(rows: list[dict], start: float, end: float | None) -> dict[str, int]:
    """Usage over the assistant API calls in [start, end], one per message id (a message split into
    several rows repeats its usage)."""
    seen: set[str] = set()
    tot = {"calls": 0, "input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
           "output_tokens": 0}
    for r in rows:
        msg = r.get("message") or {}
        ts = _row_ts(r.get("timestamp"))
        if r.get("type") != "assistant" or not msg.get("usage") or ts is None:
            continue
        if ts < start or (end is not None and ts > end):
            continue
        mid = msg.get("id") or r.get("uuid")
        if mid in seen:
            continue
        seen.add(mid)
        tot["calls"] += 1
        for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"):
            tot[k] += int(msg["usage"].get(k) or 0)
    return tot


# ----------------------------------------------------------------------------- codex seat mirrors
def codex_window(rows: list[dict]) -> tuple[float | None, float | None]:
    start = end = None
    first_record = None
    for r in rows:
        ts, m = r.get("ts"), r.get("msg") or {}
        if not isinstance(ts, (int, float)):
            continue
        item = (m.get("params") or {}).get("item") or {}
        # the skills/list catalog at boot names every skill path: only an item the model started counts
        if start is None and m.get("method") == "item/started" and item.get("type") != "mcpToolCall" \
                and "harvest/SKILL.md" in json.dumps(item).replace("\\\\", "/").replace("\\", "/"):
            start = ts
        if item.get("type") == "mcpToolCall":
            tool, args = str(item.get("tool") or ""), item.get("arguments") or {}
            if first_record is None and _is_harvest_record(tool, args if isinstance(args, dict) else {}):
                first_record = ts
            if tool == "close_self" and (start or first_record) and ts >= (start or first_record):
                end = ts
    return (start or first_record), end


def codex_tokens(rows: list[dict], start: float, end: float | None) -> dict[str, int]:
    """thread/tokenUsage `total` at the window's end minus the last total before it."""
    keys = ("inputTokens", "cachedInputTokens", "outputTokens", "reasoningOutputTokens", "totalTokens")
    calls = 0
    # S-ADV finding 6: a codex mirror is appended across threads and each thread's `total` restarts at 0,
    # so the window is summed PER THREAD (last total in the window minus the last total before it, per
    # threadId) — never one thread's end minus another thread's start (that went negative)
    before: dict[str, dict[str, int]] = {}
    after: dict[str, dict[str, int]] = {}
    for r in rows:
        m = r.get("msg") or {}
        if m.get("method") != "thread/tokenUsage/updated":
            continue
        params = m.get("params") or {}
        total = (params.get("tokenUsage") or {}).get("total") or {}
        thread = str(params.get("threadId") or params.get("thread_id") or "")
        ts = r.get("ts")
        if not isinstance(ts, (int, float)):
            continue
        snap = {k: int(total.get(k) or 0) for k in keys}
        if ts < start:
            before[thread] = snap
            after.pop(thread, None)
        elif end is None or ts <= end:
            after[thread] = snap
            calls += 1
    out = dict.fromkeys(keys, 0)
    for thread, a in after.items():
        b = before.get(thread) or dict.fromkeys(keys, 0)
        for k in keys:
            out[k] += a[k] - b[k]
    return {"calls": calls, **out}


# ----------------------------------------------------------------------------- board side
def board_records(board: str, participant: str, token: str | None, viewer: str) -> dict:
    req = urllib.request.Request(f"{board}/v1/knowledge", headers={"X-Participant": viewer, **({"X-Token": token} if token else {})})
    if not board.startswith(("http://", "https://")):
        raise ValueError(f"board url must be http(s): {board!r}")
    with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310  # scheme checked above
        return json.loads(resp.read().decode())["value"]


def records_in_window(view: dict, start: float, end: float | None) -> list[dict]:
    """Lessons and proposed docs (by status or provenance) created in [start, end]."""
    out = []
    for le in view.get("lessons", []):
        out.append({"id": le["id"], "kind": "lesson", "created_by": le["created_by"], "at": le["created_at"]})
    for d in view.get("docs", []):
        if d.get("status") == "proposed" or d.get("source"):
            out.append({"id": d["id"], "kind": f"proposed:{d.get('proposes') or 'new'}",
                        "created_by": d["created_by"], "at": d["created_at"]})
    stamped = [(r, _row_ts(r["at"])) for r in out]
    return [r for r, t in stamped if t is not None and start <= t and (end is None or t <= end)]



def compute(participant: str, *, since: str | None = None, until: str | None = None,
            knowledge: dict | None = None, log: Path | None = None) -> dict:
    """Bounded totals for one seat: window, token totals, and record counts (ids only, capped at 20).
    Raises LookupError when no log or no harvest window is found."""
    claude_roots, codex_roots = _roots()
    hit = (("codex" if log.name.startswith("codex-seat.") else "claude"), log) if log else find_log(participant, claude_roots, codex_roots)
    if hit is None or not hit[1].is_file():
        raise NoLog(participant, (log,) if log else tuple(dict.fromkeys((*claude_roots, *codex_roots))))
    kind, path = hit
    try:
        rows = _rows(path)
    except OSError as exc:
        raise LogUnreadable(f"{path.name} was found but cannot be read ({exc.__class__.__name__}: {exc})") from exc
    start, end = (claude_window if kind == "claude" else codex_window)(rows)
    s, u = _ts(since), _ts(until)
    start = s if s is not None else start
    end = u if u is not None else end
    if start is None:
        raise NoWindow(f"no harvest found in {participant}'s log (pass since)")
    tokens = (claude_tokens if kind == "claude" else codex_tokens)(rows, start, end)
    out = {"participant": participant, "seat": kind, "log": path.name,
           "window": {"start": _iso(start), "end": _iso(end)}, "tokens": tokens}
    if knowledge is not None:
        recs = records_in_window(knowledge, start, end)
        groups = {"by_participant": [r for r in recs if r["created_by"] == participant],
                  "board_auto": [r for r in recs if r["created_by"] == BOARD_AUTHOR],
                  "other_seats": [r for r in recs if r["created_by"] not in (participant, BOARD_AUTHOR)]}
        # no silent cut (owner m-891b9f42bd): past 20 ids the rest is counted and named
        out["records"] = {k: {"count": len(v), "ids": [r["id"] for r in v[:20]],
                              **({"ids_omitted": len(v) - 20,
                                  "rest": "harvest_cost(participant_id, since, until) with a narrower window"}
                                 if len(v) > 20 else {})}
                          for k, v in groups.items()}
    return out
