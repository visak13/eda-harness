"""e0cec S5 live probes (architect steer m-8e7b6df25b): one live call per refusal class with a guest token, against a
PRIVATE board in token mode (EDP8_BIND cleared), plus the scoped-404 and allowed sides. Seeds its own data over /v1.

    python scripts/guest_live_probe.py --base http://127.0.0.1:19477 --admin <admin token> \
        --owner owner:<token> --guest gina:<token> --agent arch:<token> --out docs/evidence/e0cec-s5

Writes live-probes.json and live-probes.md; exits 1 when any probe's status differs from what it expects."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

import httpx

GITHUB_SAMPLE = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"  # fabricated, matches the github-token class


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--admin", required=True)
    for who in ("owner", "guest", "agent"):
        ap.add_argument(f"--{who}", required=True, help="id:token")
    ap.add_argument("--out", default="docs/evidence/e0cec-s5")
    a = ap.parse_args()

    def hdr(spec):
        pid, tok = spec.split(":", 1)
        return {"X-Participant": pid, "X-Token": tok}

    owner, guest, agent = hdr(a.owner), hdr(a.guest), hdr(a.agent)
    gid = a.guest.split(":", 1)[0]
    c = httpx.Client(base_url=a.base, timeout=30)

    def post(path, body, h, method="POST"):
        r = c.request(method, path, json=body, headers=h)
        j = r.json()
        if r.status_code >= 300 or not j.get("ok"):
            raise SystemExit(f"seed failed {path}: {r.status_code} {r.text[:300]}")
        return j["value"]

    def seed(title, word):
        epic = post("/v1/tickets", {"kind": "epic", "work_type": "feature", "title": title}, owner)["id"]
        story = post("/v1/tickets", {"kind": "story", "work_type": "feature", "title": f"{word} story",
                                     "parent_id": epic, "description": f"{word} slice"}, agent)["id"]
        doc = post("/v1/docs", {"doc_type": "note", "title": f"{word} note", "body_md": f"{word} evidence",
                                "scope": story}, agent)["id"]
        crit = post("/v1/criteria", {"ticket_id": story, "text": f"{word} works", "check": "look"}, agent)["id"]
        msg = post("/v1/messages", {"ticket_id": story, "kind": "note", "text": f"{word} thread note"}, agent)["id"]
        return {"epic": epic, "story": story, "doc": doc, "crit": crit, "msg": msg}

    A = seed("Alpha (shared)", "zebra")
    B = seed("Bravo (private)", "zebra")
    post(f"/v1/epics/{A['epic']}/members", {"members": [gid]}, owner, method="PUT")
    post(f"/v1/gates/{A['story']}/demo/open", {"note": "look?"}, agent)

    rows = []

    def probe(cls, method, path, expect, body=None, params=None, h=guest, note=""):
        kw = {"params": params} if params else {}
        if body is not None:
            kw["json"] = body
        r = c.request(method, path, headers=h, **kw)
        try:
            err = r.json().get("error") or {}
        except ValueError:
            err = {}
        code = err.get("code") if isinstance(err, dict) else None
        rows.append({"class": cls, "method": method, "path": path, "expect": expect, "status": r.status_code,
                     "code": code, "ok": r.status_code == expect, "note": note,
                     "message": (err.get("message") if isinstance(err, dict) else str(err))[:160] if err else ""})
        return r

    # ---- refusal classes (403)
    probe("gate answer", "POST", f"/v1/gates/{A['story']}/demo/answer", 403, {"answer": "approved"})
    probe("criterion verdict", "POST", "/v1/me/verdict", 403, {"criterion_id": A["crit"], "verdict": "pass"})
    probe("criterion verdict (PATCH)", "PATCH", f"/v1/criteria/{A['crit']}", 403, {"verdict": "pass"})
    probe("spawn", "POST", "/v1/sessions/spawn", 403, {"participant_id": "x", "role": "engineer", "ticket_id": A["story"]})
    probe("reap", "POST", "/v1/sessions/reap", 403, {"participant_id": "arch"})
    probe("resume", "POST", "/v1/sessions/resume", 403, {"participant_id": "arch"})
    probe("status transition", "PATCH", f"/v1/tickets/{A['story']}", 403, {"status": "dropped"})
    probe("ticket create", "POST", "/v1/tickets", 403, {"kind": "story", "work_type": "feature", "title": "g",
                                                         "parent_id": A["epic"]})
    probe("doc create", "POST", "/v1/docs", 403, {"doc_type": "note", "title": "g", "body_md": "g", "scope": A["epic"]})
    probe("link write", "POST", "/v1/links", 403, {"from_id": A["story"], "to_id": A["doc"], "relation": "evidence_for"})
    probe("membership edit", "PUT", f"/v1/epics/{A['epic']}/members", 403, {"members": []})
    probe("admin", "GET", "/v1/admin/teammates", 403)
    probe("settings", "GET", "/v1/admin/settings", 403)
    probe("models", "GET", "/v1/models", 403)
    probe("Code tab", "GET", "/v1/code", 403)
    probe("Code chat (VS Code)", "POST", "/v1/code/session", 403, {})
    probe("workflows", "GET", "/v1/workflows", 403)
    probe("operator aggregate: library", "GET", "/v1/library", 403)
    probe("operator aggregate: recall", "GET", "/v1/recall", 403, params={"q": "zebra"})
    probe("operator aggregate: activity", "GET", "/v1/activity", 403)
    probe("message kind (steer)", "POST", "/v1/messages", 403, {"ticket_id": A["story"], "kind": "steer", "text": "x"})
    # ---- scoped: a non-member object is a 404, the same body as a missing id
    probe("scoped: ticket", "GET", f"/v1/tickets/{B['story']}", 404)
    probe("scoped: missing ticket", "GET", "/v1/tickets/s-0000000000", 404, note="same body as non-member")
    probe("scoped: doc", "GET", f"/v1/docs/{B['doc']}", 404)
    probe("scoped: message", "GET", f"/v1/messages/{B['msg']}", 404)
    probe("scoped: board", "GET", f"/v1/board/{B['epic']}", 404)
    probe("scoped: lookup", "GET", "/v1/lookup", 404, params={"scope": B["epic"], "q": "zebra"})
    probe("scoped: post on non-member", "POST", "/v1/messages", 404, {"ticket_id": B["story"], "kind": "note", "text": "x"})
    # ---- allowed on the member epic
    probe("allowed: read epic", "GET", f"/v1/board/{A['epic']}", 200)
    probe("allowed: read story", "GET", f"/v1/tickets/{A['story']}", 200)
    probe("allowed: question", "POST", "/v1/messages", 200, {"ticket_id": A["story"], "kind": "question", "to": "arch",
                                                              "text": "why zebra?"})
    probe("allowed: note", "POST", "/v1/messages", 200, {"ticket_id": A["story"], "kind": "note", "text": "noted"})
    up = c.post("/v1/artifacts/upload", headers=guest, files={"file": ("notes.txt", b"plain notes\n", "text/plain")})
    art = up.json()["value"]["id"] if up.status_code == 200 else None
    rows.append({"class": "allowed: upload", "method": "POST", "path": "/v1/artifacts/upload", "expect": 200,
                 "status": up.status_code, "code": None, "ok": up.status_code == 200, "note": "", "message": ""})
    probe("allowed: finalise on member epic", "POST", "/v1/artifacts/finalize", 200,
          {"artifact_ids": [art], "ticket_id": A["story"]})
    # ---- secret screen (on the epic with a guest member, from a teammate)
    probe("secret screen", "POST", "/v1/messages", 422, {"ticket_id": A["story"], "kind": "note",
                                                         "text": f"token {GITHUB_SAMPLE}"}, h=agent,
          note="error names the class (github-token)")

    # ---- review round 2 (architect m-33154269a9): one probe per blocker and should-fix, plus the nits
    b_ids = set(B.values())
    admin = {"X-Admin": a.admin}

    def leak_row(cls, method, path, r, ok, note):
        rows.append({"class": cls, "method": method, "path": path, "expect": 200, "status": r.status_code,
                     "code": None, "ok": r.status_code == 200 and ok, "note": note, "message": ""})

    def same_404(cls, path, f, m, fid, mid):
        same = f.status_code == m.status_code == 404 and f.text == m.text.replace(mid, fid)
        rows.append({"class": cls, "method": "GET/POST", "path": path, "expect": 404, "status": f.status_code,
                     "code": (f.json().get("error") or {}).get("code") if f.status_code >= 400 else None,
                     "ok": same, "note": f"body identical to a missing id: {same}", "message": ""})

    post("/v1/links", {"from_id": A["story"], "to_id": B["story"], "relation": "blocks"}, agent)
    cur = c.get("/v1/context", params={"ticket_id": A["story"]}, headers=guest).json()["value"]["cursor"]
    post("/v1/messages", {"ticket_id": B["story"], "kind": "note", "text": "BRAVO-ONLY-TEXT"}, agent)
    post("/v1/messages", {"ticket_id": B["story"], "kind": "question", "to": gid, "text": "BRAVO-ONLY-ASK"}, agent)
    r = c.get("/v1/context_delta", params={"cursor": cur, "ticket_id": A["story"]}, headers=guest)
    leaked = "BRAVO-ONLY" in r.text or any(x in r.text for x in b_ids)
    leak_row("r2 B1: context_delta (A blocks B)", "GET", "/v1/context_delta", r, not leaked,
             f"B text or ids in the delta: {leaked}")
    post("/v1/tickets", {"kind": "story", "work_type": "feature", "title": "quokka private", "parent_id": B["epic"]},
         agent)
    r = c.get("/v1/tickets/table", params={"q": "quokka"}, headers=guest)
    v = r.json().get("value") or {}
    leak_row("r2 B2: tickets/table count oracle", "GET", "/v1/tickets/table?q=quokka", r,
             v.get("count") == 0 == len(v.get("rows", [])), f"count={v.get('count')} rows={len(v.get('rows', []))}")
    qf = c.post("/v1/messages", headers=guest, json={"ticket_id": A["story"], "kind": "question", "to": "arch",
                "text": "see", "quotes": [{"source": "message", "id": B["msg"], "text": "zebra thread note"}]})
    qm = c.post("/v1/messages", headers=guest, json={"ticket_id": A["story"], "kind": "question", "to": "arch",
                "text": "see", "quotes": [{"source": "message", "id": "m-0123456789", "text": "zebra thread note"}]})
    same = qf.status_code == qm.status_code >= 400 and qf.text.replace(B["msg"], "m-0123456789") == qm.text
    rows.append({"class": "r2 #3: quote a B message", "method": "POST", "path": "/v1/messages (quotes)",
                 "expect": qm.status_code, "status": qf.status_code, "code": (qf.json().get("error") or {}).get("code"),
                 "ok": same, "note": f"same error as a missing source: {same}", "message": ""})
    same_404("r2 #4: ?around=<B message>", "/v1/messages?around=",
             c.get("/v1/messages", params={"around": B["msg"]}, headers=guest),
             c.get("/v1/messages", params={"around": "m-0123456789"}, headers=guest), B["msg"], "m-0123456789")
    same_404("r2 #4: reply_to=<B message>", "/v1/messages (reply_to)",
             c.post("/v1/messages", headers=guest, json={"ticket_id": A["story"], "kind": "note", "text": "re",
                                                        "reply_to": B["msg"]}),
             c.post("/v1/messages", headers=guest, json={"ticket_id": A["story"], "kind": "note", "text": "re",
                                                        "reply_to": "m-0123456789"}), B["msg"], "m-0123456789")
    hop = post("/v1/docs", {"doc_type": "note", "title": "hop", "body_md": "hop body", "scope": B["story"]}, agent)["id"]
    hop_link = post("/v1/links", {"from_id": A["story"], "to_id": hop, "relation": "evidence_for"}, agent)["id"]
    r = c.get(f"/v1/docs/{hop}", headers=guest)
    leak_row("r2 #5: one-hop doc scope", "GET", f"/v1/docs/{hop}", r,
             (r.json().get("value") or {}).get("scope") is None and B["story"] not in r.text,
             f"scope={(r.json().get('value') or {}).get('scope')!r}")
    c.post("/v1/participants", json={"type": "agent", "role": "engineer", "handle": "eng-bravo", "id": "eng-bravo"},
           headers=admin)
    c.put("/v1/sessions/sid-eng-bravo", json={"participant_id": "eng-bravo", "ticket_id": B["story"],
                                              "pool_id": "local", "state": "alive"}, headers=admin)
    r = c.get("/v1/seats", headers=guest)
    leaked = "eng-bravo" in r.text or any(x in r.text for x in b_ids)
    leak_row("r2 #6: /v1/seats", "GET", "/v1/seats", r, not leaked, f"B seat or ids listed: {leaked}")
    for cls, text in (("host-path", "logs in C:\\Users\\someone\\AppData\\Local\\x"),
                      ("api-key-header", "x-api-key: 0123456789abcdef"),
                      ("token-assignment", "DB_PASS=hunter&2!hunter")):
        probe(f"r2 #7: screen {cls}", "POST", "/v1/messages", 422,
              {"ticket_id": A["story"], "kind": "note", "text": text}, h=agent, note=f"names ({cls})")
    probe("r2 #7: EDP8_OWNER-style value passes", "POST", "/v1/messages", 200,
          {"ticket_id": A["story"], "kind": "note", "text": "EDP8_OWNER=owner"}, h=agent)
    post("/v1/status", {"ticket_id": A["story"], "status": "blocked",
                        "note": "see C:\\Users\\someone\\secrets\\x.json"}, agent)  # status notes are not write-screened
    r = c.get("/v1/messages", params={"ticket_id": A["story"]}, headers=guest)
    leak_row("r2 #7: read boundary (status note)", "GET", "/v1/messages", r,
             "someone" not in r.text and "withheld from a guest" in r.text, "host path withheld at read")
    c.delete(f"/v1/links/{hop_link}", headers=owner)
    probe("r2 nit: link delete revokes the hop", "GET", f"/v1/docs/{hop}", 404)
    same_404("r2 nit: to=<out-of-scope seat>", "/v1/messages (to)",
             c.post("/v1/messages", headers=guest, json={"ticket_id": A["story"], "kind": "question",
                                                        "to": "eng-bravo", "text": "hi"}),
             c.post("/v1/messages", headers=guest, json={"ticket_id": A["story"], "kind": "question",
                                                        "to": "nobody-zz", "text": "hi"}), "eng-bravo", "nobody-zz")

    # ---- aggregates: the guest's views never name B
    for name, path, params in [("find", "/v1/find", {"q": "zebra"}), ("context", "/v1/context", None),
                               ("attention", "/v1/me/attention", None), ("events", "/v1/events", {"limit": 500})]:
        r = c.get(path, headers=guest, params=params)
        leaked = sorted(x for x in b_ids if x in r.text)
        rows.append({"class": f"aggregate: {name}", "method": "GET", "path": path, "expect": 200, "status": r.status_code,
                     "code": None, "ok": r.status_code == 200 and not leaked, "note": f"B ids leaked: {leaked or 'none'}",
                     "message": ""})

    # ---- the SPA shell at /ui is static (no board data); the legacy /ui data pages refuse a guest (pytest
    # test_route_table_... calls each one) — here: the shell names no board object
    r = c.get("/ui/tickets", params={"as": gid, "token": guest["X-Token"]})
    leaked = sorted(x for x in set(A.values()) | set(B.values()) if x in r.text)
    rows.append({"class": "legacy /ui path (SPA shell)", "method": "GET", "path": "/ui/tickets", "expect": 200,
                 "status": r.status_code, "code": None, "ok": not leaked, "note": f"board ids in the page: {leaked or 'none'}",
                 "message": ""})

    # ---- SSE (the page's watch=true view feed, the whole-board leak the spike found): A's new ticket, never B's
    seen: list[str] = []

    def listen():
        try:
            with httpx.stream("GET", f"{a.base}/v1/feed", params={"watch": "true"}, headers=guest, timeout=8) as s:
                for line in s.iter_lines():
                    seen.append(line)
        except httpx.HTTPError:
            pass

    t = threading.Thread(target=listen, daemon=True)
    t.start()
    time.sleep(1.0)
    na = post("/v1/tickets", {"kind": "story", "work_type": "feature", "title": "after-open A", "parent_id": A["epic"]},
              agent)["id"]
    nb = post("/v1/tickets", {"kind": "story", "work_type": "feature", "title": "after-open B", "parent_id": B["epic"]},
              agent)["id"]
    time.sleep(2.0)
    feed = "\n".join(seen)
    rows.append({"class": "aggregate: SSE feed", "method": "GET", "path": "/v1/feed?watch=true", "expect": 200, "status": 200,
                 "code": None, "ok": na in feed and nb not in feed and not any(x in feed for x in b_ids),
                 "note": f"A's new ticket seen: {na in feed}; B's: {nb in feed}", "message": ""})

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "live-probes.json").write_text(json.dumps({"base": a.base, "A": A, "B": B, "rows": rows}, indent=2),
                                          encoding="utf-8")
    md = ["# e0cec S5 live probes (guest token, private board)", "",
          f"Board {a.base}, token mode, EDP8_BIND cleared. Guest `{gid}` is a member of {A['epic']} only.", "",
          "| class | call | expect | got | code | ok | note |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['class']} | `{r['method']} {r['path']}` | {r['expect']} | {r['status']} | {r['code'] or ''} | "
                  f"{'yes' if r['ok'] else '**NO**'} | {r['note'] or r['message']} |")
    bad = [r for r in rows if not r["ok"]]
    md += ["", f"{len(rows) - len(bad)}/{len(rows)} probes as expected."]
    (out / "live-probes.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
