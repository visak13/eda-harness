"""edp8 web board — read-only HTML views over the Board (no external assets).

Routes: /ui (epics) · /ui/epic/{id} (tree, gates, thread) · /ui/ticket/{id} · /ui/doc/{id}.
Identity for reads: ?as=<participant> (default owner). Auto-refreshes every 10s on the epic page.
"""

from __future__ import annotations

import html
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from .board import Board
from .schemas import TicketKind, Verdict

_CSS = """
body{font:14px/1.45 system-ui,Segoe UI,sans-serif;margin:0;background:#0f1115;color:#e6e6e6}
a{color:#7cc4ff;text-decoration:none}a:hover{text-decoration:underline}
header{padding:10px 18px;background:#171a21;border-bottom:1px solid #2a2f3a;display:flex;gap:18px;align-items:center}
main{padding:16px 18px;max-width:1200px}
.badge{display:inline-block;padding:1px 7px;border-radius:10px;font-size:12px;background:#2a2f3a;margin-left:6px}
.s-done{background:#1f6f3f}.s-in_progress{background:#2b5fa8}.s-in_review{background:#7a5a1c}.s-ready{background:#3b7a8a}
.s-blocked{background:#8a2b2b}.s-signed_off{background:#4a4a7a}.s-designed{background:#4a4a4a}.s-drafted{background:#333}
.s-partial{background:#6a4a1c}.s-dropped{background:#444}
ul.tree{list-style:none;padding-left:18px;border-left:1px dashed #2a2f3a}ul.tree>li{margin:6px 0}
.gate{background:#5a1f7a;padding:2px 8px;border-radius:6px;margin-left:6px;font-size:12px}
table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #2a2f3a;padding:6px 8px;text-align:left;vertical-align:top}
th{color:#9aa4b2;font-weight:600}.muted{color:#9aa4b2}.msg{margin:8px 0;padding:8px 10px;background:#171a21;border-radius:6px}
.msg .who{color:#9aa4b2;font-size:12px}pre{white-space:pre-wrap;background:#171a21;padding:12px;border-radius:6px}
.cols{display:grid;grid-template-columns:1.1fr 1fr;gap:22px}h2{margin:18px 0 8px;font-size:16px}
"""


def _page(title: str, body: str, refresh: int | None = None) -> str:
    meta = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>{meta}"
            f"<style>{_CSS}</style></head><body><header><b>edp8 board</b>"
            f"<a href='/ui'>epics</a><a href='/docs'>api</a><span class='muted'>{html.escape(title)}</span></header>"
            f"<main>{body}</main></body></html>")


def _e(s: Any) -> str:
    return html.escape(str(s))


def _badge(status: str) -> str:
    return f"<span class='badge s-{_e(status)}'>{_e(status)}</span>"


def router(board: Board) -> APIRouter:
    r = APIRouter()

    @r.get("/ui", response_class=HTMLResponse)
    def epics():
        rows = []
        for t in board.store.query("ticket", {"kind": TicketKind.epic}, limit=200):
            crits = board.criteria(t.id)
            passed = sum(c.verdict == Verdict.passed for c in crits)
            rows.append(f"<tr><td><a href='/ui/epic/{t.id}'>{_e(t.id)}</a></td><td>{_badge(t.status)}</td>"
                        f"<td>{passed}/{len(crits)}</td><td>{_e(t.title[:160])}</td>"
                        f"<td class='muted'>{_e(t.created_at.strftime('%Y-%m-%d %H:%M'))}</td></tr>")
        body = "<h2>Epics</h2><table><tr><th>id</th><th>status</th><th>criteria</th><th>words</th><th>created</th></tr>" \
               + "".join(rows) + "</table>"
        return _page("epics", body)

    def _node_html(n: dict[str, Any]) -> str:
        gates = "".join(f"<span class='gate'>gate: {_e(g)}</span>" for g in n["gates"])
        blocked = f"<span class='muted'> blocked by {', '.join(n['blocked_by'])}</span>" if n["blocked_by"] else ""
        kids = "".join(f"<li>{_node_html(k)}</li>" for k in n["children"])
        who = f"<span class='muted'> · {_e(n['assignee'])}</span>" if n["assignee"] else ""
        return (f"<a href='/ui/ticket/{n['id']}'>{_e(n['id'])}</a> <b>{_e(n['kind'])}</b>/{_e(n['work_type'])}"
                f"{_badge(n['status'])} <span class='muted'>crit {_e(n['criteria'])}</span>{who}{gates}{blocked}"
                f"<div>{_e(n['title'][:140])}</div>" + (f"<ul class='tree'>{kids}</ul>" if kids else ""))

    @r.get("/ui/epic/{epic_id}", response_class=HTMLResponse)
    def epic(epic_id: str, as_: str = Query(default="owner", alias="as")):
        bd = board.board(epic_id)
        tree = _node_html(bd["epic"])
        thread = board.thread(epic_id, limit=60)
        msgs = "".join(
            f"<div class='msg'><div class='who'>{_e(m.created_by)} · {_e(m.kind)} → {_e(m.to or 'thread')} · "
            f"{_e(m.created_at.strftime('%H:%M:%S'))}</div>{_e(m.text)}</div>" for m in reversed(thread))
        docs = "".join(f"<li><a href='/ui/doc/{d.id}'>{_e(d.title)}</a> <span class='muted'>{_e(d.doc_type)} v{d.version}</span></li>"
                       for d in board.store.query("doc", {"scope": epic_id}, limit=100))
        gates = "".join(f"<span class='gate'>{_e(t)} · {_e(g)}</span> " for t, g in bd["open_gates"]) or "<span class='muted'>none</span>"
        counts = " ".join(f"{_badge(k)} {v}" for k, v in bd["counts"].items())
        body = (f"<h2>{_e(epic_id)}</h2><p>{_e(bd['words'][:400])}</p><p>{counts}</p><p>open gates: {gates}</p>"
                f"<div class='cols'><div><h2>tickets</h2><ul class='tree'><li>{tree}</li></ul>"
                f"<h2>docs in this epic</h2><ul>{docs}</ul></div>"
                f"<div><h2>epic thread (newest first)</h2>{msgs}</div></div>")
        return _page(f"epic {epic_id}", body, refresh=10)

    @r.get("/ui/ticket/{ticket_id}", response_class=HTMLResponse)
    def ticket(ticket_id: str):
        t = board.ticket(ticket_id)
        crits = board.criteria(ticket_id)
        crows = "".join(
            f"<tr><td>{_e(c.id)}</td><td>{_e(c.check)}</td><td>{_e(c.checked_by)}</td><td>{_badge(c.verdict)}</td>"
            f"<td>{'<a href=/ui/doc/' + c.evidence_ref + '>evidence</a>' if c.evidence_ref else ''}</td><td>{_e(c.text)}</td></tr>"
            for c in crits)
        docs = "".join(f"<li><a href='/ui/doc/{d.id}'>{_e(d.title)}</a> <span class='muted'>{_e(d.doc_type)} v{d.version}</span></li>"
                       for d in board.linked_docs(ticket_id))
        thread = board.thread(ticket_id, limit=100)
        msgs = "".join(
            f"<div class='msg'><div class='who'>{_e(m.created_by)} · {_e(m.kind)} → {_e(m.to or 'thread')} · "
            f"{_e(m.created_at.strftime('%Y-%m-%d %H:%M:%S'))}</div>{_e(m.text)}</div>" for m in reversed(thread))
        epic_id = board.epic_of(t).id
        body = (f"<h2>{_e(t.id)} {_badge(t.status)} <span class='muted'>{_e(t.kind)}/{_e(t.work_type)} · assignee {_e(t.assignee)}</span></h2>"
                f"<p><a href='/ui/epic/{epic_id}'>↑ epic {epic_id}</a></p><p>{_e(t.title)}</p>"
                + (f"<p>design: <a href='/ui/doc/{t.design_ref}'>{_e(t.design_ref)}</a></p>" if t.design_ref else "")
                + f"<h2>criteria</h2><table><tr><th>id</th><th>check</th><th>by</th><th>verdict</th><th></th><th>text</th></tr>{crows}</table>"
                f"<h2>linked docs</h2><ul>{docs}</ul><h2>thread</h2>{msgs}")
        return _page(f"ticket {ticket_id}", body, refresh=15)

    @r.get("/ui/doc/{doc_id}", response_class=HTMLResponse)
    def doc(doc_id: str, version: int | None = None):
        d = board.doc(doc_id, version)
        versions = " ".join(f"<a href='/ui/doc/{doc_id}?version={v}'>v{v}</a>" for v in board.store.doc_versions(doc_id))
        body = (f"<h2>{_e(d.title)} <span class='muted'>{_e(d.doc_type)} · v{d.version} · {_e(d.owner_role)} · scope {_e(d.scope)}</span></h2>"
                f"<p>versions: {versions}</p><pre>{_e(d.body_md)}</pre>")
        return _page(f"doc {doc_id}", body)

    return r
