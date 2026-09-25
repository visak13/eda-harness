"""C18 quotes on messages (design-10b21760d9 §14.5): the door rules, the verification against the
source and the agent-facing render. The board is the trust point: a quote it stores says what its
source said at that version, so it re-derives what it can (heading, sha) and refuses the rest."""
from __future__ import annotations

import hashlib
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .schemas import CodeContext, Participant, QuoteContext, QuoteLocator, QuoteStored, Role

MAX_QUOTES = 20
TEXT_MAX_B = 4096      # a passage, in UTF-8 bytes (the S4 snippet cap)
CONTEXT_MAX = 500      # context.before / context.after, in characters
NOTE_MAX = 2000        # the sender's note on one passage (steer m-d735e11c27)
CONTEXT_REACH = 3      # a doc quote's context must sit within this many lines of its range
PASSAGE_CAP = 600      # passage chars a byte-bounded read (context, delta, feed) renders per quote
NOTE_CAP = 400         # note chars a byte-bounded read renders per quote
QUOTED_CAP = 2000      # the whole rendered block in a byte-bounded read (20 x the per-quote caps is too much)
HEADING_MAX = 200      # a derived heading is one doc line; stored clipped


MISMATCH, MISSING = "quote_mismatch", "quote_source_missing"  # the route answers these with 422


class _LocatorIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    heading: str | None = None  # accepted and ignored: the board derives it


class _ContextIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    before: str = Field(default="", max_length=CONTEXT_MAX)
    after: str = Field(default="", max_length=CONTEXT_MAX)


class QuoteIn(BaseModel):
    """The door rules for one quote (a typo'd field is named, not dropped)."""
    model_config = ConfigDict(extra="forbid")
    source: Literal["doc", "message", "code"]
    id: str | None = Field(default=None, min_length=1, max_length=128)
    version: int | None = Field(default=None, ge=1)
    locator: _LocatorIn | None = None
    text: str | None = None
    context: _ContextIn | None = None
    note: str | None = Field(default=None, max_length=NOTE_MAX)
    sha: str | None = None
    code: CodeContext | None = None

    @field_validator("text")
    @classmethod
    def _cap(cls, v: str | None) -> str | None:
        if v is not None and len(v.encode("utf-8")) > TEXT_MAX_B:
            raise ValueError(f"must be at most {TEXT_MAX_B} UTF-8 bytes")
        return v


def _norm(s: str) -> str:
    """Whitespace normalisation, the only difference a quote may have from its source."""
    return " ".join(s.split())


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _err(code: str, i: int, msg: str, hint: str = "") -> Exception:
    from .board import BoardError  # local: board imports this module's render helpers
    return BoardError(code, f"quotes[{i}]: {msg}",
                      hint or "fix the named quote; see describe('message') for quote rules")


def readable(actor: Participant, source: str, obj: Any) -> bool:
    """May `actor` read this quoted source? Mirrors the read routes (GET /v1/messages/{id},
    GET /v1/docs/{id}): every participant but an expert (its token reaches only its Library topic).
    One place, so a later per-reader scope tightens quoting with it (architect m-55480f6f8e)."""
    return actor.role != Role.expert


_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s{0,3}(```|~~~)")


def heading_at(lines: list[str], line_no: int) -> str | None:
    """The nearest markdown heading at or above 1-based `line_no`, ignoring `#` lines in code fences."""
    found, fence = None, None
    for ln in lines[:line_no]:
        f = _FENCE.match(ln)
        if f:  # a fence closes only with the marker that opened it
            fence = f.group(1) if fence is None else (None if f.group(1) == fence else fence)
            continue
        m = None if fence else _HEADING.match(ln)
        if m and m.group(2):
            found = m.group(2)
    return found if found is None or len(found) <= HEADING_MAX else found[:HEADING_MAX - 1] + "…"


def section_label(heading: str | None) -> str:
    """`§14.5` for a numbered heading (`14.5 Quotes: …`, `5. Work`), else `§<heading>` clipped."""
    if not heading:
        return ""
    m = re.match(r"(\d+(?:\.\d+)*)\.?(?:\s|$)", heading)
    label = m.group(1) if m else (heading if len(heading) <= 60 else heading[:59] + "…")
    return f"§{label}"


def _bad_fields(q: QuoteIn, i: int, *names: str) -> None:
    extra = [n for n in names if getattr(q, n) is not None]
    if extra:
        raise _err("schema", i, f"a {q.source} quote takes no {', '.join(extra)}")


def _check_context(q: QuoteIn, i: int, before: str, after: str) -> QuoteContext | None:
    """context.before must occur just above the passage, context.after just below it."""
    if q.context is None or not (q.context.before.strip() or q.context.after.strip()):
        return None
    for side, region in (("before", before), ("after", after)):
        part = getattr(q.context, side)
        if part.strip() and _norm(part) not in region:
            raise _err(MISMATCH, i, f"context.{side} does not occur next to the passage in the source")
    return QuoteContext(before=q.context.before, after=q.context.after)


def _one(board: Any, actor: Participant, q: QuoteIn, i: int) -> QuoteStored:
    if q.source == "code":
        _bad_fields(q, i, "id", "version", "locator", "context")
        if q.code is None:
            raise _err("schema", i, "a code quote needs `code` (a code_context object)")
        if q.text is not None and q.text != q.code.snippet:
            raise _err(MISMATCH, i, "text must equal code.snippet")
        text = q.code.snippet
        loc, ctx, extra = QuoteLocator(), None, {}
    else:
        _bad_fields(q, i, "code")
        if not q.id:
            raise _err("schema", i, f"a {q.source} quote needs `id`")
        if q.text is None or not q.text.strip():
            raise _err("schema", i, "text must not be blank")
        text, needle = q.text, _norm(q.text)
        missing = _err(MISSING, i, f"{q.source} {q.id!r}{f' v{q.version}' if q.version else ''} does not exist",
                       "quote a source you can read, at a version it has")
        if q.source == "doc":
            if q.version is None:
                raise _err("schema", i, "a doc quote needs `version`")
            lo = q.locator
            if lo is None or lo.line_start is None or lo.line_end is None:
                raise _err("schema", i, "a doc quote needs locator.line_start and locator.line_end")
            if lo.char_start is not None or lo.char_end is not None:
                raise _err("schema", i, "a doc quote is located by lines, not characters")
            if lo.line_end < lo.line_start:
                raise _err("schema", i, "locator.line_end must be >= line_start")
            doc = board.store.doc_version(q.id, q.version) if board.store.get("doc", q.id) else None
            if doc is None or not readable(actor, "doc", doc):
                raise missing
            lines = (doc.body_md or "").replace("\r\n", "\n").split("\n")
            if lo.line_end > len(lines):
                raise _err(MISMATCH, i, f"lines {lo.line_start}-{lo.line_end} are outside {q.id} v{q.version} "
                                        f"({len(lines)} lines)")
            if needle not in _norm("\n".join(lines[lo.line_start - 1:lo.line_end])):
                raise _err(MISMATCH, i, f"text does not occur in {q.id} v{q.version} "
                                        f"L{lo.line_start}-{lo.line_end}", "re-copy the passage from that version")
            ctx = _check_context(q, i, _norm("\n".join(lines[max(0, lo.line_start - 1 - CONTEXT_REACH):lo.line_start])),
                                 _norm("\n".join(lines[lo.line_end - 1:lo.line_end + CONTEXT_REACH])))
            loc = QuoteLocator(heading=heading_at(lines, lo.line_start), line_start=lo.line_start,
                               line_end=lo.line_end)
            extra = {"id": q.id, "version": q.version}
        else:
            _bad_fields(q, i, "version")
            src = board.store.get("message", q.id)
            if src is None or not readable(actor, "message", src):
                raise missing
            lo = q.locator
            if lo is not None and (lo.line_start is not None or lo.line_end is not None):
                raise _err("schema", i, "a message quote is located by characters, not lines")
            cs = lo.char_start if lo else None
            ce = lo.char_end if lo else None
            if (cs is None) != (ce is None) or (cs is not None and (ce < cs or ce > len(src.text))):
                raise _err("schema", i, f"locator.char_start/char_end must both be set, 0 <= start <= end <= {len(src.text)}")
            region = src.text[cs:ce] if cs is not None else src.text
            if needle not in _norm(region):
                raise _err(MISMATCH, i, f"text does not occur in message {q.id}", "re-copy the passage from it")
            whole = _norm(src.text)
            at = whole.find(needle)
            ctx = _check_context(q, i, whole[:at + len(needle)], whole[at:])
            loc = QuoteLocator(char_start=cs, char_end=ce)
            extra = {"id": q.id, "author": src.created_by}
    sha = _sha(text)
    if q.sha is not None and q.sha != sha:
        raise _err("schema", i, "sha must be the sha256 hex of text")
    note = q.note if q.note and q.note.strip() else None
    return QuoteStored(source=q.source, locator=loc, text=text, context=ctx, note=note, sha=sha,
                       code=q.code, **extra)


def quotes_in(board: Any, actor: Participant, raw: Any) -> list[QuoteStored]:
    """Validate and verify a message's quotes (in order). A malformed quote is a 400 naming its field;
    one the board cannot verify is a 422 (quote_mismatch / quote_source_missing)."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        from .board import BoardError
        raise BoardError("schema", f"quotes: must be a list, not {type(raw).__name__}",
                         "send quotes as a list of objects; see describe('message')")
    if len(raw) > MAX_QUOTES:
        from .board import BoardError
        raise BoardError("schema", f"quotes: at most {MAX_QUOTES} per message, got {len(raw)}",
                         "split the quotes over several messages")
    out = []
    for i, item in enumerate(raw):
        try:
            q = QuoteIn.model_validate(item)
        except ValidationError as e:
            bad = []
            for err in e.errors():
                loc = ".".join(str(x) for x in err.get("loc", ()))
                bad.append(f"{loc or 'quote'}: {err.get('msg')}")
            raise _err("schema", i, "; ".join(bad)) from None
        out.append(_one(board, actor, q, i))
    return out


def _clip(s: str, n: int | None) -> str:
    return s if n is None or len(s) <= n else s[:n].rstrip() + f"… (+{len(s) - n} chars; message_read for all)"


def source_line(q: QuoteStored) -> str:
    """`— design-… v11 §14.5 L12-15`, `— m-… (author)` or `— code path:Lx-y @sha7`."""
    if q.source == "doc":
        lo = q.locator
        parts = [f"{q.id} v{q.version}", section_label(lo.heading), f"L{lo.line_start}-{lo.line_end}"]
        return "— " + " ".join(p for p in parts if p)
    if q.source == "message":
        return f"— {q.id} ({q.author or 'unknown'})"
    return f"— code {q.code.at()}" if q.code else "— code"


def render_quote(q: QuoteStored, capped: bool = False) -> str:
    passage = _clip(q.text, PASSAGE_CAP if capped else None)
    out = [*("> " + ln if ln else ">" for ln in passage.split("\n")), source_line(q)]
    if q.note:  # the sender's words: continuation lines are indented, so a note can never pose as a
        # verified `> passage` / `— source` pair (C18 review finding)
        note = _clip(q.note, NOTE_CAP if capped else None).split("\n")
        out.append("note: " + "\n      ".join(ln.rstrip() for ln in note))
    return "\n".join(out)


def render_quotes(quotes: list[QuoteStored], capped: bool = False) -> str:
    block = "\n\n".join(render_quote(q, capped) for q in quotes)
    return _clip(block, QUOTED_CAP) if capped else block


def compact(q: QuoteStored) -> dict[str, Any]:
    """A quote's reference without its bodies (text, context, note, snippet): what a byte-bounded
    read keeps beside the rendered `quoted` block."""
    return q.model_dump(mode="json", include={"source", "id", "version", "author", "locator", "sha"},
                        exclude_none=True)


def with_quotes(row: dict[str, Any], m: Any, capped: bool = False) -> dict[str, Any]:
    """`row` with the rendered `quoted` block placed just before `text`, so an agent reads the cited
    passages above the message. A capped read also replaces raw `quotes` with compact references."""
    quotes = getattr(m, "quotes", None) or []
    if not quotes:
        return row
    quoted = render_quotes(quotes, capped)
    out: dict[str, Any] = {}
    for k, v in row.items():
        if k == "text":
            out["quoted"] = quoted
        if k != "quoted":
            out[k] = v
    out.setdefault("quoted", quoted)
    if capped or "quotes" in out:
        out["quotes"] = [compact(q) for q in quotes] if capped else [q.model_dump(mode="json") for q in quotes]
    return out
