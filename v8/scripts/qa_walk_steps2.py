"""qa_walk steps, part 2: S-LIBRARY (Library tab, link/unlink) and S-IMPLICIT (records, auto-link)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable


def run_steps2(base: str, home: Path, log: Callable, verdict: Callable, ui: Callable, call: Callable,
               tool: Callable, ticket: Callable, state: dict[str, Any], guard: Callable) -> None:
    epic = state["epic"]
    story = state["story"]
    arch = f"architect.{epic}"

    def knowledge() -> dict:
        return call("owner", "GET", "/v1/knowledge")

    def brief_ids() -> tuple[list[str], list[str]]:
        from edp8.client import BoardClient
        c = BoardClient(base_url=base, participant="owner")
        tr = c.ticket_read(story)
        log(f"  ticket_read({story}) keys={list((tr.get('value') or {}).keys())[:12]} parent_id={(tr.get('value') or {}).get('parent_id')}")
        log(f"  link_query(from_id={epic}, uses_strategy)={c.link_query(from_id=epic, relation='uses_strategy')}")
        out = tool("owner", "assemble_ruleset", ticket_id=story)
        if not out["ok"] and "no strategy/domain docs" in json.dumps(out):
            return [], []
        assert out["ok"], out
        v = out["value"]
        enforced = [x.get("text") for x in v.get("enforced") or []]
        index = [x.get("id") for x in (v.get("index") or v.get("docs") or [])]
        return enforced, index

    # seed the Library: an active strategy (tag web), a domain (tag python), a lesson, two proposals
    call("admin", "POST", "/v1/participants", json={"id": "qa.walk", "handle": "qa.walk", "role": "qa", "type": "agent"})
    strat = call("owner", "POST", "/v1/docs", json={
        "doc_type": "strategy_hl", "title": "craft: web components", "scope": "global", "tags": ["web"],
        "body_md": "How we build components.\n\n## Enforced\n- every component ships a vitest [required]\n"})
    dom = call("owner", "POST", "/v1/docs", json={
        "doc_type": "domain", "title": "domain: python services", "scope": "global", "tags": ["python"],
        "body_md": "Python service conventions.\n"})
    les = tool("qa.walk", "record_lesson", domain="testing", topic="e2e", text="Run only the specs you changed.")
    good = tool("qa.walk", "doc_create", doc_type="strategy_hl", title="craft: web components", scope="global",
                status="proposed", proposes=strat["id"], ticket_id=epic,
                body_md="How we build components.\n\n## Enforced\n- every component ships a vitest and a story [required]\n")["value"]
    bad = tool("qa.walk", "doc_create", doc_type="strategy_hl", title="craft: web components", scope="global",
               status="proposed", proposes=strat["id"], ticket_id=epic,
               body_md="How we build components.\n\n## Enforced\n- skip tests [required]\n")["value"]
    log(f"  library seeded: strat={strat['id']} dom={dom['id']} lesson={les.get('value', {}).get('id')} good={good['id']} bad={bad['id']}")

    # ---------------------------------------------------------------- c-ed2a341466 Library tab
    def s_library() -> None:
        out = ui(base, "library", {"search": "python", "tag": "web", "doc": strat["id"], "docTitle": "craft: web components",
                                   "newBody": "How we build components (edited by the owner).\n\n## Enforced\n- every component ships a vitest [required]\n",
                                   "epic": epic, "good": good["id"], "bad": bad["id"],
                                   "goodTitle": "craft: web components", "badTitle": "craft: web components"})
        s_after = call("owner", "GET", f"/v1/docs/{strat['id']}")
        g = call("owner", "GET", f"/v1/docs/{good['id']}")
        b = call("owner", "GET", f"/v1/docs/{bad['id']}")
        kinds = {k.lower() for k in out.get("kinds") or []}
        conds = {"nav": out.get("navIcon", 0) >= 1, "rows": (out.get("rowsAll") or 0) >= 4,
                 "search": (out.get("rowsSearch") or 0) < (out.get("rowsAll") or 0), "tag": (out.get("rowsTag") or 0) < (out.get("rowsAll") or 0),
                 "proposed": (out.get("rowsProposed") or 0) == 2, "edit": s_after.get("version", 1) >= 2, "diff": out.get("approveDiff") == 1,
                 "approved": str(g.get("resolution") or "").startswith("approved"), "v3": s_after.get("version") == 3, "body": "and a story" in json.dumps(s_after),
                 "rejected": b.get("status") == "retired" and b.get("resolution") == "rejected"}
        log(f"  library conds: {conds}; good resolution={g.get('resolution')!r} status={g.get('status')!r} keys={sorted(g.keys())[:20]}")
        verdict("c-ed2a341466", out.get("navIcon", 0) >= 1 and (out.get("rowsAll") or 0) >= 4
                and (out.get("rowsSearch") or 0) < (out.get("rowsAll") or 0) and (out.get("rowsTag") or 0) < (out.get("rowsAll") or 0)
                and (out.get("rowsProposed") or 0) == 2 and s_after.get("version", 1) >= 2
                and out.get("approveDiff") == 1 and str(g.get("resolution") or "").startswith("approved") and s_after.get("version") == 3
                and "and a story" in json.dumps(s_after) and b.get("status") == "retired" and b.get("resolution") == "rejected",
                f"nav icon={out.get('navIcon')} rows all/search/tag/proposed={out.get('rowsAll')}/{out.get('rowsSearch')}/{out.get('rowsTag')}/{out.get('rowsProposed')} "
                f"kinds={sorted(kinds)} edit → {strat['id']} v{s_after.get('version')}; approve: diff={out.get('approveDiff')} → {good['id']} status={g.get('status')} "
                f"resolution={g.get('resolution')} target v{s_after.get('version')} body has 'and a story'={'and a story' in json.dumps(s_after)}; reject → {bad['id']} status={b.get('status')} resolution={b.get('resolution')}; errors={out.get('errors')}")
        state["linked_from_ui"] = out.get("linked")

    guard("c-ed2a341466", s_library)

    # ---------------------------------------------------------------- c-14e93ebfc7 link / unlink ↔ brief
    def s_library_links() -> None:
        # the Library walk linked strat → epic (uses_strategy); the epic page lists it; the brief reflects it
        ep = ui(base, "epic-knowledge", {"epic": epic, "tag": "linked"})
        log(f"  links from epic: {call('owner', 'GET', f'/v1/links?from_id={epic}', ok_only=False)}")
        log(f"  knowledge linked: {[(d['id'], d.get('linked')) for d in knowledge().get('docs', [])]}")
        enforced1, index1 = brief_ids()
        listed = strat["id"] in json.dumps(knowledge()) and strat["id"] in (ep.get("knowledge") or "") or "craft: web components" in (ep.get("knowledge") or "")
        un = ui(base, "unlink", {"doc": strat["id"]})
        ep2 = ui(base, "epic-knowledge", {"epic": epic, "tag": "unlinked"})
        enforced2, index2 = brief_ids()
        hit1 = any("vitest" in (x or "") for x in enforced1) or strat["id"] in index1
        hit2 = any("vitest" in (x or "") for x in enforced2) or strat["id"] in index2
        verdict("c-14e93ebfc7", listed and hit1 and un.get("linkedLeft") == 0 and not hit2
                and "craft: web components" not in (ep2.get("knowledge") or ""),
                f"after link: epic page knowledge='{(ep.get('knowledge') or '')[:90]}' brief enforced={enforced1} index={index1}; "
                f"after unlink: links left={un.get('linkedLeft')} epic page='{(ep2.get('knowledge') or '')[:60]}' empty={ep2.get('empty')} brief enforced={enforced2} index={index2}")

    guard("c-14e93ebfc7", s_library_links)

    # ---------------------------------------------------------------- c-a9984af463 auto-link at quick task + design_signoff
    def s_autolink() -> None:
        # a Library doc tagged `quick` (the plain tag every quick task carries); an epic tagged web signed off
        qdoc = call("owner", "POST", "/v1/docs", json={
            "doc_type": "strategy_ll", "title": "craft: quick tasks", "scope": "global", "tags": ["quick"],
            "body_md": "## Enforced" + chr(10) + "- a quick task ships in one commit [required]" + chr(10)})
        # NOTE (gap): the Quick task dialog / POST /v1/quick-tasks take no tags, so from the UI a quick task carries
        # only `quick` + seat tags and links nothing; the live case is the board API's tagged quick story
        q = call("owner", "POST", "/v1/tickets", json={"kind": "story", "work_type": "feature", "title": "web tweak",
                                                      "words": "Tighten the web components' spacing.", "tags": ["quick", "web"]})
        qid = q["id"]
        qt = ticket(qid)
        qmsgs = call("owner", "GET", f"/v1/messages?ticket_id={qid}")
        qnote = [m.get("text") for m in qmsgs if "auto-link" in (m.get("text") or "").lower()]
        qlinked = [d["id"] for d in knowledge().get("docs", []) if any(x.get("ticket_id") == qid for x in d.get("linked", []))]
        log(f"  quick auto-link: linked={qlinked} note={qnote}")
        e2 = call("owner", "POST", "/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "Tagged epic",
                                                       "tags": ["web"]})["id"]
        signed = call("owner", "PATCH", f"/v1/tickets/{e2}", ok_only=False, json={"status": "signed_off"})
        if not signed.get("ok"):
            a2 = f"architect.{e2}"
            call("admin", "POST", "/v1/participants", json={"id": a2, "handle": a2, "role": "architect", "type": "agent"})
            call("owner", "PATCH", f"/v1/tickets/{e2}", ok_only=False, json={"assignee": a2})
            design = call(a2, "POST", "/v1/docs", json={"doc_type": "design", "title": "Design", "ticket_id": e2, "scope": e2,
                                                        "body_md": "# Design -- words"})
            call(a2, "POST", "/v1/criteria", json={"ticket_id": e2, "text": "the tagged epic ships", "check": "look"})
            log(f"  designed: {call(a2, 'PATCH', f'/v1/tickets/{e2}', ok_only=False, json={'status': 'designed', 'design_ref': design['id']})}"[:200])
            log(f"  gate open: {call(a2, 'POST', f'/v1/gates/{e2}/design_signoff/open', ok_only=False, json={'note': 'please sign off'})}"[:200])
            signed = call("owner", "POST", f"/v1/gates/{e2}/design_signoff/answer", ok_only=False, json={"answer": "yes"})
        log(f"  signoff attempt: {json.dumps(signed)[:300]}")
        links = [l for l in knowledge().get("docs", []) if l.get("id") == strat["id"]]
        linked_to = [x.get("ticket_id") for d in links for x in d.get("linked", [])]
        emsgs = call("owner", "GET", f"/v1/messages?ticket_id={e2}")
        enote = [m.get("text") for m in emsgs if strat["id"] in (m.get("text") or "")]
        # the owner can unlink
        link_id = next((x.get("link_id") for d in links for x in d.get("linked", []) if x.get("ticket_id") == e2), None)
        un = call("owner", "DELETE", f"/v1/links/{link_id}", ok_only=False) if link_id else {"ok": False, "error": "no link"}
        verdict("c-a9984af463", bool(qlinked) and bool(qnote) and e2 in linked_to and bool(enote) and un.get("ok"),
                f"quick {qid} tags={qt.get('tags')} linked={bool(qlinked)} note={bool(qnote)}; epic {e2} signoff ok={signed.get('ok')} "
                f"linked={e2 in linked_to} note={bool(enote)}; unlink ok={un.get('ok')}; linked_to={linked_to}")

    guard("c-a9984af463", s_autolink)

    # ---------------------------------------------------------------- c-1e8f2edd8e records written by the board
    def s_records() -> None:
        def recs(typ: str) -> list[dict]:
            r = call("owner", "GET", f"/v1/find?q=walk&k=50&types={typ}", ok_only=False)
            return r.get("value") or [] if r.get("ok") else []
        # verdict with a note → claim (qa: measured)
        c = call(arch, "POST", "/v1/criteria", json={"ticket_id": story, "text": "walk: the page loads under 2 s", "check": "command"})
        rep = call("qa.walk", "POST", "/v1/docs", json={"doc_type": "report", "title": "walk report", "ticket_id": story, "scope": story,
                                                       "body_md": "measured 1.2 s\n"})
        call("qa.walk", "PATCH", f"/v1/criteria/{c['id']}", ok_only=False, json={"evidence_ref": rep["id"]})
        v = call("qa.walk", "PATCH", f"/v1/criteria/{c['id']}", ok_only=False,
                 json={"verdict": "pass", "note": "walk claim: the page loads in 1.2 s on the private board"})
        # deviation accepted → decision
        dv = call(arch, "POST", "/v1/messages", json={"ticket_id": story, "kind": "deviation", "to": "owner",
                                                     "text": "walk deviation: ship without the tooltip"})
        acc = call("owner", "POST", "/v1/messages", ok_only=False, json={"ticket_id": story, "kind": "answer", "to": arch,
                                                                       "reply_to": dv["id"], "text": "accepted: ship without the tooltip"})
        # pain filed → lesson (the board reads the pain file on context())
        pain = home / "pain-points.jsonl"
        pain.write_text(json.dumps({"id": "p-walk1", "symptom": "walk pain: the build wedged on a locked exe",
                                    "domain": "tooling", "topic": "build"}) + "\n", encoding="utf-8")
        call("owner", "GET", f"/v1/context?ticket_id={story}", ok_only=False)
        tool("owner", "context", ticket_id=story)
        claims = [r for r in recs("claim") if "1.2 s" in json.dumps(r)]
        decisions = [r for r in recs("decision") if "tooltip" in json.dumps(r)]
        lessons = [r for r in recs("lesson") if "locked exe" in json.dumps(r)]
        # gate answered → decision (from the auto-link block's sign-off, if it went through)
        gate_dec = [r for r in recs("decision") if "design_signoff" in json.dumps(r) or "signed off" in json.dumps(r).lower()]
        # dedup: the same verdict + note on the same criterion again makes no second claim
        log(f"  claim row: {json.dumps(claims[0])[:400] if claims else None}")
        call("qa.walk", "PATCH", f"/v1/criteria/{c['id']}", ok_only=False, json={"verdict": "pending"})
        call("qa.walk", "PATCH", f"/v1/criteria/{c['id']}", ok_only=False,
             json={"verdict": "pass", "note": "walk claim: the page loads in 1.2 s on the private board"})
        claims2 = [r for r in recs("claim") if "1.2 s" in json.dumps(r)]
        wd = tool("owner", "withdraw_decision", decision_id=decisions[0]["id"], reason="walk undo") if decisions else {"ok": None}
        verdict("c-1e8f2edd8e", v.get("ok") and len(claims) == 1 and len(claims2) == 1 and bool(decisions) and bool(lessons),
                f"verdict ok={v.get('ok')} claim={[(r.get('id'), r.get('basis')) for r in claims]} dedup second note → {len(claims2)} claim(s); "
                f"deviation accepted ok={acc.get('ok')} decision={[r.get('id') for r in decisions]} withdraw={wd.get('ok')}; gate decision={[r.get('id') for r in gate_dec]}; "
                f"pain → lesson={[r.get('id') for r in lessons]}")

    guard("c-1e8f2edd8e", s_records)
