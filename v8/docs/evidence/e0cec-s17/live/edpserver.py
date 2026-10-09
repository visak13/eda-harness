"""S17 completeness lab: an MCP server named `lab` exposing the REAL edp8 tool handlers (ticket_read, doc_read, find)
over an in-memory board loaded with one lab epic (summary-first `pyr` docs). Every call is logged with its chars.
Env: S17_WT (worktree v8 dir), LAB_ROOT (ctxlab), LAB_EPIC (A|B), LAB_DOCS (pyr|orig), LAB_LOG."""
import json
import os
import pathlib
import sys
import time

WT = pathlib.Path(os.environ["S17_WT"])
sys.path[:0] = [str(WT / "src"), str(WT / "scripts")]
import s17_cost_replay as R  # noqa: E402  (isolates the env: no seat vars, embedder none, temp home)
from mcp.server.mcpserver import MCPServer as FastMCP  # noqa: E402

LAB = pathlib.Path(os.environ["LAB_ROOT"])
EPIC, DOCS = os.environ.get("LAB_EPIC", "A"), os.environ.get("LAB_DOCS", "pyr")
LOG = pathlib.Path(os.environ["LAB_LOG"])
rig = R.Rig()


def load():
    src = LAB / "plan" / EPIC / DOCS
    index = json.loads((src / "index.json").read_text(encoding="utf-8"))
    links = json.loads((src / "links.json").read_text(encoding="utf-8"))["extends"]
    stories = json.loads((src / "stories.json").read_text(encoding="utf-8"))
    e = rig.post("owner", "/v1/tickets", {"kind": "epic", "work_type": "feature", "title": f"lab epic {EPIC}"})["id"]
    ids = {}
    for lab_id, meta in index.items():
        body = (src / f"{lab_id}.md").read_text(encoding="utf-8")
        design = lab_id.endswith("-design")
        ids[lab_id] = rig.post("arch" if design else "owner", "/v1/docs", {
            "doc_type": "design" if design else "strategy_ll", "title": meta["title"], "body_md": body,
            "scope": e if design else "global"})["id"]
    for child, parents in links.items():
        for p in parents:
            rig.post("owner", "/v1/links", {"from_id": ids[child], "to_id": ids[p], "relation": "extends"})
    tickets = {}
    for s in stories:
        t = rig.post("arch", "/v1/tickets", {"kind": "story", "work_type": "feature", "title": s["title"],
                                             "parent_id": e, "assignee": "eng",
                                             "description": f"{s['description']}\n\nDesign: {s['design_section']}"})["id"]
        rig.post("arch", "/v1/links", {"from_id": t, "to_id": ids[s["design_doc"]], "relation": "designed_by"})
        for d in s["linked_docs"]:
            rig.post("arch", "/v1/links", {"from_id": t, "to_id": ids[d], "relation": "uses_strategy"})
        for c in s["criteria"]:
            text = f"{c['id']}: {c['text']}" if isinstance(c, dict) else str(c)
            rig.post("arch", "/v1/criteria", {"ticket_id": t, "text": text[:2000], "check": "command"})
        tickets[s["id"]] = t
    return tickets


TICKETS = load()
mcp = FastMCP("lab")
DESC = {n: R.ALL_TOOLS[n].description for n in ("ticket_read", "doc_read", "find")}


def _call(name, **args):
    args = {k: v for k, v in args.items() if v is not None}
    try:
        out = rig.tool("eng", name, **args)
    except Exception as ex:  # noqa: BLE001 — the seat sees the error, as over the real MCP server
        out = {"ok": False, "error": str(ex)}
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.time(), "tool": name, "args": args, "chars": R.chars(out)}) + "\n")
    return out


@mcp.tool(description=DESC["ticket_read"])
def ticket_read(ticket_id: str, include: str | None = None) -> dict:
    return _call("ticket_read", ticket_id=TICKETS.get(ticket_id, ticket_id), include=include)


@mcp.tool(description=DESC["doc_read"])
def doc_read(id: str, version: int | None = None, offset: int | None = None, limit: int | None = None,
             section: str | None = None, include_children: bool = False) -> dict:
    return _call("doc_read", id=id, version=version, offset=offset, limit=limit, section=section,
                 include_children=include_children or None)


@mcp.tool(description=DESC["find"])
def find(query: str, k: int = 10, types: str | None = None) -> dict:
    return _call("find", query=query, k=k, types=types)


if __name__ == "__main__":
    mcp.run()
