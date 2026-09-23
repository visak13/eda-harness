"""The steps of scripts/qa_walk.py, one block per criterion. Each block records a verdict and never
stops the walk; the harness prints RESULT lines at the end."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import httpx

import adversary_repro as H
from edp8.bundles import ALL_TOOLS, set_client
from edp8.client import BoardClient

ROLES = ["architect", "engineer", "qa", "adversary", "sme"]
PICKS = {"architect": "gpt-6-astra", "engineer": "gpt-6-sol", "qa": "gpt-6-astra", "adversary": "gpt-6-astra",
         "sme": "claude-opus-5-5"}


def run_steps(base: str, home: Path, log: Callable, verdict: Callable, ui: Callable) -> None:
    http = httpx.Client(base_url=base, timeout=60)

    def call(who: str, method: str, path: str, ok_only: bool = True, **kw) -> Any:
        headers = {"X-Participant": who, **({"X-Admin": H.ADMIN} if who == "admin" else {})}
        r = http.request(method, path, headers=headers, **kw).json()
        if ok_only:
            assert r.get("ok"), (method, path, r)
            return r["value"]
        return r

    def tool(who: str, name: str, **kw) -> dict:
        set_client(BoardClient(base_url=base, participant=who))
        t = ALL_TOOLS[name]
        return t.handler(t.args_model(**kw))

    def ticket(tid: str) -> dict:
        return call("owner", "GET", f"/v1/tickets/{tid}")

    def spawns_for(handle: str) -> list[dict]:
        return [s for s in H.SPAWNS if s.get("handle") == handle or s.get("participant_id") == handle]

    def sessions(pid: str) -> list[dict]:
        from edp8 import pool_adapter
        pool_adapter.sync_sessions(board_url=base, admin_token=H.ADMIN)  # the fleet board's pool watch, by hand
        return call("owner", "GET", f"/v1/sessions?participant_id={pid}")

    def guard(crit: str, fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            verdict(crit, False, f"walk error: {e!r}"[:400])

    for pid, role, typ in [("owner", "owner", "human")]:
        call("admin", "POST", "/v1/participants", json={"id": pid, "handle": pid, "role": role, "type": typ})

    state: dict[str, Any] = {}

    # ---------------------------------------------------------------- c-5bca8c2050 new-epic per-role picks
    def s_roles_new_epic() -> None:
        out = ui(base, "new-epic", {"title": "Walk epic", "words": "Build the thing the owner asked for.",
                                    "picks": PICKS, "efforts": {"engineer": "high"}, "spawn": False})
        epic = out.get("epic")
        assert epic, out
        state["epic"] = epic
        tags = ticket(epic).get("tags") or []
        want = [f"model:{r}={m}" for r, m in PICKS.items()]
        missing = [w for w in want if w not in tags]
        # one real spawn per role through the board's spawn path, each alive with the chosen model
        set_client(BoardClient(base_url=base, participant="owner"))
        arch = tool("owner", "spawn", role="architect", ticket_id=epic)
        state["story"] = call("architect." + epic, "POST", "/v1/tickets",
                              json={"kind": "story", "work_type": "feature", "title": "Walk story",
                                    "parent_id": epic})["id"]
        seen = {"architect": arch}
        for r in ("engineer", "qa", "adversary", "sme"):
            seen[r] = tool("owner", "spawn", role=r, ticket_id=state["story"] if r == "engineer" else epic)
        rows = {}
        for r in ROLES:
            pid = f"{r}.{state['story'] if r == 'engineer' else epic}"
            sp = spawns_for(pid)
            ss = sessions(pid)
            rows[r] = {"ok": seen[r].get("ok"), "model": (sp[-1].get("model") if sp else None),
                       "state": (ss[-1].get("state") if ss else None)}
        log(f"  spawns per role: {json.dumps(rows)}")
        bad = [r for r in ROLES if not rows[r]["ok"] or rows[r]["state"] not in ("alive", "parked")
               or not rows[r]["model"] or not rows[r]["model"].endswith(PICKS[r])]
        verdict("c-5bca8c2050", not missing and out.get("roleRows") == 5 and out.get("dialog", {}).get("engineer") == "gpt-6-sol" and out.get("dialog", {}).get("architect") == "gpt-6-astra"
                and not bad and out.get("modelsStrip") == 0,
                f"dialog rows={out.get('roleRows')} defaults={out.get('defaults')} tags missing={missing} "
                f"epic Models dialog after reload={out.get('dialog')} (first open, unreloaded: {out.get('dialogFresh')}) spawns={rows} bad={bad}")

    guard("c-5bca8c2050", s_roles_new_epic)

    # ---------------------------------------------------------------- c-902cb3ffff Models dialog (epic + story)
    def s_ui_models() -> None:
        out = ui(base, "models-story", {"story": state["story"], "engineer": "claude-opus-5-5"})
        tags = ticket(state["epic"]).get("tags") or []
        verdict("c-902cb3ffff", out.get("modelsStrip") == 0 and out.get("before") == "gpt-6-sol"
                and "model:engineer=claude-opus-5-5" in tags and bool(out.get("saved")),
                f"story page: no MODELS strip ({out.get('modelsStrip')}), dialog engineer {out.get('before')}→claude-opus-5-5, "
                f"saved='{out.get('saved')}', epic tags now {[t for t in tags if t.startswith('model:')]}")

    guard("c-902cb3ffff", s_ui_models)

    # ---------------------------------------------------------------- c-455bd9042c Seats → Spawn seat
    def s_roles_seats() -> None:
        s2 = call("architect." + state["epic"], "POST", "/v1/tickets",
                  json={"kind": "story", "work_type": "feature", "title": "Ready story for Seats spawn",
                        "parent_id": state["epic"]})["id"]
        before = ticket(s2)
        out = ui(base, "seats-spawn", {"story": s2, "model": "gpt-6-sol"})
        after = ticket(s2)
        sp = spawns_for(f"engineer.{s2}")
        verdict("c-455bd9042c", after.get("assignee") == f"engineer.{s2}" and bool(out.get("done")) and sp
                and set(ROLES) <= {x.split()[0].lower() for x in out.get("roles", [])} | set(out.get("roles", [])),
                f"roles offered={out.get('roles')} models={out.get('models')} status before={before.get('status')} "
                f"assignee after={after.get('assignee')} pool model={sp[-1].get('model') if sp else None} done='{out.get('done')}'")

    guard("c-455bd9042c", s_roles_seats)

    # ---------------------------------------------------------------- c-05fe4d9444 Quick task dialog
    def s_quick_dialog() -> None:
        out = ui(base, "quick-task", {"title": "Rename the export button", "words": "The export button should say Download.",
                                      "model": "gpt-6-sol"})
        sid = out.get("story")
        assert sid, out
        state["quick"] = sid
        t = ticket(sid)
        sp = spawns_for(f"engineer.{sid}")
        ss = sessions(f"engineer.{sid}")
        verdict("c-05fe4d9444", "quick" in (t.get("tags") or []) and t.get("assignee") == f"engineer.{sid}" and sp
                and sp[-1].get("model", "").endswith("gpt-6-sol") and ss and ss[-1].get("state") in ("alive", "parked"),
                f"story {sid} tags={t.get('tags')} status={t.get('status')} assignee={t.get('assignee')} "
                f"pool model={sp[-1].get('model') if sp else None} session={ss[-1].get('state') if ss else None} "
                f"page seat='{out.get('assignedSeat')}'")

    guard("c-05fe4d9444", s_quick_dialog)

    # ---------------------------------------------------------------- c-09c62d8a07 Needs you pass / fail
    def s_quick_needs_you() -> None:
        made = {}
        for tag, title in (("pass", "Quick A"), ("fail", "Quick B")):
            q = call("owner", "POST", "/v1/quick-tasks", json={"title": title, "words": f"Do {title}.", "model": "gpt-6-sol"})
            sid = q["ticket"]["id"] if isinstance(q.get("ticket"), dict) else q["id"]
            eng = f"engineer.{sid}"
            c = call(eng, "POST", "/v1/criteria", json={"ticket_id": sid, "text": f"{title} is done as the words say",
                                                        "check": "look"})
            doc = call(eng, "POST", "/v1/docs", json={"doc_type": "report", "title": f"{title} report", "ticket_id": sid, "scope": sid,
                                                     "body_md": "Done. Evidence: the button now says Download."})
            call(eng, "PATCH", f"/v1/criteria/{c['id']}", json={"evidence_ref": doc["id"]})
            call(eng, "PATCH", f"/v1/tickets/{sid}", json={"status": "in_progress"})
            call(eng, "PATCH", f"/v1/tickets/{sid}", json={"status": "in_review"})
            made[tag] = (sid, c["id"], c.get("checked_by"))
        log(f"  seeded quick tasks in_review: {made}")
        a = ui(base, "needs-you", {"tag": "pass", "verdict": "pass"})
        ta = ticket(made["pass"][0])
        b = ui(base, "needs-you", {"tag": "fail", "verdict": "fail", "note": "Not yet: the tooltip still says Export."})
        tb = ticket(made["fail"][0])
        thread = call("owner", "GET", f"/v1/messages?ticket_id={made['fail'][0]}")
        noted = any("tooltip still says Export" in (m.get("text") or "") for m in thread)
        cb = call("owner", "GET", f"/v1/criteria?ticket_id={made['fail'][0]}")
        verdict("c-09c62d8a07", made["pass"][2] == "owner" and ta.get("status") == "done" and tb.get("status") == "in_progress"
                and noted and cb and cb[0].get("verdict") == "fail" and a.get("buttons", {}).get("approve") == 1,
                f"checked_by={made['pass'][2]}; A: needs-you='{(a.get('featured') or '')[:80]}' buttons={a.get('buttons')} → {ta.get('status')}; "
                f"B: fail → {tb.get('status')}, criterion verdict={cb[0].get('verdict') if cb else None}, note on thread={noted}")

    guard("c-09c62d8a07", s_quick_needs_you)

    # ---------------------------------------------------------------- c-3000a9760a story page Spawn seat
    def s_quick_story_spawn() -> None:
        sid = state["quick"]
        e = ui(base, "story-spawn", {"story": sid, "role": "engineer", "model": "claude-opus-5-5"})
        q = ui(base, "story-spawn", {"story": sid, "role": "qa", "model": "gpt-6-astra"})
        t = ticket(sid)
        qs = sessions(f"qa.{sid}")
        verdict("c-3000a9760a", set(e.get("roles") or []) == {"engineer", "qa", "adversary"}
                and bool(e.get("done")) and bool(q.get("done")) and t.get("assignee") == f"engineer.{sid}"
                and qs and qs[-1].get("ticket_id") == sid and q.get("checkerNote"),
                f"roles={e.get('roles')} engineer done='{e.get('done')}' qa done='{q.get('done')}' checker note='{q.get('checkerNote')}' "
                f"assignee stays {t.get('assignee')}; qa session ticket={qs[-1].get('ticket_id') if qs else None}")

    guard("c-3000a9760a", s_quick_story_spawn)

    from qa_walk_steps2 import run_steps2
    run_steps2(base, home, log, verdict, ui, call, tool, ticket, state, guard)
