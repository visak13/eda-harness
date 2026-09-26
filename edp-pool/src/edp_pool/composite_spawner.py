"""CompositeSpawner — a mixed fleet: one primary backend (claude) plus one second backend (Pi or codex).

Moved out of the retired opencode launcher (S4 s-733de6e29f, design-e963c656f5 §4.11: opencode is dropped,
Pi and codex ship). Composites stack: main.py wraps claude with Pi, then that with codex. A launch goes to
the second backend when its role is in `roles` or `route_model(model)` says the requested model belongs
there; every lifecycle call goes to whichever backend knows the session id.
"""

from __future__ import annotations


class CompositeSpawner:
    def __init__(self, primary, second, roles: set[str] | None = None, route_model=None):
        self._primary = primary
        self._second = second
        self._roles = set(roles or ())
        # epic-6a8a6020fd (owner m-8642d551fc: "launch one small ticket which GPT drives"): a
        # per-spawn choice — `route_model(model) -> bool` says whether the REQUESTED model belongs
        # to the second backend (a `harness: pi` seat name such as "astra", or an openai/… id),
        # so spawn(role=engineer, model="astra") lands there without re-arming the pool by role.
        self._route_model = route_model

    def _owner(self, session_id):
        if self._second.knows(session_id):
            return self._second
        return self._primary

    def launch(self, session_id, role, handle, mode="headless",
               claude_session=None, resume_session=None, model=None,
               activation=None, parent=None, extra_env=None) -> None:
        # `parent` (F40#13 lineage) and `extra_env` (S20: the per-seat EDP8_TOKEN) are what the
        # service passes on EVERY spawn; a composite that dropped either raised TypeError on the
        # first live spawn (2026-09-17, s-174f83c926 demo). Forwarded verbatim to the backend.
        by_model = bool(self._route_model and model and self._route_model(model))
        backend = self._second if (role in self._roles or by_model) else self._primary
        backend.launch(session_id, role, handle, mode=mode,
                       claude_session=claude_session,
                       resume_session=resume_session, model=model,
                       activation=activation, parent=parent, extra_env=extra_env)

    def alive(self, session_id):
        return self._owner(session_id).alive(session_id)

    def kill(self, session_id):
        return self._owner(session_id).kill(session_id)

    def knows(self, session_id):
        return self._primary.knows(session_id) or self._second.knows(session_id)

    def pid(self, session_id):
        return self._owner(session_id).pid(session_id)

    def last_output_ts(self, session_id):
        return self._owner(session_id).last_output_ts(session_id)

    def close_viewport(self, session_id):
        if self._second.knows(session_id):
            self._second.close_viewport(session_id)

    def exit_code(self, session_id):
        code = getattr(self._second, "exit_code", lambda _s: None)(session_id)
        if code is not None:
            return code
        return getattr(self._primary, "exit_code", lambda _s: None)(session_id)

    def pins_session_id(self, session_id) -> bool:
        """Only a claude-backed seat is launched WITH the pool's minted session id."""
        return not self._second.knows(session_id)

    def session_token(self, session_id):
        """Resume-token seam: a second backend resumes by its own token; claude rows resume via their
        minted claude_session_id (service default path). After a pool restart neither backend knows the
        id, so the second backend's store is asked anyway — a hit means it was that backend's shell."""
        f = getattr(self._second, "session_token", None)
        if f is None:
            return None
        if self._second.knows(session_id) or not self._primary.knows(session_id):
            return f(session_id)
        return None

    def closed_session_token(self, session_id, handle):
        """resume_closed seam for backends that resume from a file, not an id (Pi)."""
        for b in (self._second, self._primary):
            f = getattr(b, "closed_session_token", None)
            tok = f(session_id, handle) if f else None
            if tok:
                return tok
        return None
