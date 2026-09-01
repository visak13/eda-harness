"""Slack-like, dependency-free HTML views over the edp8 Board."""
from __future__ import annotations

import html
import re as _re
from datetime import datetime
from typing import Any, Callable, Iterable
from urllib.parse import quote

import markdown as _markdown

_SCRIPT_RX = _re.compile(r"<\s*script\b.*?<\s*/\s*script\s*>", _re.IGNORECASE | _re.DOTALL)
_ON_ATTR_RX = _re.compile(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", _re.IGNORECASE)


def _md(body: str) -> str:
    """Render doc markdown to HTML (fenced code + tables), stripped of scripts and
    inline handlers — docs are fleet-authored, but the browser gets no excuses."""
    rendered = _markdown.markdown(body or "", extensions=["fenced_code", "tables", "sane_lists"])
    rendered = _SCRIPT_RX.sub("", rendered)
    return _ON_ATTR_RX.sub("", rendered)

from fastapi import APIRouter, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from . import delivery
from .avatar_preferences import load_avatar_preferences, save_avatar_preference
from .avatars import HUMAN_AVATAR_IDS, avatar_id_for, avatar_picker_html, human_avatar_svg, role_avatar_svg, system_avatar_svg
from .board import Board, BoardError
from .schemas import Gate, MessageKind, Participant, Role, TicketKind, TicketStatus, Verdict

_TERMINAL = (TicketStatus.done, TicketStatus.partial, TicketStatus.dropped)
_CSS = """
/* Tokens */
:root{color-scheme:dark;--rail:#19171d;--app:#1f1d24;--panel:#25232b;--raised:#2d2a35;--hover:#35313e;--border:#595361;--text:#f7f5f8;--secondary:#c3bec8;--muted:#9b95a1;--brand:#7c3aed;--cyan:#36c5f0;--success:#2eb67d;--warning:#ecb22e;--danger:#e85d75;--link:#70c5f9;--focus:#a78bfa;--rail-w:64px;--side-w:272px}
/* Reset and accessibility */
*{box-sizing:border-box}html,body{margin:0;min-height:100%;background:var(--app);color:var(--text);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,Helvetica,Arial,sans-serif}body{overflow-x:hidden}a{color:var(--link);text-decoration:none}a:hover{text-decoration:underline}button,input,select{font:inherit;color:inherit}button,input,select,summary,a{outline:none}:focus-visible{outline:2px solid var(--focus);outline-offset:2px}button,.nav-link,.utility-link,.epic-row{min-height:40px}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}.muted{color:var(--muted)}.secondary{color:var(--secondary)}.mono,.ticket-chip,.object-id{font:12px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace}
/* App shell */
.app-shell{min-height:100vh;display:grid;grid-template-columns:var(--rail-w) var(--side-w) minmax(0,1fr)}.workspace-rail{position:fixed;inset:0 auto 0 0;width:var(--rail-w);z-index:5;background:var(--rail);border-right:1px solid var(--border);display:flex;flex-direction:column;align-items:center;padding:12px 8px}.board-logo{display:grid;place-items:center;width:44px;height:44px;border-radius:10px;background:var(--raised)}.rail-spacer{flex:1}.rail-avatar{display:grid;place-items:center;width:48px;height:48px}.avatar-svg{display:block;border-radius:8px;flex:none}.sidebar{position:fixed;inset:0 auto 0 var(--rail-w);width:var(--side-w);z-index:4;background:var(--panel);border-right:1px solid var(--border);display:flex;flex-direction:column}.sidebar-brand{height:72px;padding:16px;border-bottom:1px solid var(--border);font-size:18px;font-weight:700;display:flex;align-items:center}.sidebar-body{padding:12px;overflow:auto}.sidebar-local{margin-top:24px}.main-pane{grid-column:3;min-width:0}.channel-header{position:sticky;top:0;z-index:3;min-height:72px;background:#25232bf7;border-bottom:1px solid var(--border);padding:11px 24px;display:flex;align-items:center}.channel-header h1{font-size:18px;margin:0}.channel-header p{margin:3px 0 0;color:var(--secondary)}.page-grid{display:grid;grid-template-columns:minmax(0,1fr)}.page-grid.with-context{grid-template-columns:minmax(0,1fr) 340px}.content{min-width:0;padding:24px}.content-inner{max-width:1180px;margin:auto}.context-panel{border-left:1px solid var(--border);background:var(--panel);padding:20px 16px;min-width:0}.content.has-composer{padding-bottom:170px}
/* Navigation */
.nav-list{display:grid;gap:4px}.nav-link,.utility-link{display:flex;align-items:center;gap:10px;padding:8px 12px;border-radius:6px;color:var(--secondary);font-weight:600}.nav-link:hover,.nav-link.active{background:var(--hover);color:var(--text);text-decoration:none}.nav-link.active{box-shadow:inset 3px 0 var(--cyan)}.utility-link{margin-top:12px;color:var(--muted)}.identity{display:flex;align-items:center;gap:10px;min-width:0}.identity-copy{min-width:0}.identity-copy strong,.identity-copy span{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.identity-copy span{font-size:12px;color:var(--secondary)}.nav-stat{display:flex;justify-content:space-between;color:var(--secondary);padding:7px 4px;font-size:13px}.nav-stat b{color:var(--text)}
/* Conversation */
.section-header{display:flex;align-items:center;gap:8px;margin:24px 0 12px}.section-header h2{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--secondary);margin:0}.count{background:var(--raised);border-radius:99px;padding:1px 7px;font-size:12px}.conversation{max-width:760px}.message,.question-unit{display:grid;grid-template-columns:40px minmax(0,1fr);gap:12px;padding:7px 0}.message.grouped{padding-top:1px}.avatar-placeholder{width:36px}.message-head{display:flex;align-items:baseline;gap:8px;min-width:0}.message-head strong{font-size:14px;font-weight:650}.message-meta{font-size:12px;color:var(--muted)}.message-text{margin-top:3px;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.55}.message-target{color:var(--secondary);font-size:12px;margin-left:8px}.question-unit{margin-bottom:20px}.question-bubble{background:var(--raised);border:1px solid var(--border);border-radius:10px 10px 0 0;padding:12px 14px}.delivery-note{color:var(--secondary);font-size:12px;margin:8px 0}.reply-form{display:flex;gap:8px;background:var(--panel);border:1px solid var(--border);border-top:0;border-radius:0 0 10px 10px;padding:10px}.reply-form input[name=text]{flex:1}.system-event{display:grid;grid-template-columns:28px minmax(0,1fr);gap:10px;border-left:1px solid var(--border);margin-left:13px;padding:8px 0 8px 14px;color:var(--secondary);font-size:13px}.event-time{display:block;color:var(--muted);font-size:12px}.ticket-chip{display:inline-flex;align-items:center;min-height:24px;padding:2px 7px;border:1px solid var(--border);border-radius:6px;background:var(--panel)}
/* Forms */
form{margin:0}input,select{border:1px solid var(--border);background:var(--app);border-radius:6px;min-height:40px;padding:8px 10px;max-width:100%}input::placeholder{color:#aaa4af}button{border:0;border-radius:6px;background:var(--brand);padding:8px 16px;font-weight:700;cursor:pointer}button:hover{background:#8b5cf6}.composer{position:fixed;z-index:4;left:calc(var(--rail-w) + var(--side-w));right:0;bottom:0;background:var(--app);border-top:1px solid var(--border);padding:24px}.composer-card{max-width:760px;margin:auto;background:var(--raised);border:1px solid var(--border);border-radius:10px;padding:10px;box-shadow:0 8px 24px #0008}.composer-top{display:grid;grid-template-columns:1fr 1fr auto;gap:8px}.composer-main{width:100%;margin-top:8px}.composer-footer{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:8px;font-size:12px;color:var(--secondary)}.avatar-picker summary{cursor:pointer;min-height:40px;display:flex;align-items:center;color:var(--secondary)}.avatar-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;margin:8px 0 12px}.avatar-choice input{position:absolute;opacity:0}.avatar-choice span{display:grid;place-items:center;gap:2px;padding:5px;border:2px solid transparent;border-radius:10px;cursor:pointer}.avatar-choice small{font-size:10px;color:var(--secondary)}.avatar-choice input:checked+span{border-color:var(--cyan);background:var(--hover)}.avatar-choice input:focus-visible+span{outline:2px solid var(--focus);outline-offset:2px}
/* Cards and metadata */
.badge{display:inline-flex;align-items:center;min-height:24px;padding:2px 8px;border-radius:99px;background:#3b3744;font-size:12px;font-weight:700;text-transform:capitalize}.s-done,.s-pass{background:#174f3b}.s-blocked,.s-fail{background:#662c38}.s-in_progress,.s-ready{background:#204d60}.s-in_review,.s-partial{background:#604a1c}.alert{border:1px solid var(--danger);border-left-width:4px;background:#3a242b;border-radius:8px;padding:12px 14px;margin-bottom:12px}.alert-ok{border-color:var(--success);background:#1c322a}.people-list{display:grid;gap:2px;margin-bottom:8px}.people-row{display:flex;align-items:center;gap:8px;padding:4px 6px;border-radius:6px;font-size:13px;cursor:default}.people-row:hover{background:var(--hover)}.people-row .muted{margin-left:auto;font-size:12px}.empty-state{text-align:center;padding:24px;border:1px dashed var(--border);border-radius:10px;color:var(--secondary)}.empty-state h3{font-size:14px;color:var(--text);margin:6px 0 2px}.empty-state p{margin:0}.gate-card{border:1px solid var(--border);border-left:3px solid var(--warning);border-radius:10px;background:var(--raised);padding:12px;margin-bottom:12px}.gate-card h3{font-size:14px;margin:0}.gate-card p{margin:5px 0;color:var(--secondary);font-size:13px}.gate-card form{display:grid;gap:8px;margin-top:10px}.epic-list{display:grid;gap:4px}.epic-row{position:relative;display:grid;grid-template-columns:minmax(0,1fr) 130px 110px auto 20px;align-items:center;gap:16px;background:var(--panel);border:1px solid transparent;border-radius:8px;padding:12px 14px 12px 18px;color:var(--text);min-height:72px}.epic-row:before{content:"";position:absolute;left:0;top:8px;bottom:8px;width:4px;background:var(--cyan)}.epic-row:hover{background:var(--hover);border-color:var(--border);text-decoration:none}.epic-title{font-weight:650}.epic-title .object-id{display:block;color:var(--link)}.epic-meta{font-size:12px;color:var(--secondary)}.progress{height:4px;background:var(--border);border-radius:4px;margin-top:5px;overflow:hidden}.progress span{display:block;height:100%;background:var(--success)}.reader-lead{font-size:22px;margin:0 0 20px}.meta-row{display:flex;justify-content:space-between;gap:12px;border-bottom:1px solid var(--border);padding:7px 0;color:var(--secondary)}
/* Ticket tree */
.ticket-tree,.ticket-tree ul{list-style:none;margin:0;padding:0}.ticket-tree ul{margin-left:16px;border-left:2px solid var(--border);padding-left:14px}.ticket-node{margin:7px 0}.ticket-card{display:block;background:var(--raised);border:1px solid var(--border);border-radius:8px;padding:10px;color:var(--text)}.ticket-card:hover{background:var(--hover);text-decoration:none}.ticket-card-top{display:flex;align-items:center;gap:7px;flex-wrap:wrap}.ticket-card-title{margin-top:5px;font-size:13px}.node-assignee{margin-left:auto}.marker{font-size:11px;color:var(--warning)}.criterion{border:1px solid var(--border);border-left:3px solid var(--border);border-radius:8px;background:var(--raised);padding:12px;margin-bottom:8px}.criterion.pass{border-left-color:var(--success)}.criterion.fail{border-left-color:var(--danger)}.criterion-head{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.criterion p{margin:7px 0}.criterion-meta{font-size:12px;color:var(--secondary)}
/* Document reader */
.version-control{display:flex;gap:2px;flex-wrap:wrap;margin:12px 0 20px}.version-control a{min-height:40px;display:flex;align-items:center;padding:6px 12px;background:var(--raised);border:1px solid var(--border)}.document-reader{max-width:860px;background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:28px}.document-reader pre{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;max-width:76ch;font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
.doc-md{font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.doc-md h1,.doc-md h2,.doc-md h3{margin:20px 0 8px;line-height:1.3}.doc-md h1{font-size:20px}.doc-md h2{font-size:17px}.doc-md h3{font-size:15px}.doc-md p,.doc-md ul,.doc-md ol{margin:8px 0;max-width:76ch}.doc-md li{margin:3px 0}.doc-md code{background:var(--app);border:1px solid var(--border);border-radius:4px;padding:1px 5px;font:12.5px/1.5 ui-monospace,Consolas,monospace}.doc-md pre{background:var(--app);border:1px solid var(--border);border-radius:8px;padding:12px;overflow-x:auto}.doc-md pre code{border:0;background:none;padding:0}.doc-md table{border-collapse:collapse;margin:10px 0;display:block;overflow-x:auto}.doc-md th,.doc-md td{border:1px solid var(--border);padding:6px 10px;text-align:left}.doc-md blockquote{border-left:3px solid var(--brand);margin:10px 0;padding:4px 14px;color:var(--secondary)}.doc-md a{color:var(--link)}
.kanban{display:grid;grid-template-columns:repeat(5,minmax(150px,1fr));gap:10px;overflow-x:auto;padding-bottom:6px}.kanban-col{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:8px;min-height:90px}.kanban-head{font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--secondary);padding:2px 4px 8px;display:flex;align-items:center;gap:6px}.kanban-card{display:block;background:var(--raised);border:1px solid var(--border);border-radius:8px;padding:8px;margin-bottom:8px;color:var(--text)}.kanban-card:hover{background:var(--hover);text-decoration:none}.kanban-top{display:flex;justify-content:space-between;align-items:center;gap:6px}.kanban-title{font-size:13px;margin:5px 0 3px;line-height:1.35}.kanban-meta{font-size:11px;color:var(--muted);display:flex;gap:6px;flex-wrap:wrap}.kanban-empty{border:1px dashed var(--border);border-radius:8px;min-height:40px}
.convo-list{display:grid;gap:2px;margin-bottom:10px}.convo-row{display:flex;align-items:center;gap:7px;padding:6px 8px;border-radius:6px;color:var(--secondary);min-height:36px}.convo-row:hover{background:var(--hover);text-decoration:none;color:var(--text)}.convo-name{font:12px/1.3 ui-monospace,Consolas,monospace;color:var(--text)}.convo-snip{font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0;flex:1}.unread-dot{width:8px;height:8px;border-radius:50%;background:var(--danger);flex:none}.seat-up{color:var(--success)}
@media(max-width:1100px){.kanban{grid-template-columns:repeat(5,minmax(150px,1fr))}}
.signoff-card{border:1px solid var(--border);border-left:3px solid var(--brand);border-radius:10px;background:var(--raised);padding:14px;margin-bottom:14px}.signoff-card details{margin:10px 0;background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:10px}.signoff-card summary{cursor:pointer;font-weight:650;min-height:32px}.signoff-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:10px}.signoff-actions input[name=note]{flex:1;min-width:220px}.btn-fail{background:#8a3b4b}.btn-fail:hover{background:#a44a5d}
/* Responsive rules */
@media(max-width:1099px){:root{--side-w:220px}.page-grid.with-context{display:block}.context-panel{border-left:0;border-top:1px solid var(--border)}}
@media(max-width:759px){.app-shell{display:block;padding-top:60px}.workspace-rail{width:100%;height:60px;inset:0 0 auto;flex-direction:row;padding:6px 10px}.rail-spacer{flex:1}.sidebar{position:static;width:100%;border-right:0;border-bottom:1px solid var(--border)}.sidebar-brand,.sidebar-local{display:none}.sidebar-body{padding:6px}.nav-list{grid-template-columns:1fr 1fr}.utility-link{display:none}.channel-header{top:60px;padding:10px 14px}.content{padding:16px 12px}.context-panel{padding:16px 12px}.content.has-composer{padding-bottom:310px}.composer{left:0;padding:16px 10px}.composer-top{grid-template-columns:1fr}.composer-footer,.reply-form{align-items:stretch;flex-direction:column}.composer-footer button{width:100%}.question-unit,.message{grid-template-columns:32px minmax(0,1fr);gap:8px}.epic-row{grid-template-columns:minmax(0,1fr) auto}.epic-row .epic-meta{grid-column:1}.chevron{grid-column:2}.document-reader{padding:18px 14px}input,select{width:100%}}
/* Inbox composer: flow-owned by the conversation column, never the viewport */
.content.has-composer{padding-bottom:24px}.content.has-composer .content-inner{min-height:calc(100vh - 120px);display:flex;flex-direction:column}.content.has-composer .page-body{flex:1;min-width:0}.composer{position:sticky;z-index:2;left:auto;right:auto;bottom:0;display:grid;grid-template-columns:40px minmax(0,1fr);gap:12px;max-width:760px;margin:0;padding:24px 0;background:var(--app);border-top:1px solid var(--border)}.composer-card{grid-column:2;max-width:none;margin:0;background:var(--raised);border:1px solid var(--border);border-radius:10px;padding:12px;box-shadow:0 8px 24px #0008}.composer-title{margin:0 0 8px;font-size:13px}.composer-top{grid-template-columns:minmax(0,1fr) minmax(0,1fr) auto}.composer-field{display:grid;gap:3px;min-width:0}.composer-field span{color:var(--secondary);font-size:11px;font-weight:700}.composer-field input,.composer-field select{width:100%}.composer-hint{margin:8px 0 0;color:var(--secondary);font-size:12px;line-height:1.4}.composer-footer{justify-content:flex-end}.composer-footer span{display:none}
@media(max-width:759px){.content.has-composer{padding-bottom:16px}.composer{grid-template-columns:32px minmax(0,1fr);gap:8px;padding:16px 0}.composer-top{grid-template-columns:1fr}}
/* Reduced motion and print */
@media(prefers-reduced-motion:reduce){*{transition:none!important}}@media print{.workspace-rail,.sidebar,.composer{display:none}.app-shell,.page-grid,.page-grid.with-context{display:block}.main-pane{margin:0}.channel-header{position:static}.context-panel{border:0}}
"""

def _e(value: Any) -> str: return html.escape(str(value))

def _icon(name: str, size: int = 16) -> str:
    from .icons import icon
    return icon(name, size)

def _badge(status: Any) -> str:
    value = getattr(status, "value", status)
    return f"<span class='badge s-{_e(value)}'>{_e(str(value).replace('_',' '))}</span>"

def _section_header(title: str, count: int | None = None) -> str:
    return f"<div class='section-header'><h2>{_e(title)}</h2>{f'<span class=count>{count}</span>' if count is not None else ''}</div>"

def _empty_state(icon: str, title: str, text: str) -> str:
    return f"<div class='empty-state'>{_icon(icon,22)}<h3>{_e(title)}</h3><p>{_e(text)}</p></div>"

def _ticket_chip(ticket_id: str) -> str:
    return f"<a class='ticket-chip' href='/ui/ticket/{quote(str(ticket_id),safe='')}'>{_e(ticket_id)}</a>"

def _format_time(value: datetime, include_date: bool = False) -> str:
    return value.strftime("%d %b %H:%M" if include_date else "%H:%M")

def _hidden_identity_fields(participant: Participant, token: str | None) -> str:
    return f"<input type='hidden' name='as_' value='{_e(participant.id)}'><input type='hidden' name='token' value='{_e(token or '')}'>"

def _page(title: str, body: str, *, refresh: int | None = None, active_nav: str | None = None, sidebar: str = "", context: str = "", composer: str = "", identity: str = "") -> str:
    meta = f"<meta http-equiv='refresh' content='{refresh}'>" if refresh else ""
    nav = (f"<nav class='nav-list'><a class='nav-link{' active' if active_nav=='me' else ''}' href='/ui/me'>{_icon('inbox')} My inbox</a>"
           f"<a class='nav-link{' active' if active_nav=='epics' else ''}' href='/ui'>{_icon('epic')} Projects</a>"
           f"<a class='nav-link{' active' if active_nav=='activity' else ''}' href='/ui/activity'>{_icon('thread')} Activity</a></nav>"
           f"<a class='utility-link' href='/docs'>API reference</a>")
    right = f"<aside class='context-panel'>{context}</aside>" if context else ""
    return f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{_e(title)} · edp8</title>{meta}<style>{_CSS}</style></head><body><div class='app-shell'><aside class='workspace-rail'><a class='board-logo' href='/ui' aria-label='edp8 board'>{system_avatar_svg(36)}</a><div class='rail-spacer'></div><div class='rail-avatar'>{identity or system_avatar_svg(36)}</div></aside><aside class='sidebar'><div class='sidebar-brand'>edp8 board</div><div class='sidebar-body'>{nav}<div class='sidebar-local'>{sidebar}</div></div></aside><main class='main-pane'><header class='channel-header'><div><h1>{_e(title)}</h1><p>Project-persistent board workspace</p></div></header><div class='page-grid{' with-context' if context else ''}'><section class='content{' has-composer' if composer else ''}'><div class='content-inner'><div class='page-body'>{body}</div>{composer}</div></section>{right}</div></main></div></body></html>"

def router(board: Board, verify: Callable[[str, str | None], Participant] | None = None) -> APIRouter:
    r = APIRouter()
    preferences = load_avatar_preferences()
    def _me(as_: str, token: str | None) -> Participant: return verify(as_, token) if verify else board.participant(as_)
    def _qs(p: Participant, token: str | None) -> str: return f"as={quote(p.id)}" + (f"&token={quote(token)}" if token else "")
    def _participant(pid: str | None) -> Participant | None:
        try: return board.store.get("participant", pid) if pid else None  # type: ignore[return-value]
        except Exception: return None
    def _participant_label(p: Participant | None) -> str: return (p.handle or p.id) if p else "Unknown participant"
    def _avatar_for(pid: str | None, size: int = 36) -> str:
        p = _participant(pid)
        if not p: return system_avatar_svg(size, unknown=True)
        return human_avatar_svg(avatar_id_for(p, preferences), size) if p.type == "human" else role_avatar_svg(p.role, p.model, size)
    def _message_html(m: Any, *, viewer_id: str | None = None, previous: Any = None) -> str:
        grouped = previous is not None and previous.created_by == m.created_by and abs((m.created_at-previous.created_at).total_seconds()) <= 300
        p = _participant(m.created_by)
        avatar = "<span class='avatar-placeholder'></span>" if grouped else _avatar_for(m.created_by)
        head = "" if grouped else f"<div class='message-head'><strong>{_e(_participant_label(p))}</strong><span class='message-meta'>{_e(getattr(p,'role','system'))} · {_format_time(m.created_at)}</span></div>"
        target = f"<span class='message-target'>to {_e(m.to)}</span>" if m.to else ""
        return f"<article class='message{' grouped' if grouped else ''}'>{avatar}<div>{head}<div class='message-text'>{_e(m.text)}{target}</div></div></article>"
    def _message_group_html(messages: Iterable[Any], *, viewer_id: str | None = None) -> str:
        ordered = sorted(messages, key=lambda m:m.created_at)
        if not ordered: return _empty_state("thread","No messages yet","This thread is ready for its first update.")
        out=[]; previous=None
        for m in ordered: out.append(_message_html(m,viewer_id=viewer_id,previous=previous)); previous=m
        return "<div class='conversation'>"+"".join(out)+"</div>"
    def _feed_line(e: Any) -> str:
        d=e.data
        if e.kind=="message_sent": return f"{d.get('from')} → {d.get('to') or 'thread'}: {d.get('text','')}"
        if e.kind=="status_changed": return f"moved {d.get('from','?')} → {d.get('to',d.get('note','?'))}"
        if e.kind=="gate_opened": return f"needs your answer: {d.get('gate')} gate ({d.get('note') or 'no note'})"
        if e.kind=="gate_answered": return f"{d.get('gate')} gate answered by {d.get('by')}: {d.get('answer','')}"
        if e.kind in ("shell_dead","shell_stalled"):
            verb = "closed" if d.get("clean") else ("stalled" if str(e.kind).endswith("stalled") else "died")
            return f"{d.get('participant')}'s shell {verb} — {d.get('reason') or 'no reason recorded'}"
        if e.kind=="assigned": return f"assigned to {d.get('assignee')}"
        return str({k:v for k,v in d.items() if k!="mentions"})[:200]
    def _event_html(e: Any) -> str: return f"<div class='system-event'>{system_avatar_svg(24)}<div>{_e(_feed_line(e)[:220])} {_ticket_chip(e.subject_id)}<span class='event-time'>{_format_time(e.created_at,True)}</span></div></div>"
    def _gate_card_html(ticket_id: str, gate: Any, opened_by: Any, note: Any, hidden: str="", actionable: bool=False) -> str:
        value=getattr(gate,"value",gate); form=""
        if actionable:
            options="".join(f"<option>{_e(x.value)}</option>" for x in Gate if x.value==value)
            form=f"<form method='post' action='/ui/me/gate'>{hidden}<input type='hidden' name='ticket_id' value='{_e(ticket_id)}'><select name='gate'>{options}</select><input name='answer' placeholder='Your ruling…' required><button>Submit ruling</button></form>"
        return f"<article class='gate-card'><h3>{_icon('gate')} {_e(str(value).replace('_',' ').title())}</h3><p>{_ticket_chip(ticket_id)} · opened by {_e(opened_by or 'board')}</p><p>{_e(note or 'No note provided.')}</p>{form}</article>"
    def _criterion_html(c: Any) -> str:
        verdict=getattr(c.verdict,"value",c.verdict); symbol="✓" if verdict=="pass" else "!" if verdict=="fail" else "·"
        evidence=f" · <a href='/ui/doc/{quote(c.evidence_ref,safe='')}'>Evidence</a>" if c.evidence_ref else ""
        return f"<article class='criterion {_e(verdict)}'><div class='criterion-head'><span>{symbol}</span>{_badge(verdict)}<span class='object-id'>{_e(c.id)}</span></div><p>{_e(c.text)}</p><div class='criterion-meta'>{_e(c.check)} · responsible: {_e(c.checked_by)}{evidence}</div></article>"
    def _node_html(n: dict[str,Any]) -> str:
        markers="".join(f"<span class='marker'>Gate: {_e(g)}</span>" for g in n["gates"])
        if n["blocked_by"]: markers+=f"<span class='marker'>Blocked by {_e(', '.join(n['blocked_by']))}</span>"
        assignee=f"<span class='node-assignee'>{_avatar_for(n.get('assignee'),24)}</span>" if n.get("assignee") else ""
        children="".join(_node_html(k) for k in n["children"])
        return f"<li class='ticket-node'><a class='ticket-card' href='/ui/ticket/{quote(n['id'],safe='')}'><div class='ticket-card-top'>{_icon('ticket')}<span class='object-id'>{_e(n['id'])}</span>{_badge(n['status'])}<span class='secondary'>{_e(n['criteria'])} criteria</span>{markers}{assignee}</div><div class='ticket-card-title'>{_e(n['title'])}</div></a>{f'<ul>{children}</ul>' if children else ''}</li>"

    @r.get("/ui/me",response_class=HTMLResponse)
    def me(as_: str=Query(default="owner",alias="as"),token: str|None=Query(default=None),err: str|None=Query(default=None),
           sent: str|None=Query(default=None)):
        p=_me(as_,token); hidden=_hidden_identity_fields(p,token); qs=_qs(p,token); ctx=board.context(p)
        def asker_note(pid: str) -> str:
            asker=_participant(pid)
            if asker and asker.type=="human": return "A person will see your answer on their page."
            sessions=sorted(board.store.query("session",{"participant_id":pid}),key=lambda s:s.created_at); state=sessions[-1].state.value if sessions else None
            return f"Its shell is {state}; your answer wakes it." if state in ("alive","parked") else "Its shell has closed; your answer stays with the project for the next shell."
        ask_rows=[]
        for m in ctx["asks_for_me"]:
            asker=_participant(m["created_by"]); created=m.get("created_at"); when=_format_time(created) if isinstance(created,datetime) else ""
            ask_rows.append(f"<article class='question-unit'>{_avatar_for(m['created_by'])}<div><div class='message-head'><strong>{_e(_participant_label(asker))}</strong><span class='message-meta'>{_e(getattr(asker,'role','system'))} · {when}</span></div><div class='question-bubble'><div class='message-text'>{_e(m['text'])}</div>{_ticket_chip(m['ticket_id'])}</div><div class='delivery-note'>{_e(asker_note(m['created_by']))}</div><form class='reply-form' method='post' action='/ui/me/message'>{hidden}<input type='hidden' name='ticket_id' value='{_e(m['ticket_id'])}'><input type='hidden' name='to' value='{_e(m['created_by'])}'><input type='hidden' name='kind' value='answer'><input type='hidden' name='reply_to' value='{_e(m['id'])}'><input name='text' placeholder='Write an answer…' required><button>Send</button></form></div></article>")
        asks="".join(ask_rows) or _empty_state("inbox","Inbox clear","Nothing is waiting for your answer.")
        gate_rows=[]
        if p.role==Role.owner:
            for t in board.store.query("ticket",{"kind":TicketKind.epic},limit=200):
                if t.status in _TERMINAL or not board._owner_scope(p,t.id): continue
                for sub in (t,*board._descendants(t.id)):
                    for ev in board.open_gates(sub.id): gate_rows.append((sub.id,ev.data.get("gate"),ev))
        gates="".join(_gate_card_html(t,g,e.data.get("by"),e.data.get("note"),hidden,True) for t,g,e in gate_rows) or _empty_state("gate","No open gates","No rulings need your attention.")
        # docs awaiting the human's sign-off: criteria checked_by=owner, pending, with evidence —
        # the deliverable renders HERE (markdown) and the verdict button IS the HITL gate
        signoff_rows=[]
        if p.role==Role.owner:
            from .schemas import Verdict as _V
            for c in board.store.query("criterion",{"verdict":_V.pending},limit=300):
                if c.checked_by!="owner": continue
                tk=board.store.get("ticket",c.ticket_id)
                if tk is None or tk.status in _TERMINAL or not c.evidence_ref: continue
                if not board._owner_scope(p,tk.id): continue
                doc=board.store.get("doc",c.evidence_ref)
                doc_view=(f"<details open><summary>{_e(getattr(doc,'title','evidence'))} "
                          f"<span class='muted'>{_e(getattr(doc,'doc_type',''))} v{getattr(doc,'version','?')}</span></summary>"
                          f"<div class='doc-md'>{_md(getattr(doc,'body_md',''))}</div></details>") if doc else \
                         f"<p class='muted'>evidence {_e(c.evidence_ref)} unreadable</p>"
                signoff_rows.append(
                    f"<article class='signoff-card'><div class='who'>sign-off wanted on "
                    f"<a href='/ui/ticket/{quote(c.ticket_id,safe='')}'>{_e(c.ticket_id)}</a> · "
                    f"<span class='object-id'>{_e(c.id)}</span></div><p>{_e(c.text)}</p>{doc_view}"
                    f"<form class='signoff-actions' method='post' action='/ui/me/verdict'>{hidden}"
                    f"<input type='hidden' name='criterion_id' value='{_e(c.id)}'>"
                    f"<input type='hidden' name='ticket_id' value='{_e(c.ticket_id)}'>"
                    f"<input name='note' placeholder='optional note to the author…'>"
                    f"<button name='verdict' value='pass' title='approve — the ticket can close'>Approve</button>"
                    f"<button name='verdict' value='fail' class='btn-fail' title='send back — add a note saying what is missing'>Needs work</button>"
                    f"</form></article>")
        signoffs="".join(signoff_rows)
        # message kinds with human labels + tooltips; the wire value stays the enum
        _KIND_LABELS={"note":("Note","FYI on the thread — no reply expected"),
                      "question":("Question","expects an answer; recipients see it in 'waiting on you'"),
                      "answer":("Answer","replies to a question"),
                      "steer":("Steer","redirect work already in progress"),
                      "status":("Status update","progress note, no action needed"),
                      "finding":("Finding","a problem or discovery worth attention"),
                      "deviation":("Deviation","the plan can't be followed as written")}
        _kind_order=["note","question","steer","finding","status","answer","deviation"]
        kinds="".join(f"<option value='{k}' title='{_e(_KIND_LABELS[k][1])}'>{_e(_KIND_LABELS[k][0])}</option>"
                      for k in _kind_order if k in _KIND_LABELS)
        active_tickets=sorted((ticket for ticket in board.store.query("ticket",{}) if ticket.status not in _TERMINAL),
                              key=lambda ticket:ticket.created_at,reverse=True)
        ticket_options="".join(f"<option value='{_e(ticket.id)}' title='{_e(ticket.title[:160])}'>"
                               f"{_e(ticket.id)} — {_e(ticket.title[:56])}{'…' if len(ticket.title)>56 else ''}</option>"
                               for ticket in active_tickets)
        composer=(f"<div class='composer'><form class='composer-card' method='post' action='/ui/me/message'>{hidden}"
                  f"<h2 class='composer-title'>Post to a conversation</h2><div class='composer-top'>"
                  f"<label class='composer-field'><span>Conversation (ticket)</span>"
                  f"<select name='ticket_id' required title='every message joins ONE ticket&#39;s thread — that thread is the chat window'>"
                  f"<option value='' disabled selected>Pick the conversation…</option>{ticket_options}</select></label>"
                  f"<label class='composer-field'><span>Kind</span><select name='kind' title='what this message is — hover the options'>{kinds}</select></label></div>"
                  f"<input class='composer-main' name='text' placeholder='Write a message — type @handle anywhere to notify people (see People, right)' required "
                  f"title='type @handle anywhere in the text to notify that person; several @mentions allowed'>"
                  f"<input type='hidden' name='reply_to' value=''>"
                  f"<p class='composer-hint'>Your message lands on the chosen ticket's thread — that thread is the chat window (open it via the ticket link). "
                  f"Everyone you @mention gets it in their inbox. One ticket per message, any number of people.</p>"
                  f"<div class='composer-footer'><button title='post to the thread and notify every @mention'>Send message</button></div></form></div>")
        selected=avatar_id_for(p,preferences); identity=human_avatar_svg(selected,36) if p.type=="human" else _avatar_for(p.id)
        # CONVERSATIONS (Discord-style): one row per ticket that involves me — unanswered
        # asks first (unread dot), then my open epics/tickets by recent traffic. Each row
        # opens the ticket's chat room carrying my identity so I can reply there.
        ask_tids=[]
        for m in ctx["asks_for_me"]:
            if m["ticket_id"] not in ask_tids: ask_tids.append(m["ticket_id"])
        convo_ids=list(ask_tids)
        for blk in ctx.get("tickets") or []:
            tid=blk["ticket"]["id"]
            if blk["ticket"]["status"] not in ("done","partial","dropped") and tid not in convo_ids:
                convo_ids.append(tid)
        convo_rows=[]
        for tid in convo_ids[:14]:
            tk=board.store.get("ticket",tid)
            if tk is None: continue
            unread="<span class='unread-dot' title='waiting on you'></span>" if tid in ask_tids else ""
            last=board.thread(tid,limit=1)
            who=_avatar_for(last[-1].created_by,20) if last else _icon("thread",14)
            convo_rows.append(
                f"<a class='convo-row' href='/ui/ticket/{quote(tid,safe='')}?{qs}' "
                f"title='{_e(tk.title[:120])}'>{unread}{who}<span class='convo-name'>{_e(tid)}</span>"
                f"<span class='muted convo-snip'>{_e((last[-1].text if last else tk.title)[:34])}</span></a>")
        conversations="".join(convo_rows) or "<p class='muted' style='font-size:12px'>no open conversations</p>"
        sidebar=(f"<div class='identity'>{identity}<div class='identity-copy'><strong>{_e(p.handle)}</strong>"
                 f"<span>{_e(p.role)} · {_e(p.type)}</span></div></div>"
                 f"<div class='nav-stat'><span>Waiting on you</span><b>{len(ask_rows)}</b></div>"
                 f"<div class='nav-stat'><span>Open gates</span><b>{len(gate_rows)}</b></div>"
                 f"{_section_header('Conversations',len(convo_rows))}<div class='convo-list'>{conversations}</div>"
                 f"{avatar_picker_html(p,selected,hidden) if p.type=='human' else ''}")
        # People = humans (taggable, always) + LIVE agent seats (with their ticket + state).
        # Base-role registry stubs (@engineer, @reviewer…) are empty chairs: tagging them
        # reaches nobody, so they do not appear — you talk to agents on their TICKET thread.
        def _seat_state(pid: str) -> str | None:
            rows=sorted(board.store.query("session",{"participant_id":pid}),key=lambda s:s.created_at)
            return rows[-1].state.value if rows else None
        people_rows=[]
        for c in sorted(board.store.query("participant",{}),key=lambda c:(c.type!="human",c.handle or "")):
            if not c.handle or c.handle.startswith(("__","wt-")): continue
            if c.type=="human":
                people_rows.append(
                    f"<div class='people-row' title='type @{_e(c.handle)} in a message to notify them'>"
                    f"{_avatar_for(c.id,24)}<span class='mono'>@{_e(c.handle)}</span>"
                    f"<span class='muted'>person</span></div>")
                continue
            state=_seat_state(c.id)
            if state not in ("alive","parked"): continue  # a closed seat is not a recipient
            tid=c.id.split(".",1)[1] if "." in c.id else None
            people_rows.append(
                f"<div class='people-row' title='a running {_e(c.role)} seat — steer it on its ticket thread'>"
                f"{_avatar_for(c.id,24)}<span class='mono'>@{_e(c.handle)}</span>"
                f"{_ticket_chip(tid) if tid else ''}<span class='muted seat-up'>● up</span></div>")
        people="".join(people_rows) or "<p class='muted'>no one else is on right now — agents appear here while their shells run</p>"
        right=(f"{_section_header('Open gates',len(gate_rows))}{gates}"
               f"{_section_header('Who can I reach',len(people_rows))}<div class='people-list'>{people}</div>"
               f"<p class='muted' style='font-size:12px'>Agents without a running shell aren't listed: "
               f"post on their <b>ticket thread</b> instead — the next shell on that seat reads it first thing. "
               f"<a href='/ui/activity?{qs}'>Full activity →</a></p>")
        banner=f"<div class='alert' role='alert'>⚠ {_e(err)}</div>" if err else ""
        if sent:
            banner+=(f"<div class='alert alert-ok' role='status'>✓ Sent — it's on "
                     f"<a href='/ui/ticket/{quote(sent,safe='')}'>{_e(sent)}</a>'s thread (that page is the conversation); "
                     f"everyone you @mentioned has it in their inbox.</div>")
        signoff_block=f"{_section_header('Docs awaiting your sign-off',len(signoff_rows))}{signoffs}" if signoff_rows else ""
        body=f"{banner}<div class='identity'>{identity}<div class='identity-copy'><strong>{_e(p.handle)}</strong><span>{_e(p.role)} · {_e(p.type)} participant</span></div></div><p class='secondary'>Messages are pinned to the project. Active shells wake immediately; closed shells read them when they reopen.</p>{signoff_block}{_section_header('Waiting on you',len(ask_rows))}<div class='conversation'>{asks}</div>"
        return _page(f"{p.handle} · My inbox",body,refresh=30,active_nav="me",sidebar=sidebar,context=right,composer=composer,identity=identity)

    @r.post("/ui/me/message")
    def me_message(as_: str=Form(...),token: str=Form(default=""),ticket_id: str=Form(...),to: str=Form(default=""),kind: str=Form(default="note"),text: str=Form(...),reply_to: str=Form(default="")):
        p=_me(as_,token or None)
        try:
            m=board.message_send(p,ticket_id=ticket_id.strip(),to=to.strip() or None,kind=MessageKind(kind),text=text,reply_to=reply_to.strip() or None); delivery.after_message(board,p.id,m)
        except (BoardError,ValueError) as e: return RedirectResponse(f"/ui/me?{_qs(p,token or None)}&err={quote(str(e))}",status_code=303)
        return RedirectResponse(f"/ui/me?{_qs(p,token or None)}&sent={quote(m.ticket_id,safe='')}",status_code=303)

    @r.post("/ui/me/gate")
    def me_gate(as_: str=Form(...),token: str=Form(default=""),ticket_id: str=Form(...),gate: str=Form(...),answer: str=Form(...)):
        p=_me(as_,token or None)
        try: board.gate_answer(p,ticket_id.strip(),Gate(gate),answer); delivery.after_gate_answer(board,p.id,ticket_id.strip(),gate,answer)
        except (BoardError,ValueError) as e: return RedirectResponse(f"/ui/me?{_qs(p,token or None)}&err={quote(str(e))}",status_code=303)
        return RedirectResponse(f"/ui/me?{_qs(p,token or None)}",status_code=303)

    @r.get("/ui/activity",response_class=HTMLResponse)
    def activity_page(as_: str=Query(default="owner",alias="as"),token: str|None=Query(default=None)):
        p=_me(as_,token)
        feed=board.replay(p,0)[-120:]
        by_day: dict[str,list]= {}
        for _s,e in reversed(feed):
            by_day.setdefault(e.created_at.strftime("%A %d %b"),[]).append(e)
        sections="".join(
            f"{_section_header(day,len(evs))}"+ "".join(_event_html(e) for e in evs)
            for day,evs in by_day.items()) or _empty_state("thread","Quiet","Project activity will appear here.")
        body=f"<p class='secondary'>Everything relevant to you, newest first. Your inbox stays for things that need YOU; this page is the pulse.</p>{sections}"
        return _page("Activity",body,refresh=30,active_nav="activity")

    @r.post("/ui/me/verdict")
    def me_verdict(as_: str=Form(...),token: str=Form(default=""),criterion_id: str=Form(...),
                   ticket_id: str=Form(default=""),verdict: str=Form(...),note: str=Form(default="")):
        p=_me(as_,token or None)
        try:
            from .schemas import Verdict as _V
            board.criterion_update(p,criterion_id.strip(),verdict=_V(verdict))
            if note.strip() and ticket_id.strip():
                tk=board.store.get("ticket",ticket_id.strip())
                m=board.message_send(p,ticket_id=ticket_id.strip(),to=getattr(tk,"assignee",None),
                                     kind=MessageKind.answer if verdict=="pass" else MessageKind.finding,
                                     text=f"[sign-off {verdict}] {note.strip()}")
                delivery.after_message(board,p.id,m)
        except (BoardError,ValueError) as e:
            return RedirectResponse(f"/ui/me?{_qs(p,token or None)}&err={quote(str(e))}",status_code=303)
        return RedirectResponse(f"/ui/me?{_qs(p,token or None)}",status_code=303)

    @r.post("/ui/me/avatar")
    def me_avatar(as_: str=Form(...),token: str=Form(default=""),avatar: str=Form(...)):
        p=_me(as_,token or None)
        if p.type!="human" or avatar not in HUMAN_AVATAR_IDS: return RedirectResponse(f"/ui/me?{_qs(p,token or None)}&err=Invalid%20avatar",status_code=303)
        try: save_avatar_preference(p.id,avatar); preferences[p.id]=avatar
        except (OSError,ValueError) as e: return RedirectResponse(f"/ui/me?{_qs(p,token or None)}&err={quote(str(e))}",status_code=303)
        return RedirectResponse(f"/ui/me?{_qs(p,token or None)}",status_code=303)

    @r.get("/ui",response_class=HTMLResponse)
    def epics():
        rows=[]; epic_rows=board.store.query("ticket",{"kind":TicketKind.epic},limit=200)
        for t in epic_rows:
            crits=board.criteria(t.id); passed=sum(c.verdict==Verdict.passed for c in crits); percent=int(100*passed/len(crits)) if crits else 0
            rows.append(f"<a class='epic-row' href='/ui/epic/{quote(t.id,safe='')}'><div class='epic-title'><span class='object-id'>{_e(t.id)}</span>{_e(t.title[:160])}</div><div class='epic-meta'>{passed} / {len(crits)} passed<div class='progress'><span style='width:{percent}%'></span></div></div><div class='epic-meta'>{_e(t.created_at.strftime('%Y-%m-%d'))}</div>{_badge(t.status)}<span class='chevron'>›</span></a>")
        body=f"<p class='reader-lead'>{len(epic_rows)} workspaces in progress</p><div class='epic-list'>{''.join(rows) if rows else _empty_state('epic','No epics yet','Created epics will appear here.')}</div>"
        return _page("Epics",body,active_nav="epics")

    @r.get("/ui/epic/{epic_id}",response_class=HTMLResponse)
    def epic(epic_id: str,as_: str=Query(default="owner",alias="as")):
        bd=board.board(epic_id); thread=board.thread(epic_id,limit=60); docs=board.store.query("doc",{"scope":epic_id},limit=100); gates=bd["open_gates"]
        counts=" ".join(f"{_badge(k)} {v}" for k,v in bd["counts"].items())
        # JIRA-style board: the epic's child tickets in status columns, drag-free but scannable
        _COLS=[("Backlog",("drafted","designed","signed_off","blocked")),("Ready",("ready",)),
               ("In progress",("in_progress",)),("In review",("in_review",)),("Done",("done","partial"))]
        kids=[t for t in board._descendants(epic_id) if t.status.value!="dropped"]
        col_html=""
        for label,states in _COLS:
            cards="".join(
                f"<a class='kanban-card' href='/ui/ticket/{quote(k.id,safe='')}?as={quote(as_)}' title='{_e(k.title[:140])}'>"
                f"<div class='kanban-top'><span class='object-id'>{_e(k.id)}</span>"
                f"{_avatar_for(k.assignee,20) if k.assignee else ''}</div>"
                f"<div class='kanban-title'>{_e(k.title[:70])}</div>"
                f"<div class='kanban-meta'>{_e(k.work_type)}"
                f"{''.join('<span class=marker>'+_e(g)+'</span>' for _t,g in gates if _t==k.id)}</div></a>"
                for k in kids if k.status.value in states)
            n=sum(1 for k in kids if k.status.value in states)
            col_html+=f"<div class='kanban-col'><div class='kanban-head'>{_e(label)} <span class='count'>{n}</span></div>{cards or '<div class=kanban-empty></div>'}</div>"
        body=(f"<p class='reader-lead'>{_e(bd['words'])}</p><div>{counts}</div>"
              f"{_section_header('Board',len(kids))}<div class='kanban'>{col_html}</div>"
              f"{_section_header('Epic thread',len(thread))}{_message_group_html(thread)}")
        tree=f"<ul class='ticket-tree'>{_node_html(bd['epic'])}</ul>"; gate_html="".join(_gate_card_html(t,g,"board","Open decision") for t,g in gates) or _empty_state("gate","No open gates","This epic has no pending decisions.")
        doc_html="".join(f"<div><a href='/ui/doc/{quote(d.id,safe='')}'>{_e(d.title)}</a> <span class='muted'>{_e(d.doc_type)} v{d.version}</span></div>" for d in docs) or _empty_state("doc","No documents","Linked epic documents will appear here.")
        right=f"{_section_header('Ticket tree')}{tree}{_section_header('Open gates',len(gates))}{gate_html}{_section_header('Documents',len(docs))}{doc_html}"
        return _page(f"Epic {epic_id}",body,refresh=10,active_nav="epics",context=right)

    @r.get("/ui/ticket/{ticket_id}",response_class=HTMLResponse)
    def ticket(ticket_id: str,as_: str|None=Query(default=None,alias="as"),token: str|None=Query(default=None)):
        t=board.ticket(ticket_id); crits=board.criteria(ticket_id); docs=board.linked_docs(ticket_id); thread=board.thread(ticket_id,limit=100); epic_id=board.epic_of(t).id; assignee=_participant(t.assignee)
        # the ticket page IS the chat room: arriving with an identity docks a composer
        composer=""; identity=""
        if as_:
            try:
                p=_me(as_,token); hidden=_hidden_identity_fields(p,token)
                selected=avatar_id_for(p,preferences); identity=human_avatar_svg(selected,36) if p.type=="human" else _avatar_for(p.id)
                composer=(f"<div class='composer'><form class='composer-card' method='post' action='/ui/ticket/{quote(ticket_id,safe='')}/say'>{hidden}"
                          f"<input type='hidden' name='ticket_id' value='{_e(ticket_id)}'>"
                          f"<input class='composer-main' name='text' placeholder='Message this conversation — @mention anyone' required "
                          f"title='posts to this thread; every @mention gets it in their inbox'>"
                          f"<div class='composer-footer'><span class='muted'>as @{_e(p.handle.lstrip('@'))}</span><button>Send</button></div></form></div>")
            except Exception:
                composer=""
        body=f"<p><a href='/ui/epic/{quote(epic_id,safe='')}'>← Epic {_e(epic_id)}</a></p><p class='reader-lead'>{_e(t.title)}</p><div class='identity'>{_avatar_for(t.assignee)}<div class='identity-copy'><strong>{_e(_participant_label(assignee))}</strong><span>{_e(t.kind)} / {_e(t.work_type)} · {_badge(t.status)}</span></div></div>{_section_header('Conversation',len(thread))}{_message_group_html(thread)}"
        criteria_html="".join(_criterion_html(c) for c in crits) or _empty_state("ticket","No criteria","Acceptance criteria have not been added."); docs_html="".join(f"<div><a href='/ui/doc/{quote(d.id,safe='')}'>{_e(d.title)}</a> <span class='muted'>v{d.version}</span></div>" for d in docs) or _empty_state("doc","No linked documents","Documents linked to this ticket will appear here.")
        design=f"<a href='/ui/doc/{quote(t.design_ref,safe='')}'>{_e(t.design_ref)}</a>" if t.design_ref else "Not linked"
        right=f"{_section_header('Acceptance criteria',len(crits))}{criteria_html}{_section_header('Linked documents',len(docs))}{docs_html}{_section_header('Ticket metadata')}<div class='meta-row'><span>Design</span><span>{design}</span></div><div class='meta-row'><span>Kind</span><span>{_e(t.kind)}</span></div><div class='meta-row'><span>Work type</span><span>{_e(t.work_type)}</span></div>"
        return _page(f"Ticket {ticket_id}",body,refresh=15,active_nav="epics",context=right,composer=composer,identity=identity)

    @r.post("/ui/ticket/{ticket_id}/say")
    def ticket_say(ticket_id: str,as_: str=Form(...),token: str=Form(default=""),text: str=Form(...)):
        p=_me(as_,token or None)
        try:
            m=board.message_send(p,ticket_id=ticket_id,to=None,kind=MessageKind.note,text=text)
            delivery.after_message(board,p.id,m)
        except (BoardError,ValueError) as e:
            return RedirectResponse(f"/ui/ticket/{quote(ticket_id,safe='')}?{_qs(p,token or None)}&err={quote(str(e))}",status_code=303)
        return RedirectResponse(f"/ui/ticket/{quote(ticket_id,safe='')}?{_qs(p,token or None)}",status_code=303)

    @r.get("/ui/doc/{doc_id}",response_class=HTMLResponse)
    def doc(doc_id: str,version: int|None=None):
        d=board.doc(doc_id,version); versions="".join(f"<a href='/ui/doc/{quote(doc_id,safe='')}?version={v}'>v{v}</a>" for v in board.store.doc_versions(doc_id))
        body=f"<p class='secondary'>{_e(d.doc_type)} · owner {_e(d.owner_role)} · scope {_e(d.scope)} · version {d.version}</p><div class='version-control'>{versions}</div><article class='document-reader doc-md'>{_md(d.body_md)}</article>"
        return _page(d.title,body,active_nav="epics")
    return r
