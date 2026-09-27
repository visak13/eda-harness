"""S23 bounded list output: every list/query tool returns count + a page of compact rows + next_cursor,
and no default call exceeds ~8 KB (T1 audit: ticket_query 472 KB, doc_query 270 KB, participants 87 KB in
one line). verbose=true returns full rows (still paged); the cap and the continuation are named in the
result's `page` receipt.

Two cursor kinds, both opaque base64 JSON bound to the query's filters:
- offset ({"o": n}) over a filtered list the board returns whole (tickets, docs, links, sessions, people);
- seq ({"s": seq}) over an append-only stream the board pages itself (messages, events).
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any, Callable

from . import settings

DEFAULT_LIMIT = 25
MAX_LIMIT = 100
_PAGE_CAP_B = 8_000


def page_cap() -> int:
    """EDP8_TOOL_PAGE_B overrides the per-call byte cap (default 8000)."""
    try:
        return max(2_000, int(settings.get("EDP8_TOOL_PAGE_B")))
    except (KeyError, ValueError, TypeError):
        return _PAGE_CAP_B


def nbytes(obj: Any) -> int:
    return len(json.dumps(obj, ensure_ascii=True, default=str).encode("utf-8"))


def clip(s: Any, n: int) -> Any:
    if not isinstance(s, str) or len(s) <= n:
        return s
    return s[:n].rstrip() + f"… (+{len(s) - n} chars)"


def _qhash(filters: dict[str, Any]) -> str:
    raw = json.dumps({k: (v.value if hasattr(v, "value") else v) for k, v in sorted(filters.items())},
                     default=str, sort_keys=True)
    return hashlib.sha1(raw.encode()).hexdigest()[:10]


def encode_cursor(filters: dict[str, Any], **pos: Any) -> str:
    raw = json.dumps({"q": _qhash(filters), **pos}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


class CursorError(ValueError):
    pass


def decode_cursor(cursor: str | None, filters: dict[str, Any]) -> dict[str, Any]:
    if not cursor:
        return {}
    try:
        pad = "=" * (-len(cursor) % 4)
        got = json.loads(base64.urlsafe_b64decode(cursor + pad))
    except (ValueError, TypeError) as e:
        raise CursorError("cursor is not one this tool returned") from e
    if not isinstance(got, dict) or got.get("q") != _qhash(filters):
        raise CursorError("cursor belongs to a different query — repeat the same filters with it, or drop it")
    return got


def cursor_error(tool: str, e: CursorError) -> dict[str, Any]:
    return {"ok": False, "error": {"code": "schema", "field": "cursor", "message": f"{tool}: {e}"},
            "hint": "pass next_cursor from the previous page with the same filters; omit cursor for page 1"}


def _fit(rows: list[Any], cap: int, overhead: int) -> list[Any]:
    """The longest prefix of rows that fits the cap (at least one row, whatever its size)."""
    out: list[Any] = []
    used = overhead
    for r in rows:
        b = nbytes(r) + 1
        if out and used + b > cap:
            break
        out.append(r)
        used += b
    return out


def _lossy(raw: list[Any], shown: list[Any]) -> bool:
    """Did the compact projection drop or clip anything a row carried? (empty values are not information)"""
    for r, p in zip(raw, shown):
        if isinstance(r, dict) and p != {k: v for k, v in r.items() if v not in (None, "", [], {})}:
            return True
    return False


def _receipt(tool: str, cap: int, next_cursor: str | None, lossy: bool, full: str) -> dict[str, Any]:
    """What was cut and the exact call that fetches the rest (owner m-891b9f42bd: no silent truncation):
    `continue` + the cap when rows remain, `full_rows` when a row was compacted (a clipped field ends in
    "(+N chars)"). A page that cut nothing carries no receipt."""
    rec: dict[str, Any] = {}
    if next_cursor:
        rec.update(cap_b=cap, **{"continue": f"{tool}(<same filters>, cursor=next_cursor)"})
    if lossy:
        rec["full_rows"] = full
    return rec


def offset_page(tool: str, rows: list[Any], *, filters: dict[str, Any], limit: int | None, cursor: str | None,
                verbose: bool, project: Callable[[dict[str, Any]], dict[str, Any]], full: str) -> dict[str, Any]:
    """Page a whole filtered list by offset. Returns the tool envelope's `value`."""
    pos = decode_cursor(cursor, filters)
    off = int(pos.get("o") or 0)
    lim = max(1, min(limit or DEFAULT_LIMIT, MAX_LIMIT))
    cap = page_cap()
    window = rows[off:off + lim]
    items = [r if verbose or not isinstance(r, dict) else project(r) for r in window]
    items = items if verbose else _fit(items, cap, 400)
    nxt = off + len(items)
    next_cursor = encode_cursor(filters, o=nxt) if nxt < len(rows) else None
    lossy = not verbose and _lossy(window, items)
    return {"count": len(rows), **({"offset": off} if off else {}), "items": items,
            "next_cursor": next_cursor, "page": _receipt(tool, cap, next_cursor, lossy, full)}


def seq_page(tool: str, rows: list[Any], *, filters: dict[str, Any], limit: int, verbose: bool,
             project: Callable[[dict[str, Any]], dict[str, Any]], full: str, seq_key: str = "seq",
             more_possible: bool) -> dict[str, Any]:
    """Page a seq-ordered stream the board already cut to `limit`: next_cursor resumes after the last
    returned seq. `more_possible` is whether the board filled the page."""
    cap = page_cap()
    items = [r if verbose or not isinstance(r, dict) else project(r) for r in rows]
    fitted = items if verbose else _fit(items, cap, 400)
    cut = len(fitted) < len(items)
    last = next((r.get(seq_key) for r in reversed(fitted) if isinstance(r, dict) and r.get(seq_key) is not None),
                None)
    next_cursor = encode_cursor(filters, s=last) if last is not None and (cut or more_possible) else None
    lossy = not verbose and _lossy(rows, fitted)
    return {"items": fitted, "last_seq": last, "next_cursor": next_cursor,
            "page": _receipt(tool, cap, next_cursor, lossy, full)}


def seq_hint(value: dict[str, Any], since_arg: str) -> str:
    """The resume hint of a seq page, computed from the page RETURNED, never the board's batch (T3 F1: the REST
    hint named the batch's last seq after the page was fitted, so following it skipped messages)."""
    last = value.get("last_seq")
    if last is None:
        return f"no rows; repeat with the same {since_arg} later for new ones"
    more = "more remain: " if value.get("next_cursor") else ""
    return f"{more}last_seq={last} is the last row shown; pass cursor=next_cursor or {since_arg}={last} to continue"


def pick(row: dict[str, Any], keys: tuple[str, ...], clips: dict[str, int] | None = None) -> dict[str, Any]:
    clips = clips or {}
    return {k: clip(row.get(k), clips[k]) if k in clips else row.get(k)
            for k in keys if row.get(k) not in (None, "", [], {})}
