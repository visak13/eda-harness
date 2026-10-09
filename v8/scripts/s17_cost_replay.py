"""S17 cost replay (design-f39cf0db7d, Measurement topic): a deterministic replay of the doc reads, find calls and
writes the plan-lab tasks make, through the REAL MCP tool handlers (`bundles.ALL_TOOLS`) on an in-memory board.

usage: python scripts/s17_cost_replay.py <ctxlab dir> <real-docs dir> <out.json> [--label before|after]

Counts JSON chars a seat receives (read) and sends + receives on writes (written). Nothing here reads the fleet
board: the 3 real docs are snapshots (`<real-docs dir>/<id>.json`, the GET /v1/docs/{id} envelope) kept outside
the repo; only the numbers are written out.

Per story (A1-A3, B1-B3), on the dummy docs as written ("orig") and as summary-first copies ("pyr"):
  reads   context(story) · ticket_read(story) · the ruleset tool(story) while it exists ·
          doc_read(id) for every doc the codex full-read trace read ·
          head-first only: the section/offset reads the codex brief-pyr trace made (what a head-first seat pulls),
          totalled on their own line (section_read; architect m-d125e8ccd1); a section wholly inside the head page
          the seat already holds is counted (sections_in_head), not re-read ·
          find(q) for the story's fixed queries
  writes  doc_create(the story's codex plan) · one section revision: doc_update(whole body) while doc_read
          returns the whole doc, doc_edit(one edit) once it is head-first (the doc-write skill's revision path)
Real docs: doc_read(id) default + one find each, and the same section-revision write.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import tempfile  # noqa: E402

# an isolated board, as tests/conftest.py makes it: no seat/host env (bind, tokens), no pool watcher
for k in [k for k in os.environ if k.startswith(("EDP8_", "EDP_"))]:
    os.environ.pop(k)
os.environ["EDP8_EMBEDDER"] = "none"
os.environ["EDP8_TOKENS"] = str(Path(tempfile.mkdtemp()) / "absent-tokens.json")
for k in ("EDP_POOL_URL", "EDP8_POOL_WATCH", "EDP_POOL_HOST"):
    os.environ.pop(k, None)
os.environ["EDP_POOL_PORT"] = "9"
os.environ["EDP8_HOME"] = tempfile.mkdtemp()
os.environ["EDP_DEV"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from edp8.board import Board  # noqa: E402
from edp8.bundles import ALL_TOOLS, set_client, tools_for_role  # noqa: E402

RETIRED = [n for n in ALL_TOOLS if n.endswith("_ruleset")]
from edp8.client import BoardClient  # noqa: E402
from edp8.service import create_app  # noqa: E402
from edp8.store import Store  # noqa: E402

ADMIN = {"X-Admin": "t"}
STORIES = {"A": ["A1", "A2", "A3"], "B": ["B1", "B2", "B3"]}
# fixed find queries per story: the story id plus the plain-word forms of the codex brief traces' searches
QUERIES = {"A1": ["partial refunds", "refund_lines allocation"], "A2": ["reconciliation", "PR-7 mismatch report"],
           "A3": ["kill switch", "dry run verification"], "B1": ["secret scope", "offline sync"],
           "B2": ["shared note field merge", "conflict resolution"], "B3": ["release train", "protocol version"]}
REAL_QUERIES = {"design-b6a55eed13": "asks ledger", "design-f39cf0db7d": "legacy warning",
                "note-0db5502c85": "answer key"}


def chars(x) -> int:
    return len(json.dumps(x, ensure_ascii=False))


class Rig:
    def __init__(self):
        self.http = TestClient(create_app(Board(Store(":memory:")), admin_token="t"))
        for pid, role, typ in [("owner", "owner", "human"), ("arch", "architect", "agent"),
                               ("eng", "engineer", "agent"), ("sme", "sme", "agent")]:
            r = self.http.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                               headers=ADMIN).json()
            assert r["ok"], r

    def post(self, who, path, body):
        r = self.http.post(path, json=body, headers={"X-Participant": who}).json()
        assert r["ok"], (path, r)
        return r["value"]

    def tool(self, who, name, **args):
        set_client(BoardClient(participant=who, client=self.http))
        t = ALL_TOOLS[name]
        return t.handler(t.args_model(**args))


def load_epic(rig: Rig, lab: Path, epic: str, docs: str):
    src = lab / "plan" / epic / docs
    index = json.loads((src / "index.json").read_text(encoding="utf-8"))
    links = json.loads((src / "links.json").read_text(encoding="utf-8"))["extends"]
    stories = json.loads((src / "stories.json").read_text(encoding="utf-8"))
    e = rig.post("owner", "/v1/tickets", {"kind": "epic", "work_type": "feature", "title": f"lab epic {epic}"})["id"]
    ids = {}
    for lab_id, meta in index.items():
        body = (src / f"{lab_id}.md").read_text(encoding="utf-8")
        is_design = lab_id.endswith("-design")
        d = rig.post("arch" if is_design else "owner", "/v1/docs", {
            "doc_type": "design" if is_design else "strategy_ll", "title": meta["title"], "body_md": body,
            "scope": e if is_design else "global"})
        ids[lab_id] = d["id"]
    for child, parents in links.items():
        for p in parents:
            rig.post("owner", "/v1/links", {"from_id": ids[child], "to_id": ids[p], "relation": "extends"})
    out = {}
    for s in stories:
        t = rig.post("arch", "/v1/tickets", {"kind": "story", "work_type": "feature", "title": s["title"],
                                             "parent_id": e, "description": s["description"],
                                             "assignee": "eng"})["id"]
        rig.post("arch", "/v1/links", {"from_id": t, "to_id": ids[s["design_doc"]], "relation": "designed_by"})
        for d in s["linked_docs"]:
            rig.post("arch", "/v1/links", {"from_id": t, "to_id": ids[d], "relation": "uses_strategy"})
        for c in s["criteria"]:
            text = c if isinstance(c, str) else (c.get("text") or json.dumps(c))
            rig.post("arch", "/v1/criteria", {"ticket_id": t, "text": text[:2000], "check": "command"})
        out[s["id"]] = t
    return e, ids, out


def trace(lab: Path, run: str, sid: str) -> list[dict]:
    p = lab / "presults" / run / f"{sid}.calls.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def head_first() -> bool:
    return "include_children" in ALL_TOOLS["doc_read"].args_model.model_fields


def revise_one_section(rig: Rig, who: str, doc_id: str, body: str) -> tuple[int, int]:
    """One section revision: (chars sent, chars received). Appends a line to the first section."""
    lines = body.splitlines(keepends=True)
    anchor = next((ln for ln in lines if ln.startswith("## ")), lines[0] if lines else body)
    if body.count(anchor) != 1:
        anchor = body[: min(len(body), 200)]
    new = anchor + "Revised: one added line.\n"
    if head_first():
        args = {"id": doc_id, "expected_version": 1, "edits": [{"old_text": anchor, "new_text": new}]}
        out = rig.tool(who, "doc_edit", **args)
    else:
        args = {"id": doc_id, "body_md": body.replace(anchor, new, 1)}
        out = rig.tool(who, "doc_update", **args)
    assert out.get("ok"), out
    return chars(args), chars(out)


def run_story(rig, lab, epic, docs, sid, ticket, ids, row):
    rd = lambda **a: row.__setitem__("read", row["read"] + chars(rig.tool("eng", "doc_read", **a)))  # noqa: E731
    for name, args in (("context", {"ticket_id": ticket}), ("ticket_read", {"ticket_id": ticket})):
        out = rig.tool("eng", name, **args)
        row["read"] += chars(out)
        row["calls"][name] = chars(out)
    for retired in RETIRED:  # the ruleset tool S17 removed; present only in the before-run
        n = chars(rig.tool("eng", retired, ticket_id=ticket))
        row["read"] += n
        row["calls"][retired] = n
    seen = []
    for c in trace(lab, f"p1-codex-full-{epic}-orig", sid):
        d = c["args"].get("id")
        if c["tool"] == "read_doc" and d in ids and d not in seen:
            seen.append(d)
    before = row["read"]
    for d in seen:
        rd(id=ids[d])
    row["calls"]["doc_read"] = row["read"] - before
    if head_first():  # architect m-d125e8ccd1: the section reads a seat needs, counted on their own line
        sec = lambda **a: row.__setitem__("section_read", row["section_read"] + chars(rig.tool("eng", "doc_read", **a)))  # noqa: E731
        brief = trace(lab, f"p1-codex-brief-{epic}-pyr", sid)
        asked = {(c["args"].get("id"), c["args"].get("section")) for c in brief if c["tool"] == "read_doc"}
        done: set[tuple[str, str]] = set()

        def sec_tree(lab_id: str, h: str) -> None:
            """A section read returns its own text + child map (m-8c4f0d64cb); the seat then reads each child the
            trace's whole-subtree read covered, unless the trace reads that child itself (no part read twice)."""
            if (lab_id, h) in done:
                return
            done.add((lab_id, h))
            out = rig.tool("eng", "doc_read", id=ids[lab_id], section=h)
            row["section_read"] += chars(out)
            row["section_calls"] = row.get("section_calls", 0) + 1
            row["section_body"] = row.get("section_body", 0) + len((out.get("value") or {}).get("body_md") or "")
            for ch in (out.get("value") or {}).get("children") or []:
                if (lab_id, ch["h"]) not in asked and not _in_head(rig, ids[lab_id], ch["h"]):
                    sec_tree(lab_id, ch["h"])
        for c in brief:
            a, d = c["args"], c["args"].get("id")
            if c["tool"] != "read_doc" or d not in ids:
                continue
            if d not in seen:  # a head-first seat opens a doc at its head first
                seen.append(d)
                rd(id=ids[d])
            try:
                if a.get("section") and _in_head(rig, ids[d], a["section"]):
                    row["in_head"] += 1  # the head already returned this whole section: no second read
                elif a.get("section"):
                    sec_tree(d, a["section"])
                elif a.get("offset"):
                    sec(id=ids[d], offset=a["offset"])
            except Exception as ex:  # a heading the orig copy lacks: counted as a miss, never silently
                row["misses"].append(f"{d}:{a.get('section')}:{ex}")
    f0 = row["read"]
    for q in QUERIES[sid]:
        row["read"] += chars(rig.tool("eng", "find", query=q))
    row["calls"]["find"] = row["read"] - f0
    plan = (lab / "presults" / f"p1-codex-full-{epic}-pyr" / f"{sid}.last.txt")
    body = f"# Plan: {sid}\n\n## Purpose\nImplement {sid}.\n\n## Steps\n" + plan.read_text(encoding="utf-8")
    args = {"doc_type": "note", "title": f"Plan: {sid}", "body_md": body, "scope": "global", "ticket_id": ticket}
    out = rig.tool("eng", "doc_create", **args)
    row["written"] += chars(args) + chars(out)
    s, r = revise_one_section(rig, "eng", out["value"]["id"], body)
    row["written"] += s + r


_HEADS: dict[str, tuple[int, dict[str, tuple[int, int]]]] = {}


def _in_head(rig: Rig, doc_id: str, section: str) -> bool:
    """True when the whole section lies inside the page the head read returned (uncounted lookup of the body)."""
    from edp8.doc_tools import _page_end, head_read, heading_map  # noqa: F401
    if doc_id not in _HEADS:
        body = rig.http.get(f"/v1/docs/{doc_id}", params={"all": "true"}, headers={"X-Participant": "eng"}).json()["value"]["body_md"]
        sections = heading_map(body)
        _HEADS[doc_id] = (_page_end(body, 8192, sections), {s["h"]: (s["at"], s["chars"]) for s in sections})
    stop, where = _HEADS[doc_id]
    at, n = where.get(section, (stop, 0))
    return at + n <= stop


def tool_desc_chars(role="engineer") -> int:
    return sum(len(t.name) + len(t.description) + chars(t.input_schema) for t in tools_for_role(role))


def main():
    lab, real, out_path = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    label = sys.argv[sys.argv.index("--label") + 1] if "--label" in sys.argv else ("after" if head_first() else "before")
    result = {"label": label, "head_first": head_first(), "ruleset_tool": bool(RETIRED),
              "engineer_tool_desc_chars": tool_desc_chars(), "rows": [], "totals": {}}
    for docs in ("orig", "pyr"):
        rig = Rig()
        for epic, sids in STORIES.items():
            _e, ids, tickets = load_epic(rig, lab, epic, docs)
            for sid in sids:
                row = {"set": docs, "story": sid, "read": 0, "section_read": 0, "in_head": 0, "written": 0,
                       "calls": {}, "misses": []}
                run_story(rig, lab, epic, docs, sid, tickets[sid], ids, row)
                result["rows"].append(row)
    rig = Rig()
    for f in sorted(real.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))["value"]
        doc = rig.post("owner", "/v1/docs", {"doc_type": "note", "title": d["title"], "body_md": d["body_md"],
                                             "scope": "global"})
        row = {"set": "real", "story": d["id"], "read": 0, "section_read": 0, "written": 0, "calls": {},
               "misses": []}
        row["read"] += chars(rig.tool("eng", "doc_read", id=doc["id"]))
        row["read"] += chars(rig.tool("eng", "find", query=REAL_QUERIES.get(d["id"], d["title"])))
        s, r = revise_one_section(rig, "owner", doc["id"], d["body_md"])
        row["written"] += s + r
        result["rows"].append(row)
    for st in ("orig", "pyr", "real"):
        rows = [r for r in result["rows"] if r["set"] == st]
        result["totals"][st] = {"read": sum(r["read"] for r in rows), "written": sum(r["written"] for r in rows),
                                "section_read": sum(r.get("section_read", 0) for r in rows),
                                "misses": sum(len(r["misses"]) for r in rows),
                                "sections_in_head": sum(r.get("in_head", 0) for r in rows),
                                "section_calls": sum(r.get("section_calls", 0) for r in rows),
                                "section_body_chars": sum(r.get("section_body", 0) for r in rows)}
    out_path.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("label", "head_first", "ruleset_tool",
                                             "engineer_tool_desc_chars", "totals")}))


if __name__ == "__main__":
    main()
