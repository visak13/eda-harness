"""edp8 autopilot — the coordinator's routine moves as code (owner ruling 2026-08-24).

Every board-keeping action that needs no judgment runs here, in the board process,
for free: spawn the right shell when a ticket needs one, respawn dead shells whose
tickets are still live, stand the fleet down when an epic closes. Judgment stays
with humans and the crafted seats; a coordinator SHELL is now optional (manual
override), never required.

Rules (deterministic, idempotent):
  epic drafted, no architect session          -> spawn architect.<epic>  (assign epic)
  knowledge ticket ready/in_progress, no sme  -> spawn sme.<ticket>      (assign)
  story ready, no doer session                -> spawn engineer.<story>  (assign)
      (work_type=review -> reviewer.<story> as the doer; criteria are qa-checked)
  ticket in_review with pending reviewer-checked criteria, no reviewer session
                                              -> spawn reviewer.<ticket> (no assign)
  pending qa-checked criteria on an in_review ticket, or an open acceptance gate
                                              -> spawn qa.<epic>         (no assign)
  session dead + its ticket not terminal      -> respawn same participant
  epic done/partial/dropped                   -> reap every session of that epic (parked too)

A participant is registered before its first spawn. One session per participant:
nothing is spawned while a session for that participant is active or parked.
Disable with EDP8_AUTOPILOT=0.
"""

from __future__ import annotations

import logging
import threading
import time

from .board import Board, BoardError
from .schemas import Gate, Participant, Role, TicketKind, TicketStatus, Verdict, WorkType

log = logging.getLogger("edp8.autopilot")

_TERMINAL = (TicketStatus.done, TicketStatus.partial, TicketStatus.dropped)


class Autopilot:
    def __init__(self, board: Board):
        self.board = board
        self._stop = threading.Event()
        self.actions: list[str] = []  # audit of what it did (also posted as thread notes)

    # ------------------------------------------------------------------ pool access
    def _sessions(self) -> dict[str, str]:
        """participant handle -> state for sessions that occupy a seat (active/parked/resuming)."""
        from . import pool_adapter

        got = pool_adapter.sessions()
        if not got.get("ok"):
            return {}
        rows = got["value"] if isinstance(got["value"], list) else got["value"].get("sessions", [])
        out: dict[str, str] = {}
        for s in rows:
            if s.get("state") in ("active", "alive", "parked", "resuming", "starting"):
                out[s.get("handle", "")] = s.get("state", "")
        return out

    def _spawn(self, role: Role, pid: str, ticket_id: str | None, assign: bool, why: str) -> None:
        from . import pool_adapter

        try:
            self.board.participant(pid)
        except BoardError:
            self.board.participant_create("agent", role, pid, id_=pid)
        if assign and ticket_id:
            actor = self._system_actor()
            try:
                self.board.ticket_update(actor, ticket_id, assignee=pid)
            except BoardError as e:
                log.warning("autopilot assign %s -> %s refused: %s", ticket_id, pid, e.message)
        out = pool_adapter.spawn(role.value, pid)
        note = f"autopilot: spawned {pid} ({why})" if out.get("ok") else \
            f"autopilot: spawn {pid} FAILED ({why}): {out.get('error')}"
        self.actions.append(note)
        log.info(note)
        if ticket_id:
            self._note(ticket_id, note)

    def _reap(self, handle: str, ticket_id: str | None, why: str) -> None:
        from . import pool_adapter

        out = pool_adapter.reap(handle)
        note = f"autopilot: reaped {handle} ({why})" if out.get("ok") else \
            f"autopilot: reap {handle} failed ({why})"
        self.actions.append(note)
        log.info(note)
        if ticket_id:
            self._note(ticket_id, note)

    def _system_actor(self) -> Participant:
        try:
            return self.board.participant("autopilot")
        except BoardError:
            return self.board.participant_create("agent", Role.coordinator, "autopilot", id_="autopilot")

    def _note(self, ticket_id: str, text: str) -> None:
        try:
            self.board.message_send(self._system_actor(), ticket_id=ticket_id, to=None, kind="note", text=text)
        except BoardError:
            log.warning("autopilot note on %s failed", ticket_id)

    # ------------------------------------------------------------------ one pass
    def tick(self) -> None:
        seats = self._sessions()
        epics = [t for t in self.board.store.query("ticket", {"kind": TicketKind.epic}) if t.status not in _TERMINAL]
        for epic in epics:
            # architect for a drafted/designed-in-progress epic
            arch = f"architect.{epic.id}"
            if epic.status in (TicketStatus.drafted,) and arch not in seats:
                self._spawn(Role.architect, arch, epic.id, assign=True, why=f"epic {epic.id} needs a design")
            tree = [epic, *self.board._descendants(epic.id)]
            qa_needed = bool(self.board.open_gates(epic.id, Gate.acceptance))
            for t in tree:
                crits = self.board.criteria(t.id)
                if t.kind == TicketKind.story and t.status == TicketStatus.ready:
                    role = Role.reviewer if t.work_type == WorkType.review else \
                        (Role.sme if t.work_type == WorkType.knowledge else Role.engineer)
                    pid = f"{role.value}.{t.id}"
                    if (t.assignee or pid) not in seats and pid not in seats:
                        self._spawn(role, pid, t.id, assign=True, why=f"story {t.id} is ready")
                if t.status == TicketStatus.in_review and crits:
                    if any(c.checked_by == "reviewer" and c.verdict == Verdict.pending for c in crits):
                        pid = f"reviewer.{t.id}"
                        if pid not in seats and t.assignee != pid:
                            self._spawn(Role.reviewer, pid, t.id, assign=False,
                                        why=f"{t.id} awaits reviewer verdicts")
                    if any(c.checked_by == "qa" and c.verdict == Verdict.pending for c in crits):
                        qa_needed = True
            if qa_needed:
                pid = f"qa.{epic.id}"
                if pid not in seats and epic.assignee != pid:
                    self._spawn(Role.qa, pid, epic.id, assign=False, why=f"epic {epic.id} awaits qa")
        # respawn dead seats whose tickets are live; stand down closed epics
        self._recover_and_teardown(seats)

    def _recover_and_teardown(self, seats: dict[str, str]) -> None:
        from . import pool_adapter

        got = pool_adapter.sessions()
        if not got.get("ok"):
            return
        rows = got["value"] if isinstance(got["value"], list) else got["value"].get("sessions", [])
        closed_epics = {t.id for t in self.board.store.query("ticket", {"kind": TicketKind.epic})
                        if t.status in _TERMINAL}
        for s in rows:
            handle, state = s.get("handle", ""), s.get("state", "")
            tid = handle.split(".", 1)[1] if "." in handle else None
            epic_of = None
            if tid:
                tk = self.board.store.get("ticket", tid)
                epic_of = self.board.epic_of(tk).id if tk is not None else None  # type: ignore[arg-type]
            if state in ("active", "alive", "parked") and epic_of in closed_epics:
                self._reap(handle, tid, f"epic {epic_of} is closed")
            elif state == "dead" and tid:
                tk = self.board.store.get("ticket", tid)
                if tk is not None and tk.status not in _TERMINAL and handle not in seats:
                    role = handle.split(".", 1)[0]
                    try:
                        self._spawn(Role(role), handle, tid, assign=False, why="its shell died mid-ticket")
                    except ValueError:
                        log.warning("dead session with unknown role handle: %s", handle)

    # ------------------------------------------------------------------ loop
    def run_forever(self, interval: float = 10.0) -> None:
        time.sleep(5)
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as e:  # keep the loop alive, loudly
                log.warning("autopilot tick failed: %s", e)
            self._stop.wait(interval)

    def stop(self) -> None:
        self._stop.set()


def start_autopilot_thread(board: Board) -> Autopilot | None:
    import os

    if os.environ.get("EDP8_AUTOPILOT", "1") in ("0", "false", "no"):
        return None
    if not (os.environ.get("EDP_POOL_URL") or os.environ.get("EDP8_POOL_WATCH")):
        return None
    ap = Autopilot(board)
    threading.Thread(target=ap.run_forever, name="edp8-autopilot", daemon=True).start()
    log.info("autopilot started")
    return ap
