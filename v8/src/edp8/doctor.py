"""S19 read-only diagnostics for the Help seat (design-e963c656f5 §4.14(e).5).

Every function here only READS: the board's store, the pool's GET routes, the supervisor's status, the
log files and the pain log. Each one answers with facts plus `causes`, a list of named root causes. A
cause is {code, what, evidence, fix, guide}, and `guide` is the troubleshooting guide the card sends the
doctor to. The routes that serve these functions (api_doctor) admit the doctor role and admin humans only.

- `health`: services, the supervisor, versions, pool and broker reachability.
- `pool_view`: pool reachability, sessions, caps and usage, and saturated classes.
- `feed_lag`: per live seat, the oldest event addressed to it since its last board request.
- `dead_mail`: publishes the broker could not route (`publish_no_route` in its log).
- `why_stuck`: the gate, checker, blocker, assignee or cap holding a ticket, with the next edges'
  missing preconditions.
- `workflow_check`: the validator's problems, plus a static reachability walk.
- `pains`: the open pain records.
- `logs`: redacted log tails.
"""

from __future__ import annotations

import json
import time
from typing import Any

from . import pool_adapter, settings
from . import workflow as wflow
from .board import _TERMINAL, Board, BoardError, is_quick
from .schemas import Gate, Participant, Role, TicketKind, TicketStatus

LAG_WARN_S = 120      # an addressed event older than this, unread by a live seat, is lag
LAG_EVENTS = 2000     # newest events scanned for feed lag


def _cause(code: str, what: str, *, evidence: Any = None, fix: str = "", guide: str = "") -> dict[str, Any]:
    return {"code": code, "what": what, "evidence": evidence, "fix": fix,
            "guide": f"troubleshooting-{guide}" if guide else ""}


# ----------------------------------------------------------------------------- health
def health(board: Board) -> dict[str, Any]:
    from importlib import metadata

    from .admin import services as admin_services
    causes: list[dict[str, Any]] = []
    try:
        svc = admin_services.status()
    except Exception as e:  # noqa: BLE001 — a broken status read is itself a finding
        svc = {"services": [], "supervisor": {"running": False, "error": f"{type(e).__name__}: {e}"}}
    for r in svc.get("services", []):
        name, state = r.get("service"), r.get("health") or r.get("state")
        if name == "code-server" or state in ("up", None):
            continue
        causes.append(_cause("service_down", f"{name} is {state}", evidence=r,
                             fix=f"restart {name} (propose service.restart {{service: {name}}})"
                                 if name in ("board", "broker", "pool", "mcp", "bridge") else "",
                             guide="service-down"))
    if not svc.get("supervisor", {}).get("running"):
        causes.append(_cause("supervisor_down", "the supervisor is not running, so no service can be restarted "
                                                "from the board", evidence=svc.get("supervisor"),
                             fix="the person runs `heronry start` on the host", guide="service-down"))
    pool_up = pool_adapter.reachable()
    if not pool_up:
        causes.append(_cause("pool_unreachable", "the pool does not answer: no seat can spawn, resume or be "
                                                 "reaped, and seat states freeze", evidence={"pool": "unreachable"},
                             fix="propose service.restart {service: pool}", guide="service-down"))
    versions: dict[str, Any] = {}
    for name in ("edp8", "edp-pool", "edp-broker", "edp-contracts"):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return {"services": svc.get("services", []), "supervisor": svc.get("supervisor"), "pool_reachable": pool_up,
            "versions": versions, "causes": causes}


# ----------------------------------------------------------------------------- pool
def _limits() -> dict[str, Any] | None:
    out = pool_adapter._get("/v1/limits", {"usage": "1"})
    return out.get("value") if out.get("ok") else None


def saturation(lim: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Caps whose usage has reached them: total, live, each class and each per-role cap."""
    if not lim:
        return []
    use = lim.get("usage") or {}
    rows: list[tuple[str, Any, Any]] = [("total shells", lim.get("max_total_shells"), use.get("total")),
                                        ("live shells", lim.get("max_live_shells"), use.get("live"))]
    for cls, key in (("builder", "max_workers"), ("planner", "max_planners")):
        rows.append((f"{cls} class", lim.get(key), (use.get("classes") or {}).get(cls)))
    for role, cap in (lim.get("role_caps") or {}).items():
        rows.append((f"role {role}", cap, (use.get("roles") or {}).get(role)))
    return [{"cap": name, "limit": cap, "in_use": n} for name, cap, n in rows
            if isinstance(cap, int) and isinstance(n, int) and n >= cap]


def pool_view(board: Board) -> dict[str, Any]:
    causes: list[dict[str, Any]] = []
    if not pool_adapter.reachable():
        causes.append(_cause("pool_unreachable", "the pool does not answer", fix="propose service.restart "
                             "{service: pool}", guide="service-down"))
        return {"reachable": False, "sessions": [], "limits": None, "saturated": [], "causes": causes}
    sess = pool_adapter.sessions()
    rows = sess.get("value") if sess.get("ok") else None
    if isinstance(rows, dict):
        rows = rows.get("sessions") or rows.get("value") or []
    lim = _limits()
    sat = saturation(lim)
    for s in sat:
        causes.append(_cause("cap_saturated", f"{s['cap']} is full ({s['in_use']}/{s['limit']}): new spawns of "
                                              "that class wait", evidence=s,
                             fix="raise the cap (propose pool.set_limits) or let a seat finish",
                             guide="caps-saturated"))
    pending = [{"participant": pid, **{k: v for k, v in info.items() if k in ("role", "ticket")}}
               for pid, info in list(board._pending_pairings.items())]
    if pending and sat:
        causes.append(_cause("spawns_queued", f"{len(pending)} seat(s) wait to spawn while a cap is full",
                             evidence=pending, fix="raise the saturated cap", guide="caps-saturated"))
    return {"reachable": True, "sessions": rows or [], "limits": lim, "saturated": sat, "pending_spawns": pending,
            "causes": causes}


# ----------------------------------------------------------------------------- feed lag
def feed_lag(board: Board, last_seen: Any = None, *, now: float | None = None) -> dict[str, Any]:
    """For each seat with a live or parked session: the oldest event addressed to it that is newer than its
    last authenticated board request. A live seat that has not read an event for LAG_WARN_S has lag."""
    now = time.time() if now is None else now
    seats = []
    causes: list[dict[str, Any]] = []
    live: dict[str, Any] = {}
    for s in board.store.query("session", {}, limit=-1):
        cur = live.get(s.participant_id)
        if cur is None or s.created_at > cur.created_at:
            live[s.participant_id] = s
    events = board.store.query("event", {"kind": "message_sent"}, limit=LAG_EVENTS, newest_first=True)
    for pid, s in sorted(live.items()):
        state = getattr(s.state, "value", s.state)
        if state not in ("alive", "parked", "stalled"):
            continue
        seen = last_seen.get(pid) if last_seen is not None else None
        unread = [e for e in events if (e.data or {}).get("to") == pid
                  and (seen is None or e.created_at.timestamp() > seen)]
        oldest = min((e.created_at.timestamp() for e in unread), default=None)
        lag = round(now - oldest) if oldest is not None else 0
        out_at = s.last_output_at.timestamp() if s.last_output_at else None
        row = {"seat": pid, "state": state, "last_request_age_s": round(now - seen) if seen else None,
               "last_output_age_s": round(now - out_at) if out_at else None, "unread_addressed": len(unread),
               "lag_s": lag, "presence_stale": s.presence_stale_since is not None}
        seats.append(row)
        if lag >= LAG_WARN_S:
            causes.append(_cause("feed_lag", f"{pid} has {len(unread)} message(s) addressed to it, the oldest "
                                             f"{lag}s old, and has not called the board since",
                                 evidence=row, fix="the seat's feed monitor is probably dead: resume the seat "
                                                   "(the owner or its architect) so it re-arms", guide="feed-lag"))
        elif state == "stalled":
            causes.append(_cause("seat_stalled", f"{pid} is stalled (no output)", evidence=row,
                                 guide="feed-lag"))
    return {"seats": seats, "causes": causes}


# ----------------------------------------------------------------------------- broker dead mail
def dead_mail(board: Board, *, lines: int = 2000) -> dict[str, Any]:
    """Publishes the broker refused for an unroutable recipient (`publish_no_route` in its log)."""
    from .diagnostics import Scrubber, tail
    log = settings.logs_dir() / "broker.log"
    rows: list[dict[str, Any]] = []
    scrub = Scrubber()
    if log.is_file():
        for line in tail(log, lines).splitlines():
            if "publish_no_route" not in line:
                continue
            row: dict[str, Any] = {"line": scrub(line[:400])}
            try:
                d = json.loads(line)
                row.update({k: d.get(k) for k in ("ts", "to", "sender", "msg_kind") if k in d})
            except ValueError:
                pass
            rows.append(row)
    causes = []
    if rows:
        tos = sorted({str(r.get("to")) for r in rows if r.get("to")})
        causes.append(_cause("dead_mail", f"{len(rows)} broker message(s) had no recipient"
                                          + (f" (to {', '.join(tos[:5])})" if tos else ""),
                             evidence=rows[-5:], fix="the sender used a handle no seat reads on; resend to the "
                                                     "seat's participant id", guide="broker-dead-mail"))
    return {"log": "broker.log" if log.is_file() else None, "dead": rows[-50:], "count": len(rows), "causes": causes}


# ----------------------------------------------------------------------------- why stuck
def _humans(board: Board) -> list[Participant]:
    return [p for p in board.store.query("participant", {}, limit=-1)  # type: ignore[misc]
            if p.type == "human" and p.role != Role.expert]


def why_stuck(board: Board, ticket_id: str) -> dict[str, Any]:
    t = board.ticket(ticket_id)
    wf = board.workflow_of(t)
    causes: list[dict[str, Any]] = []
    facts: dict[str, Any] = {"id": t.id, "kind": t.kind.value, "status": t.status.value, "assignee": t.assignee,
                             "workflow": wf.ref}
    if t.status in _TERMINAL:
        return {"ticket": facts, "causes": [], "note": f"{t.id} is {t.status.value}: finished, not stuck"}

    # 1. open gates nobody can answer
    humans = _humans(board)
    gates = []
    for ev in board.open_gates(t.id):
        g = Gate(ev.data.get("gate"))
        refusals = {}
        for h in humans:
            r = board.gate_answer_refusal(h, t.id, g)
            refusals[h.id] = None if r is None else r.message
        answerable = [h for h, r in refusals.items() if r is None]
        row = {"gate": g.value, "opened_at": ev.created_at.isoformat(), "note": ev.data.get("note"),
               "answerable_by": answerable}
        gates.append(row)
        if not answerable:
            why = sorted({r for r in refusals.values() if r}) or ["no human participant exists on this board"]
            causes.append(_cause("gate_unanswerable", f"gate {g.value} on {t.id} is open but no human can answer it",
                                 evidence={"refusals": refusals or why},
                                 fix="fix the missing precondition the refusal names, or re-open the gate once it "
                                     "holds (propose gate.open); a workflow whose gate no human answers needs a "
                                     "fixed version for new epics", guide="stuck-ticket"))
    facts["open_gates"] = gates

    # 2. the doer
    if t.assignee:
        doer = board.store.get("participant", t.assignee)
        state = board.seat_state(t.assignee)
        facts["assignee_state"] = state
        if doer is not None and doer.type == "agent" and t.status in (TicketStatus.ready, TicketStatus.in_progress) \
                and state not in ("alive", "parked"):
            causes.append(_cause("assignee_seat_down", f"{t.assignee} does the work but its seat is "
                                                       f"{state or 'never spawned'}",
                                 evidence={"seat": t.assignee, "state": state},
                                 fix="the architect or owner resumes (or respawns) the seat", guide="stuck-ticket"))
    elif t.status in (TicketStatus.ready, TicketStatus.in_progress) and t.kind != TicketKind.epic:
        causes.append(_cause("no_assignee", f"{t.id} is {t.status.value} with nobody assigned",
                             fix="the architect assigns or spawns its engineer", guide="stuck-ticket"))

    # 3. the checker
    try:
        checker = board.checker_for(t)
    except LookupError as e:
        checker = None
        causes.append(_cause("no_checker", str(e), fix="publish a workflow version whose checker map covers this "
                                                        "kind, for new epics", guide="stuck-ticket"))
    facts["checker"] = checker
    if checker and t.kind == TicketKind.epic and board.open_gates(t.id, Gate.acceptance):
        seat = f"{checker}.{t.id}"
        state = board.seat_state(seat)
        facts["checker_seat"] = {"seat": seat, "state": state, "queued": seat in board._pending_pairings}
        if state not in ("alive", "parked"):
            info = board._pending_pairings.get(seat) or {}
            causes.append(_cause("checker_missing", f"the acceptance gate waits on {seat}, which is "
                                                    f"{state or 'not spawned'}"
                                 + (" (queued: spawn failed, retrying)" if info.get("spawn_failed_noted")
                                    else " (queued)" if info else ""),
                                 evidence={"seat": seat, "state": state, "pending": info or None},
                                 fix="check the pool and caps (doctor_pool); the board re-queues the checker "
                                     "every tick", guide="stuck-ticket"))
    if checker and board.store.get("participant", checker) is None and checker not in wf.spawnable \
            and not any(p.role.value == checker for p in humans):
        causes.append(_cause("checker_role_unfilled", f"{t.id}'s criteria are checked by {checker}, which no human "
                                                      "holds and no seat can spawn as", fix="a workflow version "
                                                      "whose checker is a spawnable role or a human", guide="stuck-ticket"))

    # 4. blockers
    blockers = [b for b in board.blockers(t.id) if b.status not in _TERMINAL]
    facts["open_blockers"] = [{"id": b.id, "status": b.status.value, "title": b.title} for b in blockers]
    if blockers and t.status in (TicketStatus.signed_off, TicketStatus.ready):
        causes.append(_cause("blocked_by", f"{t.id} waits on {len(blockers)} unfinished blocker(s)",
                             evidence=facts["open_blockers"], fix="finish or unlink the blockers", guide="stuck-ticket"))

    # 5. the next edges and what each is missing
    nxt = []
    for to in sorted(wf.legal(t.status.value)):
        edge = wf.edge(t.status.value, to)
        ctx = wflow.Ctx(board, None, t, wf, frm=t.status.value, to=to)
        r = wf.missing(edge.requires if edge else [], ctx, quick=is_quick(t), skip_roles=True)
        nxt.append({"to": to, "missing": None if r is None else {"code": r.code, "message": r.message,
                                                                 "hint": r.hint}})
    facts["next"] = nxt

    # 6. caps: a seat this ticket needs sits queued while a cap is full
    mine = {pid: info for pid, info in board._pending_pairings.items() if info.get("ticket") == t.id}
    if mine:
        sat = saturation(_limits()) if pool_adapter.reachable() else []
        facts["queued_seats"] = sorted(mine)
        if sat:
            causes.append(_cause("cap_saturated", f"{', '.join(sorted(mine))} wait(s) to spawn while "
                                                  + ", ".join(f"{s['cap']} {s['in_use']}/{s['limit']}" for s in sat)
                                                  + " is full", evidence={"saturated": sat, "queued": sorted(mine)},
                                 fix="raise the cap (propose pool.set_limits)", guide="caps-saturated"))
        elif not pool_adapter.reachable():
            causes.append(_cause("pool_unreachable", f"{', '.join(sorted(mine))} cannot spawn: the pool does not "
                                                     "answer", fix="propose service.restart {service: pool}",
                                 guide="service-down"))
    return {"ticket": facts, "causes": causes}


# ----------------------------------------------------------------------------- workflow
def workflow_check(board: Board, ref: str) -> dict[str, Any]:
    """Validate a workflow version and walk its status graph from the first status (the dry run's static
    half: which statuses no transition reaches, which non-terminal statuses have no exit)."""
    wf_id, ver = wflow.parse_ref(ref) if "@" in ref else (ref, None)
    try:
        d = board.workflows.get(wf_id, ver)
    except wflow.WorkflowError as e:
        raise BoardError("not_found", e.message, e.hint) from None
    problems = wflow.validate(d)
    edges: dict[str, set[str]] = {}
    for tr in d.transitions:
        edges.setdefault(tr.from_, set()).add(tr.to)
    start = d.statuses[0] if d.statuses else None
    seen, todo = set(), [start] if start else []
    while todo:
        s = todo.pop()
        if s in seen:
            continue
        seen.add(s)
        todo += sorted(edges.get(s, set()) - seen)
    walk = {"start": start, "unreachable": [s for s in d.statuses if s not in seen],
            "dead_ends": [s for s in d.statuses if s not in d.terminal and not edges.get(s)]}
    causes = [_cause("workflow_invalid", f"{p['code']}: {p['message']}", evidence=p,
                     fix=p.get("fix", ""), guide="update-failed") for p in problems if p["severity"] == "error"]
    return {"ref": d.ref, "published": d.published, "problems": problems, "walk": walk, "causes": causes}


# ----------------------------------------------------------------------------- pains, logs
def pains(limit: int = 30) -> dict[str, Any]:
    from .records import pain_file, read_pains
    p = pain_file()
    try:
        rows = read_pains(p)
    except OSError:
        rows = []
    return {"open": len(rows), "pains": [{k: r.get(k) for k in ("id", "area", "symptom", "severity", "ts", "status")}
                                         for r in rows[-limit:]]}


def logs(service: str, lines: int = 100) -> dict[str, Any]:
    """The redacted tail of one service log (<logs_dir>/<service>.log), or the list of logs there are."""
    from .diagnostics import Scrubber, log_files, tail
    files = {f.stem if f.parent == settings.logs_dir() else f"pool-logs/{f.stem}": f for f in log_files()}
    if service not in files:
        return {"service": service, "available": sorted(files), "text": None,
                "hint": "pass one of `available`"}
    lines = max(1, min(int(lines), 500))
    return {"service": service, "lines": lines, "text": Scrubber()(tail(files[service], lines))}


