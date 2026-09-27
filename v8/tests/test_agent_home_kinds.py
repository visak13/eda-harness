"""T3 F3 (report-6971109e05): the agent home never tells a seat to use a `kind` the tools refuse.

`message_send(kind='blocked')` was in guides/agent-tools.md and `kind=blocked` in shared-host-rules.md and the
heartbeat prompt; the kind enum has no `blocked`, so a seat's first try was an arg miss. Every `kind=<word>` in
the cards, skills, guides and CLAUDE.md must be a message kind or a ticket kind; blocking is
record_status(status=blocked) plus a deviation or question.
"""

from __future__ import annotations

import re
from pathlib import Path

from edp8.schemas import MessageKind, TicketKind

V8 = Path(__file__).resolve().parent.parent
HOME = [*sorted((V8 / ".claude" / "commands").glob("*.md")), *sorted((V8 / ".claude" / "skills").rglob("*.md")),
        *sorted((V8 / "guides").glob("*.md")), V8 / "CLAUDE.md"]
ALLOWED = {k.value for k in MessageKind} | {k.value for k in TicketKind}
KIND = re.compile(r"""\bkind\s*=\s*['"]?([A-Za-z_]+)""")


def test_agent_home_names_only_real_kinds():
    bad = []
    for path in HOME:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            bad += [f"{path.relative_to(V8)}:{n}: kind={k}" for k in KIND.findall(line) if k not in ALLOWED]
    assert not bad, "message/ticket kinds outside the enums:\n" + "\n".join(bad)


def test_tool_text_never_says_kind_blocked():
    hits = [f"{p.relative_to(V8)}" for p in (V8 / "src" / "edp8").rglob("*.py")
            if re.search(r"kind\s*=\s*['\"]?blocked", p.read_text(encoding="utf-8"))]
    assert not hits, f"kind=blocked is not a message kind: {hits}"
