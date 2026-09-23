"""edp8 ruleset assembly — the v7 `assemble_ruleset` mechanism ported onto board docs.

A worker's behavior is an additive composition of layers:

    universal / high-level strategy  →  extends-chains  →  low-level craft / domain

resolved **universal-first, most-specific-last**. Layering is declared on the
board: a doc `extends` another doc via a Link(relation=extends). A later layer
may ADD but never DELETE an earlier one — structural, since each layer is a
separate doc.

The assembled ruleset is split into two VIEWS for the two consumers:
CONSTRUCTIVE (how to build — the worker's view) and ENFORCED (what to check —
the reviewer/adversary's adherence view). A line is ENFORCED when it is a
checkbox (`- [ ]`), carries an adherence tag (`[required]`, `[expected]`,
`[preferred]`), or sits under a heading containing "checklist" or "enforced".

No context weight (S-LIBRARY, design-34bf11cc07 §4.4): the brief a seat receives INLINES only
the ENFORCED lines; every layer doc appears once in `index` (id, title, tags, approx tokens) for
the seat to doc_read when its work touches it — knowledge "like skills but dynamic": loaded by
link and on demand, never by default. The oversize check applies to the inlined part only. The
full constructive view is still computed and returned when the caller asks (`full=True`).

This module is pure: it takes `load(doc_id) -> LayerDoc | None` and
`extends_of(doc_id) -> list[str]` callables so it is testable without the
board service.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from pydantic import BaseModel

# a composed brief bigger than this is a scoping defect to split, not to truncate
OVERSIZE_TOKENS = 24_000

_ADHERENCE_RX = re.compile(r"\[(required|expected|preferred)\]", re.IGNORECASE)
_ENFORCED_HEADING_RX = re.compile(r"^#+\s.*(checklist|enforced)", re.IGNORECASE)
_HEADING_RX = re.compile(r"^#+\s")


class AssembleError(Exception):
    """A layering could not be resolved (cycle or missing layer). Carries an
    instruction-shaped message the tool surfaces verbatim — never a crash,
    never a silent partial assembly."""

    def __init__(self, instruction: str):
        super().__init__(instruction)
        self.instruction = instruction


class LayerDoc(BaseModel):
    id: str
    title: str
    doc_type: str
    body_md: str
    tags: list[str] = []


class RulesetLine(BaseModel):
    text: str
    layer: str  # the doc id this line came from (provenance)


class IndexLine(BaseModel):
    """One layer doc, listed instead of inlined: the seat doc_reads it on demand."""
    id: str
    title: str
    doc_type: str
    tags: list[str]
    approx_tokens: int  # the whole doc body
    line: str  # "id · title · tags · ~N tokens" — the one line a brief prints


INDEX_INSTRUCTION = ("enforced lines are inlined; every linked doc is one `index` line — doc_read(id) the ones "
                     "your work touches (constructive craft lives there), before you build on them")


class AssembledRuleset(BaseModel):
    leaf_doc_ids: list[str]
    layers: list[str]                # ordered doc ids: universal-first … most-specific-last
    layer_titles: dict[str, str]     # doc id -> "title (doc_type)"
    enforced: list[RulesetLine]      # WHAT to check — the adherence view (inlined)
    index: list[IndexLine]           # every layer doc, one line each (read on demand)
    instruction: str
    constructive: list[RulesetLine] | None = None  # HOW to build — only with full=True
    approx_tokens: int               # the INLINED part: enforced + index lines
    full_tokens: int                 # what inlining everything would cost (constructive + enforced)
    oversize: bool                   # on the inlined part only


def _resolve_layers(
    load: Callable[[str], LayerDoc | None],
    extends_of: Callable[[str], list[str]],
    leaf_doc_ids: list[str],
) -> list[LayerDoc]:
    """Post-order DFS over `extends`, deduped, so the result is
    universal-first / most-specific-last. Cycles and missing layers raise."""
    ordered: list[LayerDoc] = []
    placed: set[str] = set()

    def walk(doc_id: str, path: frozenset[str]) -> None:
        if doc_id in path:
            chain = " -> ".join([*path, doc_id])
            raise AssembleError(
                f"extends cycle detected ({chain}); a doc cannot extend itself "
                f"transitively. Fix the `extends` link of one of these docs."
            )
        doc = load(doc_id)
        if doc is None:
            raise AssembleError(
                f"layer {doc_id!r} does not exist. It is referenced via an "
                f"`extends` link or given as a leaf. Create it or drop the "
                f"link — do NOT proceed with a partial ruleset."
            )
        for parent in extends_of(doc_id):
            walk(parent, path | {doc_id})
        if doc_id not in placed:
            placed.add(doc_id)
            ordered.append(doc)

    for leaf in leaf_doc_ids:
        walk(leaf, frozenset())
    return ordered


def _split_lines(doc: LayerDoc) -> tuple[list[str], list[str]]:
    """(constructive, enforced) lines of one doc body."""
    constructive: list[str] = []
    enforced: list[str] = []
    in_enforced_section = False
    for raw in doc.body_md.splitlines():
        line = raw.rstrip()
        if _HEADING_RX.match(line):
            in_enforced_section = bool(_ENFORCED_HEADING_RX.match(line))
            continue  # headings are structure, not rules
        if not line.strip():
            continue
        stripped = line.strip()
        is_enforced = (
            in_enforced_section
            or stripped.startswith("- [ ]")
            or stripped.startswith("- [x]")
            or bool(_ADHERENCE_RX.search(stripped))
        )
        (enforced if is_enforced else constructive).append(line)
    return constructive, enforced


def _tokens(text_len: int) -> int:
    return text_len // 4


def assemble_ruleset(
    load: Callable[[str], LayerDoc | None],
    extends_of: Callable[[str], list[str]],
    leaf_doc_ids: list[str],
    *,
    full: bool = False,
) -> AssembledRuleset:
    """Resolve + split the layered ruleset. Additive union across layers,
    deduped on the stripped line text keeping the FIRST (most-universal)
    occurrence, so a leaf that restates a universal rule doesn't double it.
    Enforced lines are inlined; each layer is one index line; `full` adds constructive."""
    if not leaf_doc_ids:
        raise AssembleError(
            "no leaf docs to assemble. Link strategy/domain docs to the ticket "
            "(relation=uses_strategy|uses_domain) or pass doc_ids explicitly."
        )
    layers = _resolve_layers(load, extends_of, leaf_doc_ids)

    constructive: list[RulesetLine] = []
    enforced: list[RulesetLine] = []
    seen: set[str] = set()
    for doc in layers:
        c_lines, e_lines = _split_lines(doc)
        for text in c_lines:
            key = text.strip()
            if key in seen:
                continue
            seen.add(key)
            constructive.append(RulesetLine(text=text, layer=doc.id))
        for text in e_lines:
            key = text.strip()
            if key in seen:
                continue
            seen.add(key)
            enforced.append(RulesetLine(text=text, layer=doc.id))

    index = []
    for d in layers:
        n = _tokens(len(d.body_md))
        tags = ", ".join(d.tags) if d.tags else "untagged"
        index.append(IndexLine(id=d.id, title=d.title, doc_type=d.doc_type, tags=list(d.tags), approx_tokens=n,
                               line=f"{d.id} · {d.title} ({d.doc_type}) · {tags} · ~{n} tokens"))
    enforced_chars = sum(len(x.text) for x in enforced)
    inlined = _tokens(enforced_chars + sum(len(x.line) for x in index) + len(INDEX_INSTRUCTION))
    return AssembledRuleset(
        leaf_doc_ids=leaf_doc_ids,
        layers=[d.id for d in layers],
        layer_titles={d.id: f"{d.title} ({d.doc_type})" for d in layers},
        enforced=enforced,
        index=index,
        instruction=INDEX_INSTRUCTION,
        constructive=constructive if full else None,
        approx_tokens=inlined,
        full_tokens=_tokens(sum(len(x.text) for x in constructive) + enforced_chars),
        oversize=inlined > OVERSIZE_TOKENS,
    )
