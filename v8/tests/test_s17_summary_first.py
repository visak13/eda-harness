"""S17 (s-800c57b900, design-f39cf0db7d): summary-first docs. The `layout` flag (old docs `legacy`, new docs
`summary_first`, never inferred from a body), the head-first doc_read, and the legacy warning on every read path."""
from __future__ import annotations

import json
import os
import sqlite3

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from edp8.board import Board  # noqa: E402
from edp8.bundles import ALL_TOOLS, set_client  # noqa: E402
from edp8.client import BoardClient  # noqa: E402
from edp8.schemas import LEGACY_WARNING  # noqa: E402
from edp8.service import create_app  # noqa: E402
from edp8.store import Store  # noqa: E402

ADMIN = {"X-Admin": "t"}
OWNER = {"X-Participant": "owner"}
ARCH = {"X-Participant": "arch"}

SUMMARY = "# Big doc\n\n## Purpose\nWhy it exists.\n\n## Key points\n- the one rule\n\n## Outline\n- Topics: detail\n\n"
TOPICS = "## Topics\n" + "".join(f"### Topic {i}\n" + ("filler line about topic %d.\n" % i) * 60 + "\n" for i in range(12))
BIG = SUMMARY + TOPICS


def _call(http, who, name, **args):
    set_client(BoardClient(participant=who, client=http))
    t = ALL_TOOLS[name]
    return t.handler(t.args_model(**args))


@pytest.fixture
def http():
    c = TestClient(create_app(Board(Store(":memory:")), admin_token="t"))
    for pid, role, typ in [("owner", "owner", "human"), ("arch", "architect", "agent"), ("eng", "engineer", "agent")]:
        assert c.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                      headers=ADMIN).json()["ok"]
    return c


def _doc(http, body=BIG, who=ARCH, **extra):
    r = http.post("/v1/docs", json={"doc_type": "note", "title": "Big doc", "body_md": body, "scope": "global",
                                    **extra}, headers=who).json()
    assert r["ok"], r
    return r["value"]["id"]


# ----------------------------------------------------------------------------- decision 2: the layout flag

def _old_board(path):
    """A board file as it was before S17: a doc table without the layout column, one doc with two versions."""
    s = Store(str(path))
    from edp8.schemas import Doc
    d = Doc(id="note-old1", doc_type="note", title="old", body_md=SUMMARY, owner_role="architect", scope="global")
    s.put("doc", d)
    d.version = 2
    s.put("doc", d)
    s._conn.close()
    con = sqlite3.connect(str(path))
    con.execute("DROP INDEX IF EXISTS ix_doc_layout")
    con.execute("ALTER TABLE doc DROP COLUMN layout")
    con.execute("UPDATE doc SET body=json_remove(body, '$.layout')")
    con.execute("UPDATE doc_versions SET body=json_remove(body, '$.layout')")
    con.commit()
    con.close()


def test_migration_flags_every_existing_doc_legacy_and_new_docs_summary_first(tmp_path):
    path = tmp_path / "board.db"
    _old_board(path)
    s = Store(str(path))
    old = s.get("doc", "note-old1")
    # the old body IS summary-first shaped: the flag still says legacy, because nothing parses bodies
    assert old.layout == "legacy" and old.body_md.startswith("# Big doc\n\n## Purpose")
    assert s._conn.execute("SELECT layout FROM doc WHERE id='note-old1'").fetchone()[0] == "legacy"
    assert {json.loads(r[0])["layout"] for r in s._conn.execute("SELECT body FROM doc_versions")} == {"legacy"}
    board = Board(s)
    owner = board.participant_create("human", "owner", "owner", id_="owner")
    from edp8.schemas import DocType
    new = board.doc_create(owner, doc_type=DocType.note, title="new", body_md="no structure at all", scope="global")
    assert new.layout == "summary_first"  # never rejected, never inferred from its body
    s._conn.close()
    again = Store(str(path))  # reopening never re-flags: the migration runs once
    assert again.get("doc", new.id).layout == "summary_first" and again.get("doc", "note-old1").layout == "legacy"


def test_no_code_parses_bodies_to_set_the_flag():
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "edp8"
    for f in src.rglob("*.py"):
        for ln in f.read_text(encoding="utf-8").splitlines():
            if "layout" in ln and "body_md" in ln and "=" in ln and ("legacy" in ln or "summary_first" in ln):
                assert "d.layout" in ln or "target.layout" in ln, f"{f.name}: {ln.strip()}"


def test_rewrite_clears_the_flag_and_layout_is_never_a_reason_to_refuse(http):
    d = _doc(http, body="one line, no headings", layout="legacy")
    assert _call(http, "arch", "doc_read", id=d)["value"]["warning"] == LEGACY_WARNING
    r = _call(http, "arch", "doc_update", id=d, body_md=SUMMARY, layout="summary_first")
    assert r["ok"], r
    v = _call(http, "arch", "doc_read", id=d)["value"]
    assert v["layout"] == "summary_first" and "warning" not in v
    assert _call(http, "arch", "doc_edit", id=d, expected_version=2,
                 edits=[{"old_text": "the one rule", "new_text": "any text"}])["ok"]


# ----------------------------------------------------------------------------- decision 3: head-first doc_read

def test_doc_read_defaults_to_the_head_with_map_and_continuation(http):
    d = _doc(http)
    v = _call(http, "eng", "doc_read", id=d)["value"]
    assert v["body_md"].startswith(SUMMARY) and len(v["body_md"]) <= 8192 and not v["complete"]
    assert v["total_chars"] == len(BIG) and "versions" not in v
    sizes = {m["h"]: m["chars"] for m in v["map"]}
    assert sizes["## Topics"] == len(TOPICS) and sizes["### Topic 11"] > 0
    assert v["continuation"]["page"]["offset"] == len(v["body_md"])
    assert "section=" in v["continuation"]["section"] and "all" not in v["continuation"]
    sec = _call(http, "eng", "doc_read", id=d, section="### Topic 11")["value"]
    assert sec["body_md"].startswith("### Topic 11") and len(sec["body_md"]) == sizes["### Topic 11"]


def test_mcp_doc_read_has_no_whole_body_and_http_all_true_does(http):
    """all=true is the HTTP read for humans and editors; the MCP doc_read has no whole-body read (m-c6cdb0602c)."""
    assert "all" not in ALL_TOOLS["doc_read"].args_model.model_fields
    d = _doc(http)
    v = http.get(f"/v1/docs/{d}", params={"all": "true"}, headers=OWNER).json()["value"]
    assert v["body_md"] == BIG and v["versions"] == [1]


def test_a_short_doc_comes_back_whole_without_a_map(http):
    d = _doc(http, body=SUMMARY)
    v = _call(http, "eng", "doc_read", id=d)["value"]
    assert v["body_md"] == SUMMARY and v["complete"] and "map" not in v and "continuation" not in v


def test_http_get_is_head_first_and_all_true_is_the_full_record(http):
    d = _doc(http, layout="legacy")
    head = http.get(f"/v1/docs/{d}", headers=OWNER).json()["value"]
    assert len(head["body_md"]) < len(BIG) and head["warning"] == LEGACY_WARNING and "map" in head
    full = http.get(f"/v1/docs/{d}", params={"all": "true"}, headers=OWNER).json()["value"]
    assert full["body_md"] == BIG and full["versions"] == [1] and full["warning"] == LEGACY_WARNING
    page = http.get(f"/v1/docs/{d}", params={"offset": 10}, headers=OWNER).json()["value"]
    assert page["warning"] == LEGACY_WARNING


def test_doc_tools_name_the_skill_in_one_line():
    for name in ("doc_create", "doc_update", "doc_edit"):
        desc = ALL_TOOLS[name].description
        assert desc.count("/doc-write") == 1, (name, desc)


def test_ruleset_tool_is_gone():
    """Decision 5: the ruleset tool, its module and every bundle entry are gone."""
    import importlib.util
    from edp8.bundles import ALL_TOOLS, ROLE_BUNDLES
    assert not [n for n in ALL_TOOLS if "ruleset" in n]
    assert not [n for b in ROLE_BUNDLES.values() for n in b if "ruleset" in n]
    assert importlib.util.find_spec("edp8.ruleset") is None


# ----------------------------------------------------------------------------- decision 4: find by section

DEEP = BIG.replace("filler line about topic 9.", "filler line about topic 9 and the zanzibarite clause.", 1)


def test_find_hits_a_term_past_2000_chars_with_its_section(http):
    """A term deep in the body (past the old 2,000-char embed cut) is found, and the hit names the doc, its title,
    the section heading and a snippet; the section reads back with doc_read(section=)."""
    did = _doc(http, body=DEEP)
    assert DEEP.index("zanzibarite") > 2000
    r = http.get("/v1/find", params={"q": "zanzibarite", "types": "doc"}, headers=OWNER).json()
    hit = r["value"][0]
    assert (hit["type"], hit["id"], hit["title"], hit["section"]) == ("doc", did, "Big doc", "### Topic 9")
    assert "zanzibarite" in hit["snippet"]
    assert "section" in r["hint"]
    part = _call(http, "eng", "doc_read", id=did, section=hit["section"])["value"]
    assert "zanzibarite" in part["body_md"] and part["body_md"].startswith("### Topic 9")
    assert _call(http, "eng", "find", query="zanzibarite", types="doc")["value"][0]["section"] == "### Topic 9"


def test_doc_edit_moves_the_section_hit(http):
    did = _doc(http, body=DEEP)
    new = DEEP.replace(" and the zanzibarite clause", "").replace("filler line about topic 3.",
                                                                  "filler line about topic 3 and zanzibarite.", 1)
    assert http.patch(f"/v1/docs/{did}", json={"body_md": new}, headers=ARCH).json()["ok"]
    hit = http.get("/v1/find", params={"q": "zanzibarite", "types": "doc"}, headers=OWNER).json()["value"][0]
    assert hit["section"] == "### Topic 3"


def test_semantic_index_units_are_sections_within_the_embed_window():
    """Every section unit fits the embedder's window, so no part of a long doc goes unembedded; the index returns
    one hit per doc, at its best section."""
    from edp8.doc_tools import UNIT_CHARS, doc_units
    from edp8.search import EMBED_MAX_CHARS, Index, NullEmbedder
    units = doc_units("Big doc", DEEP)
    assert len(units) > 12 and all(len(t) <= EMBED_MAX_CHARS for _, t in units) and UNIT_CHARS < EMBED_MAX_CHARS
    ix = Index(embedder=NullEmbedder())
    ix.rebuild([("doc", "note-1", t, h) for h, t in units] + [("message", "m-1", "unrelated words")])
    hits = ix.search("zanzibarite", k=5)
    assert [(h["id"], h["section"]) for h in hits] == [("note-1", "### Topic 9")]
    ix.upsert_sections("doc", "note-1", [(None, "Big doc\nnothing here")])
    assert ix.search("zanzibarite", k=5) == [] and ix.unit_count() == 2


def test_an_old_fts_table_is_rebuilt_by_section(tmp_path):
    path = tmp_path / "b.db"
    s = Store(str(path))
    from edp8.schemas import Doc
    s.put("doc", Doc(id="note-x", doc_type="note", title="x", body_md=DEEP, owner_role="architect", scope="global"))
    s.close()
    con = sqlite3.connect(path)
    con.execute("DROP TABLE fts")
    con.execute("CREATE VIRTUAL TABLE fts USING fts5(type UNINDEXED, id UNINDEXED, text)")
    con.commit()
    con.close()
    hits = Store(str(path)).fts_search("zanzibarite", types={"doc"})
    assert [(h["id"], h["section"]) for h in hits] == [("note-x", "### Topic 9")]


# ----------------------------------------------------------------------------- decision 6: every agent read path

def test_agent_read_paths_show_the_warning_and_never_the_whole_body():
    """ticket_read, context and find (the paths a seat meets a doc on besides doc_read) carry the legacy warning on
    the doc's item and never inline the body past the head."""
    from edp8.schemas import DocType, Relation, Role, TicketKind, WorkType
    b = Board(Store(":memory:"))
    http = TestClient(create_app(b, admin_token="t"))
    owner = b.participant_create("human", Role.owner, "owner", id_="owner")
    arch = b.participant_create("agent", Role.architect, "arch", id_="arch")
    b.participant_create("agent", Role.engineer, "eng", id_="eng")
    epic = b.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    story = b.ticket_create(arch, kind=TicketKind.story, work_type=WorkType.feature, title="S", parent_id=epic.id)
    d = b.doc_create(arch, doc_type=DocType.design, scope=epic.id, title="Old design", body_md=DEEP, layout="legacy")
    b.link_create(arch, from_id=story.id, to_id=d.id, relation=Relation.designed_by)
    deep = "filler line about topic 11"
    for name, args in (("ticket_read", {"ticket_id": story.id}), ("context", {"ticket_id": story.id}),
                       ("find", {"query": "zanzibarite", "types": "doc"})):
        out = json.dumps(_call(http, "eng", name, **args))
        assert d.id in out and LEGACY_WARNING in out, name
        assert deep not in out, name


def test_human_doc_view_has_banner_map_and_whole_body(http):
    """Ruling m-639da0243d: the web doc view (GET /v1/docs/{id}/html) carries the legacy warning and the heading map
    with sizes, and still renders the whole body; the HTTP write hints name the skill."""
    did = _doc(http, layout="legacy")
    v = http.get(f"/v1/docs/{did}/html", headers=OWNER).json()["value"]
    assert v["layout"] == "legacy" and v["warning"] == LEGACY_WARNING
    assert {"h": "### Topic 11", "level": 3, "chars": len(TOPICS.split("### Topic 11")[1]) + len("### Topic 11")} \
        in v["map"]
    assert "filler line about topic 11" in v["html"] and v["total_chars"] == len(BIG)
    r = http.post("/v1/docs", json={"doc_type": "note", "title": "n", "body_md": "x", "scope": "global"},
                  headers=ARCH).json()
    assert "/doc-write" in r["hint"]
    assert "/doc-write" in http.patch(f"/v1/docs/{did}", json={"body_md": "y"}, headers=ARCH).json()["hint"]


def test_a_parent_section_read_returns_its_own_text_and_the_child_map(http):
    """Architect m-8c4f0d64cb: a section read returns the section's own text up to its first subsection, plus each
    direct subsection's heading and size, so a parent and its child are never read twice; include_children=true
    returns the old whole-subtree read."""
    did = _doc(http)
    own = _call(http, "eng", "doc_read", id=did, section="## Topics")["value"]
    assert own["body_md"] == "## Topics\n" and "filler" not in own["body_md"]
    assert [c["h"] for c in own["children"]] == [f"### Topic {i}" for i in range(12)]
    assert own["children"][3]["chars"] == len(TOPICS.split("### Topic 3")[1].split("### Topic 4")[0]) + len("### Topic 3")
    whole = _call(http, "eng", "doc_read", id=did, section="## Topics", include_children=True, limit=32768, fresh=True)["value"]
    assert whole["body_md"] == TOPICS and "children" not in whole
    leaf = _call(http, "eng", "doc_read", id=did, section="### Topic 3", fresh=True)["value"]
    assert leaf["body_md"].startswith("### Topic 3") and "children" not in leaf
