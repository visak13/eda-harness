"""Pure document edit/read contracts shared by HTTP and tool clients."""
import re

from pydantic import BaseModel, Field, model_validator


_ALIASES = {"old_string": "old_text", "new_string": "new_text"}


def _native(d: dict) -> dict:
    """The native Edit names (old_string/new_string) are the aliases of old_text/new_text."""
    out = {_ALIASES.get(k, k): v for k, v in d.items()}
    if len(out) < len(d):
        raise ValueError("pass old_string/new_string or old_text/new_text, not both")
    return out


class TextEdit(BaseModel):
    old_text: str = Field(min_length=1, description="Exact text in the original body")
    new_text: str
    replace_all: bool = False

    @model_validator(mode="before")
    @classmethod
    def _names(cls, v):
        return _native(v) if isinstance(v, dict) else v


class DocEdit(BaseModel):
    """The native Edit shape: top-level old_string/new_string/replace_all, or `edits` (a list of those).
    expected_version defaults to the version this reader was last served (the board fills it in)."""
    expected_version: int | None = Field(default=None, ge=1, description='version you read; default: last served')
    edits: list[TextEdit] = Field(default_factory=list, max_length=100, description='old_string/new_string pairs')
    title: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _top_level(cls, v):
        if not isinstance(v, dict):
            return v
        v = dict(v)
        keys = ("old_string", "new_string", "old_text", "new_text", "replace_all")
        one = {k: val for k in keys if (val := v.pop(k, None)) is not None}
        if one:
            if v.get("edits"):
                raise ValueError("pass top-level old_string/new_string or `edits`, not both")
            v["edits"] = [one]
        return v

    @model_validator(mode="after")
    def _some_edit(self):
        # after the field checks, so a missing `id` or an unknown arg is named first (test_s9_tool_matrix)
        if not self.edits:
            raise ValueError("pass old_string and new_string, or a non-empty `edits` list")
        return self


def edited_body(body: str, edits: list[TextEdit]) -> str:
    """Resolve all edits against original text, rejecting ambiguity and overlap. replace_all edits every occurrence."""
    from .board import BoardError
    spans = []
    for i, edit in enumerate(edits):
        hits, start = [], body.find(edit.old_text)
        while start >= 0:
            hits.append(start)
            start = body.find(edit.old_text, start + len(edit.old_text))
        if not hits or (len(hits) > 1 and not edit.replace_all):
            raise BoardError("edit_match", f"edit {i}: old_string must match exactly once ({len(hits)} found)",
                             "doc_read the current version, then retry with unique exact text, or replace_all=true")
        for h in hits if edit.replace_all else hits[:1]:
            spans.append((h, h + len(edit.old_text), edit.new_text))
    spans.sort()
    if any(a[1] > b[0] for a, b in zip(spans, spans[1:])):
        raise BoardError("edit_overlap", "edits overlap in the original body", "merge overlapping edits")
    for start, end, replacement in reversed(spans):
        body = body[:start] + replacement + body[end:]
    return body


def receipt(doc, fields: list[str]) -> dict:
    """A doc write's receipt; the body (and its size) is behind read_ref (S23 qa: no task may grow bytes). The
    named read is the head since S17 (architect m-c6cdb0602c); its continuation pages the whole body."""
    return {"id": doc.id, "version": doc.version, "changed_fields": fields,
            "layout": getattr(doc, "layout", "summary_first"), **legacy_note(doc),  # S13 F10
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


# S17 decision 1: every doc write names the skill; nothing checks a body's layout
DOC_WRITE_HINT = "small doc: plain prose; large doc: summary first; edit, don't rewrite (/doc-write)"

HEAD_CHARS = 8192  # the "first page": the doc-write skill promises the full summary fits in it
MAP_LEVELS = 3     # the heading map lists #..### headings; deeper ones are counted, not listed


PATH_SEP = " > "  # S13 F12: joins a heading path, e.g. "## Windows > ### Install"


def _chains(lines: list[str], heads: dict[int, int]) -> dict[int, list[str]]:
    """Each heading's ancestor chain of heading lines, itself last."""
    out, path = {}, []
    for i, level in heads.items():
        path = [p for p in path if p[0] < level] + [(level, lines[i].rstrip('\r\n'))]
        out[i] = [p[1] for p in path]
    return out


def _selectors(lines: list[str], heads: dict[int, int]) -> dict[int, str]:
    """S13 F12: each heading's section selector: its line when no other heading has the same line, else the
    shortest tail of its heading path (outermost first, PATH_SEP-joined) that no other heading shares. S18-4: when
    even the whole path is shared (repeated sibling headings), the path carries the occurrence, e.g.
    `# Manual > ## Example ⟨2⟩`, counted in document order within that version. The suffix never equals a literal
    heading line or path (a heading that really ends in `[2]` keeps its own selector)."""
    chains = _chains(lines, heads)
    literal = {PATH_SEP.join(c[-n:]) for c in chains.values() for n in range(1, len(c) + 1)}
    out = {}
    for i, chain in chains.items():
        tail = chain
        for n in range(1, len(chain) + 1):
            tail = chain[-n:]
            if not any(j != i and c[-n:] == tail for j, c in chains.items()):
                break
        else:
            same = [j for j, c in chains.items() if c == chain]
            out[i] = sel = _nth_selector(PATH_SEP.join(chain), same.index(i) + 1)
            while sel in literal:  # a heading that literally ends in the suffix: nest it once more
                out[i] = sel = _nth_selector(sel, same.index(i) + 1)
            continue
        out[i] = PATH_SEP.join(tail)
    return out


def _nth_selector(path: str, n: int) -> str:
    return f"{path} \u27e8{n}\u27e9"


_NTH = re.compile(r"^(.*?)\s*\u27e8(\d+)\u27e9$")  # S18-4: a selector's occurrence suffix, `path ⟨n⟩`


def _resolve_section(lines: list[str], heads: dict[int, int], section: str) -> int:
    """The heading line index a selector names: an exact heading line that is unique, or a heading path whose
    parts are the tail of exactly one heading's ancestor chain, or (S18-4) such a path with an occurrence suffix
    `⟨n⟩`, read only when the literal selector names no heading. Else section_match, naming the selectors."""
    from .board import BoardError
    exact = [i for i in heads if lines[i].rstrip('\r\n') == section]
    if len(exact) == 1:
        return exact[0]
    chains = _chains(lines, heads)

    def tail_of(sel):
        parts = [s.strip() for s in sel.split(PATH_SEP.strip())]
        return [i for i, c in chains.items() if len(c) >= len(parts) and [x.strip() for x in c[-len(parts):]] == parts]
    found = tail_of(section)
    if len(found) == 1:
        return found[0]
    sel = _selectors(lines, heads)
    nth = _NTH.match(section.strip()) if not (exact or found) else None
    if nth:  # S18-4: an occurrence selector names one heading; a wrong occurrence lists its siblings
        hit = [i for i, s in sel.items() if s == section.strip()]
        if hit:
            return hit[0]
        found = tail_of(nth[1])
    pick = _loose_section(lines, heads, section, sel)
    if isinstance(pick, int):
        return pick
    near = [sel[i] for i in (found or exact)][:6] or pick
    hint = "pass one of the candidates, or a `section` from the doc's map or a find hit"
    if _NUMISH.match(section):
        hint = ("section numbers count from 1 (`2`, `2.1`) and name the Nth heading of a level; otherwise pass a "
                "heading or a `section` from the doc's map. " + hint)
    raise BoardError("section_match", "section must name one heading: a unique heading line or a heading path"
                     + (f"; candidates: {near}" if near else ""), hint)


_NUM = re.compile(r"^\s*§?\s*(\d+(?:\.\d+)*)\.?\s*$")
_NUMISH = re.compile(r"^\s*§?\s*-?\d+(?:\.-?\d+)*\.?\s*$")
_LEAD_NUM = re.compile(r"^[#\s]*§?\s*(\d+(?:\.\d+)*)\.?(?=\s|$|[):\-–—])")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[`*_#]", "", text)).strip().lower()


def _positional(lines: list[str], heads: dict[int, int], parts: list[int]) -> int | None:
    """`3.2` = the 2nd subsection of the 3rd top section. Top sections are the H2s when the doc has one H1 title,
    else the shallowest level present."""
    levels = sorted(set(heads.values()))
    if not levels or any(n < 1 for n in parts):
        return None
    top = levels[1] if len(levels) > 1 and list(heads.values()).count(levels[0]) == 1 else levels[0]
    at, level = -1, top
    for n in parts:
        kids = []
        for i, lv in heads.items():
            if i <= at:
                continue
            if at >= 0 and lv < level:
                break
            if lv == level:
                kids.append(i)
        if n > len(kids):
            return None
        at, level = kids[n - 1], heads[kids[n - 1]] + 1
    return at


def _loose_section(lines: list[str], heads: dict[int, int], section: str, sel: dict[int, str]) -> int | list[str]:
    """A section number ("3", "3.2", "§3") or a near heading match. One hit = its line index; else the candidates."""
    num = _NUM.match(section)
    if num:
        hit = [i for i in heads if (m := _LEAD_NUM.match(lines[i])) and m[1] == num[1]]
        if len(hit) == 1:
            return hit[0]
        if not hit:
            at = _positional(lines, heads, [int(x) for x in num[1].split(".")])
            if at is not None:
                return at
        return [sel[i] for i in hit][:6]
    if _NUMISH.match(section):  # -1, 1.-2, 0 ...: a number that names no heading and cannot be a position
        return []
    want = _norm(re.sub(r"\s*>\s*", " > ", section))
    if not want:
        return []
    texts = {i: _norm(lines[i]) for i in heads}
    for test in (lambda t: t == want, lambda t: t.startswith(want), lambda t: want in t):
        hit = [i for i, t in texts.items() if test(t)]
        if len(hit) == 1:
            return hit[0]
        if hit:
            return [sel[i] for i in hit][:6]
    import difflib
    close = difflib.get_close_matches(want, list(texts.values()), n=6, cutoff=0.6)
    hit = [i for i, t in texts.items() if t in close]
    if len(hit) == 1 and len(close) == 1:
        return hit[0]
    return [sel[i] for i in hit][:6]


def heading_map(body: str) -> list[dict]:
    """Every ATX section (fences ignored) as {h: section selector, at: char offset, chars: section size incl.
    its subsections}. The same boundaries bounded_read(section=…) cuts on, so `h` is a ready section argument: the
    heading line, or its heading path when another heading has the same line (S13 F12)."""
    lines = body.splitlines(keepends=True)
    heads = _headings(lines)
    sel = _selectors(lines, heads)
    pos = [0]
    for ln in lines:
        pos.append(pos[-1] + len(ln))
    out = []
    for i, level in heads.items():
        end = next((j for j, lv in heads.items() if j > i and lv <= level), len(lines))
        out.append({"h": sel[i], "level": level, "at": pos[i], "chars": pos[end] - pos[i]})
    return out


UNIT_CHARS = 1500  # a search unit's text cap: under the embedder's window, so no part of a doc goes unembedded


def _paragraphs(text: str, cap: int) -> list[str]:
    """`text` cut at blank lines into chunks of at most `cap` chars (a longer paragraph is hard-cut)."""
    out, cur = [], ""
    for para in re.findall(r".*?(?:\n[ \t]*\n|\Z)", text, re.S):
        while len(para) > cap:
            if cur:
                out.append(cur)
                cur = ""
            out.append(para[:cap])
            para = para[cap:]
        if cur and len(cur) + len(para) > cap:
            out.append(cur)
            cur = ""
        cur += para
    if cur.strip():
        out.append(cur)
    return out


def doc_units(title: str, body: str, *, cap: int = UNIT_CHARS) -> list[tuple[str | None, str]]:
    """S17 decision 4: a doc's search units, one per section (a heading's own text, up to the next heading of any
    level), a long section or a heading-less body cut at paragraphs. Each is (heading line or None, text), the text
    led by the title and the heading path so every unit carries its context. Same boundaries as heading_map."""
    lines = body.splitlines(keepends=True)
    heads = _headings(lines)
    sel = _selectors(lines, heads)
    starts = [0] + [i for i in heads if i > 0]
    path: list[tuple[int, str]] = []
    out: list[tuple[str | None, str]] = []
    for n, s in enumerate(starts):
        e = starts[n + 1] if n + 1 < len(starts) else len(lines)
        own = "".join(lines[s:e])
        h = None
        if s in heads:
            h = sel[s]  # S13 F12: the selector doc_read(section=) resolves, even for a repeated heading
            path = [p for p in path if p[0] < heads[s]] + [(heads[s], lines[s].rstrip("\r\n").lstrip("# ").strip())]
        lead = " > ".join([title] + [p[1] for p in path])
        if not own.strip() and n:
            continue
        for chunk in _paragraphs(own, max(cap // 2, cap - len(lead) - 1)) or [own]:
            out.append((h, f"{lead}\n{chunk}"))
    return out


def _page_end(body: str, limit: int, sections: list[dict]) -> int:
    """Where the first page stops: the whole body when it fits, else the last section start past half the page,
    else the last blank line, else the limit."""
    if len(body) <= limit:
        return len(body)
    starts = [s["at"] for s in sections if limit // 2 < s["at"] <= limit]
    if starts:
        return starts[-1]
    cut = body.rfind("\n\n", limit // 2, limit)
    return cut + 1 if cut != -1 else limit


def legacy_note(doc) -> dict:
    from .schemas import LEGACY_WARNING
    return {"warning": LEGACY_WARNING} if getattr(doc, "layout", "summary_first") == "legacy" else {}


def head_read(doc, *, limit: int = HEAD_CHARS, served=None) -> dict:
    """S17 decision 3: the default doc read. The first page (the summary, when the writer followed the doc-write
    skill), the heading map with each section's size, and the calls that read on; a legacy doc carries the
    warning line. The whole body is HTTP-only (all=true, for people and their editors; architect m-c6cdb0602c)."""
    body = doc.body_md
    sections = heading_map(body)
    stop = _page_end(body, limit, sections)
    listed = [{"h": s["h"], "chars": s["chars"]} for s in sections if s["level"] <= MAP_LEVELS]
    meta = {k: getattr(getattr(doc, k, None), "value", getattr(doc, k, None))
            for k in ("scope", "status", "owner_role", "tags", "proposes", "resolution")}
    out = {"id": doc.id, "version": doc.version, "title": doc.title,
           "doc_type": getattr(doc.doc_type, "value", doc.doc_type),
           **{k: v for k, v in meta.items() if v not in (None, [])},
           "layout": getattr(doc, "layout", "summary_first"), **legacy_note(doc),
           "body_md": body[:stop], "total_chars": len(body), "complete": stop >= len(body)}
    if served:
        start, end, line = served(0, stop)
        out["body_md"] = body[start:end]
        if start:
            out["offset"] = start
        if line:
            out["already_read"] = line
    if stop < len(body):
        # S13 F9 (ruling: advisory, no parsing, no enforcement; owner m-ee0717d276): the layout is the writer's
        # declaration, so the head never promises that page 1 holds everything
        out["note"] = "page 1 is the writer's summary, not checked: read the map sections your work touches"
        out["map"] = listed
        if len(listed) < len(sections):
            out["map_deeper_headings"] = len(sections) - len(listed)
        out["continuation"] = {"page": {"id": doc.id, "version": doc.version, "offset": stop},
                               "section": f"doc_read(id={doc.id!r}, section=<an h from map>)"}
    return out


def bounded_read(doc, *, offset: int = 0, limit: int = 8192, section: str | None = None,
                 include_children: bool = False, served=None) -> dict:
    """Character ranges pinned to a version; section is an exact Markdown heading line. A section read returns the
    section's own text, up to its first subsection, plus `children` (each direct subsection's heading and size), so
    a parent and a child are never read twice (architect m-8c4f0d64cb); include_children=true returns the section
    with every subsection's body. `section` is a unique heading line or a heading path (S13 F12)."""
    body = doc.body_md
    children = None
    base = 0
    if section is not None:
        lines = body.splitlines(keepends=True)
        headings = _headings(lines)
        start = _resolve_section(lines, headings, section)
        depth = headings[start]
        end = next((i for i, level in headings.items() if i > start and level <= depth), len(lines))
        if not include_children:
            inner = [s for s in heading_map(body) if start < _line_of(lines, s["at"]) < end]
            # a direct child: no earlier subsection of a higher level holds it
            children = [{"h": s["h"], "chars": s["chars"]} for n, s in enumerate(inner)
                        if all(p["level"] >= s["level"] for p in inner[:n])]
            end = next((i for i in headings if start < i < end), end)
        base = sum(len(ln) for ln in lines[:start])
        body = ''.join(lines[start:end])
    stop = min(offset + limit, len(body))
    more = stop < len(body)
    first, shown, line = offset, stop, None
    if served:
        first, shown, line = served(base + offset, base + stop)
        first, shown = first - base, shown - base
    # S17: a range read is often one small section, so the envelope carries only what the reader acts on: the
    # version it pins to, the text and its size, and a continuation/child map when there is more (m-8c4f0d64cb)
    out = {"id": doc.id, "version": doc.version, **legacy_note(doc), "body_md": body[first:shown],
           "total_chars": len(body)}
    if first:
        out["offset"] = first
    if line:
        out["already_read"] = line
    if more:
        out["truncated"] = True
        out["continuation"] = {"id": doc.id, "version": doc.version, "offset": stop, "limit": limit,
                               "section": section, **({"include_children": True} if include_children else {})}
    if children:
        out["children"] = children
    return out


def _line_of(lines: list[str], at: int) -> int:
    """The line index that starts at char offset `at`."""
    pos = 0
    for i, ln in enumerate(lines):
        if pos == at:
            return i
        pos += len(ln)
    return len(lines)


class ReadLedger:
    """Already-read (note-e6ddb85977 §3): the char ranges of each (doc id, version) this participant was served
    since its last resume_self. In memory in the board process, per participant; a new version starts empty."""

    def __init__(self) -> None:
        import threading
        self._lock = threading.Lock()
        self._rows: dict[tuple[str, str], tuple[int, list[list[int]]]] = {}

    def last_version(self, who: str, doc_id: str) -> int | None:
        """The version of `doc_id` this participant was last served, or None."""
        with self._lock:
            row = self._rows.get((who, doc_id))
        return row[0] if row else None

    def wrote(self, who: str, doc_id: str, version: int) -> None:
        """The writer's own new version is the one it holds (it knows what it wrote): later edits default to it."""
        with self._lock:
            self._rows[(who, doc_id)] = (version, [])

    def clear(self, who: str) -> None:
        with self._lock:
            for k in [k for k in self._rows if k[0] == who]:
                del self._rows[k]

    def serve(self, who: str, doc_id: str, version: int, a: int, b: int) -> tuple[int, int, str | None]:
        """The part of [a, b) not yet sent, as (start, stop, line); records what is sent. Leading and trailing
        sent text is trimmed; sent text between two unsent gaps is sent again with them."""
        if b <= a:
            return a, b, None
        with self._lock:
            ver, spans = self._rows.get((who, doc_id), (version, []))
            if ver != version:
                spans = []
            gaps, pos = [], a
            for s, e in spans:
                if e <= pos or s >= b:
                    continue
                if s > pos:
                    gaps.append((pos, s))
                pos = max(pos, e)
            if pos < b:
                gaps.append((pos, b))
            first = next(((s, e) for s, e in spans if s < b and e > a), None)
            start, stop = (gaps[0][0], gaps[-1][1]) if gaps else (a, a)
            if gaps:
                spans = _merge(spans + [[start, stop]])
            self._rows[(who, doc_id)] = (version, spans)
        if first is None:
            return start, stop, None
        have = f"you already have {max(first[0], 0):,}–{first[1]:,} of v{version}"
        tail = "ask with `fresh=true` for the whole range"
        if not gaps:
            return start, stop, f"{have}, all you asked for; {tail}"
        where = f"this continues from {start:,}" if start > a else f"this sends {start:,}–{stop:,} only"
        return start, stop, f"{have}; {where}; {tail}"

    def record(self, who: str, doc_id: str, version: int, a: int, b: int) -> None:
        with self._lock:
            ver, spans = self._rows.get((who, doc_id), (version, []))
            self._rows[(who, doc_id)] = (version, _merge((spans if ver == version else []) + [[a, b]]))


def _merge(spans: list[list[int]]) -> list[list[int]]:
    out: list[list[int]] = []
    for s, e in sorted(spans):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def section_hint(description: str, doc) -> str:
    """note-e6ddb85977 §2: '' when the description names a heading of `doc`, else the reminder with its top headings.
    A heading is named by its text or by its leading §<n> token."""
    heads = [h for h in heading_map(doc.body_md) if 2 <= h["level"] <= MAP_LEVELS]
    if not heads:
        return ""
    low = (description or "").lower()
    titles = []
    for h in heads:
        title = h["h"].lstrip("# ").strip() if h["h"].lstrip().startswith("#") else h["h"]
        titles.append(title)
        tok = re.match(r"§\s*[\w.]+", title)
        if title.lower() in low or (tok and re.search(re.escape(tok.group(0).lower()) + r"(?!\w|\.\w)", low)):
            return ""
    return f"description names no section of {doc.id}; its top headings are: " + "; ".join(titles[:8])
