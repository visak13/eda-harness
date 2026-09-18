"""Pure document edit/read contracts shared by HTTP and tool clients."""
import re

from pydantic import BaseModel, Field


class TextEdit(BaseModel):
    old_text: str = Field(min_length=1, description="Exact unique text in the original body")
    new_text: str


class DocEdit(BaseModel):
    expected_version: int = Field(ge=1)
    edits: list[TextEdit] = Field(min_length=1, max_length=100)
    title: str | None = None


def edited_body(body: str, edits: list[TextEdit]) -> str:
    """Resolve all edits against original text, rejecting ambiguity and overlap."""
    from .board import BoardError
    spans = []
    for i, edit in enumerate(edits):
        start = body.find(edit.old_text)
        if start < 0 or body.find(edit.old_text, start + 1) >= 0:
            raise BoardError("edit_match", f"edit {i}: old_text must match exactly once",
                             "doc_read the current version, then retry with unique exact text")
        spans.append((start, start + len(edit.old_text), edit.new_text))
    spans.sort()
    if any(a[1] > b[0] for a, b in zip(spans, spans[1:])):
        raise BoardError("edit_overlap", "edits overlap in the original body", "merge overlapping edits")
    for start, end, replacement in reversed(spans):
        body = body[:start] + replacement + body[end:]
    return body


def receipt(doc, fields: list[str]) -> dict:
    return {"id": doc.id, "version": doc.version, "changed_fields": fields,
            "read_ref": {"tool": "doc_read", "id": doc.id, "version": doc.version}}


def _headings(lines: list[str]) -> dict[int, int]:
    """ATX section boundaries, ignoring backtick/tilde fenced code contents."""
    headings = {}
    fence = None
    for i, line in enumerate(lines):
        match = re.match(r' {0,3}(`{3,}|~{3,})(.*)$', line.rstrip('\r\n'))
        if fence is not None:
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence) and not match[2].strip():
                fence = None
            continue
        if match:
            if match[1][0] != '`' or '`' not in match[2]:
                fence = match[1]
            continue
        match = re.match(r' {0,3}(#{1,6})(?:[ \t]+|$)', line)
        if match:
            headings[i] = len(match[1])
    return headings


def bounded_read(doc, *, offset: int = 0, limit: int = 8192, section: str | None = None) -> dict:
    """Character ranges pinned to a version; section is an exact Markdown heading line."""
    from .board import BoardError
    body = doc.body_md
    if section is not None:
        lines = body.splitlines(keepends=True)
        headings = _headings(lines)
        matches = [i for i in headings if lines[i].rstrip('\r\n') == section]
        if len(matches) != 1:
            raise BoardError("section_match", "section must be a unique exact Markdown heading line")
        start = matches[0]
        depth = headings[start]
        end = next((i for i, level in headings.items() if i > start and level <= depth), len(lines))
        body = ''.join(lines[start:end])
    stop = min(offset + limit, len(body))
    more = stop < len(body)
    return {"id": doc.id, "version": doc.version, "title": doc.title,
            "body_md": body[offset:stop], "offset": offset, "total_chars": len(body),
            "truncated": more, "continuation":
            {"id": doc.id, "version": doc.version, "offset": stop, "limit": limit, "section": section}
            if more else None}
