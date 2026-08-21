"""Structured-text rendering for the MCP boundary (QoL F19).

Operator ruling (2026-08-21): "ensure that the mcp calls return text and
not json. json is completely unreadable. 'structured text' is much more
readable." Every tool result crosses the MCP boundary through
`render_result` — a ToolOk payload becomes headed `key: value` lines
(nested maps indented, lists bulleted, long text as an indented block),
a ToolError becomes one loud `ERROR` line carrying the message.

Rules that keep the output lean:
- `None` values and empty strings/lists/dicts are DROPPED — a payload
  full of nulls used to bury the three fields that mattered.
- Multiline / long strings render as an indented block under their key.
- Depth is bounded; a container past the cap renders as a labeled
  summary with a retrieval pointer (never raw JSON).
"""

from __future__ import annotations

_MAX_DEPTH = 5
_INLINE_STR = 96          # strings longer than this render as a block
_INDENT = "  "


def _is_empty(v: object) -> bool:
    return v is None or v == "" or v == [] or v == {}


def _scalar(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _render_value(key: str, v: object, depth: int, out: list[str]) -> None:
    pad = _INDENT * depth
    if _is_empty(v):
        return
    if depth >= _MAX_DEPTH:
        # Sol review 2026-08-21 #10: no raw JSON even at the depth cap —
        # containers get a labeled summary + retrieval pointer; scalars
        # render normally.
        if isinstance(v, dict):
            out.append(f"{pad}{key}: <nested map, keys: "
                       f"{', '.join(str(k) for k in v)}> "
                       "(depth cap — read_object the parent for the full "
                       "value)")
        elif isinstance(v, list):
            out.append(f"{pad}{key}: <list of {len(v)}> (depth cap — "
                       "read_object the parent for the full value)")
        else:
            out.append(f"{pad}{key}: {_scalar(v)}")
        return
    if isinstance(v, dict):
        out.append(f"{pad}{key}:")
        for k2, v2 in v.items():
            _render_value(str(k2), v2, depth + 1, out)
        if out[-1] == f"{pad}{key}:":      # everything inside was empty
            out.pop()
        return
    if isinstance(v, list):
        if all(isinstance(x, (str, int, float, bool)) for x in v):
            joined = ", ".join(_scalar(x) for x in v)
            if len(joined) <= _INLINE_STR:
                out.append(f"{pad}{key}: {joined}")
                return
        out.append(f"{pad}{key}:")
        for x in v:
            if isinstance(x, dict):
                first = True
                for k2, v2 in x.items():
                    if _is_empty(v2):
                        continue
                    lead = f"{pad}{_INDENT}- " if first else \
                        f"{pad}{_INDENT}  "
                    sub: list[str] = []
                    _render_value(str(k2), v2, 0, sub)
                    for i, line in enumerate(sub):
                        out.append((lead if first and i == 0 else
                                    f"{pad}{_INDENT}  ") + line)
                        first = False
            else:
                out.append(f"{pad}{_INDENT}- {_scalar(x)}")
        return
    s = _scalar(v)
    if isinstance(v, str) and ("\n" in s or len(s) > _INLINE_STR):
        out.append(f"{pad}{key}:")
        for line in s.splitlines() or [""]:
            out.append(f"{pad}{_INDENT}{line}")
        return
    out.append(f"{pad}{key}: {s}")


def render_payload(payload: dict, title: str = "") -> str:
    out: list[str] = []
    if title:
        out.append(f"[{title}]")
    for k, v in payload.items():
        _render_value(str(k), v, 0, out)
    if len(out) <= (1 if title else 0):
        out.append("ok")
    return "\n".join(out)


def render_result(name: str, res: object) -> str:
    """ToolOk/ToolError → the structured text the MCP client receives."""
    ok = bool(getattr(res, "ok", False))
    if not ok:
        code = getattr(res, "code", None)
        msg = getattr(res, "message", "") or ""
        code_s = getattr(code, "value", code) or "error"
        return f"ERROR [{name}] ({code_s}): {msg}"
    data = getattr(res, "data", None)
    if data is None:
        return f"[{name}] ok"
    payload = data if isinstance(data, dict) else data.model_dump(mode="json")
    return render_payload(payload, title=name)
