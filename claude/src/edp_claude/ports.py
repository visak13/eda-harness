"""IoC seam ABCs (LLD §3). Stub* now; Http* in components #3/#4 — swapping
is a DI choice in server.py, never a call-site change."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Literal

from edp_contracts import BrokerMessage, ToolError, ToolOk

ToolResult = ToolOk | ToolError


class PoolPort(ABC):
    @abstractmethod
    async def spawn_planner(
        self, recipe_id: str, step_id: str, model: str | None = None,
        resume_session: str | None = None,
    ) -> ToolResult:
        """W10a: optional per-spawn model tier (None=Opus).

        W11: the impl PINS a fresh claude session id on every planner spawn
        and returns it as `claude_session_id` — a planner the caller cannot
        name is a planner suspend/resume cannot fork. `resume_session` names
        an EXISTING base to fork FROM; paired with the fresh pin it drives
        `--resume <base> --session-id <fork> --fork-session`, branching the
        suspended planner rather than mutating it."""

    @abstractmethod
    async def spawn_worker(
        self, plan_id: str, action_id: str, model: str | None = None,
        role: str = "worker",
    ) -> ToolResult: ...
    # s17 FA3: optional per-action model tier (None=Opus).
    # s26 item 6b: `role` selects the shell's activator + tool surface
    # ("worker" | "reviewer"); the default keeps every existing dispatch
    # byte-identical.

    @abstractmethod
    async def close_when_idle(
        self, session_id: str, idle_secs: float, reason: str = "",
        park: bool = False,
    ) -> ToolResult: ...
    # s26 item 1: ARM a one-shot, per-session deferred reap. The session's
    # action has reached a TERMINAL status, so the shell has nothing left to do.
    # The pool waits for it to go idle and then reaps it — closing the leak
    # where an LLM ends its turn after reporting and never calls
    # `pool_close_self`. Idempotent + no-op if the shell closes itself first.
    #
    # DESIGN-v7 1.5.2 `park`: the same idle-gated trigger, but the terminal
    # act is a PARK (state="parked", lock + resume token kept) instead of a
    # release. This is the pool's designed SELF-park path: the shell arms it,
    # ends its turn, and the pool parks the quiesced shell — a self-park
    # cannot be synchronous, because the transcript must flush and the shell
    # must stop consuming before the inbox watermark is cut.

    # (spawn_goal_keeper / spawn_pattern_observer lived here — Phase 6
    # externality shells. DELETED with their roles, owner ruling 2026-08-04.)

    @abstractmethod
    async def spawn_curiosity(
        self, parent_id: str, curiosity_id: str, model: str | None = None
    ) -> ToolResult:
        """v2.2 (2026-05-22): the curiosity neuron — an externality shell
        that interrogates the user neuron at EACH decision point until
        the decision is 'clear'. Same consult-before-spawn pattern as
        critic: the neuron posts the {decision, context} to the
        curiosity inbox FIRST, then spawns; curiosity replies with
        questions (or clear) for the neuron to relay to the user. The
        neuron does not decide alone."""

    @abstractmethod
    async def spawn_acceptor(
        self, parent_id: str, acceptor_id: str, model: str | None = None
    ) -> ToolResult:
        """F31 (2026-08-18, owner ruling): the FINAL ACCEPTANCE shell — the
        advisor seat (Fable) verifying the whole delivery against the
        VERBATIM goal + named artifacts in ITS OWN shell, fixing what it
        safely can, and recording acceptance_verdict. Same
        consult-before-spawn pattern as curiosity: the neuron posts the
        acceptance brief to the acceptor inbox FIRST, then spawns."""

    @abstractmethod
    async def spawn_specialist(
        self, parent_id: str, specialist_id: str,
        claude_session: str | None = None,
        mode: str = "headless",
        resume_session: str | None = None,
        model: str | None = None,
    ) -> ToolResult:
        """Specialization vision phase 4 (2026-05-22): a SME shell that
        self-trains into a subject-matter expert. parent_id is the
        caller (agentic-plan); specialist_id is the spawned shell's
        broker inbox. Same consult-before-spawn pattern as critic — the
        caller posts the {subject, description, category} task FIRST,
        then spawns; the SME's Step 0 inbox-check reads it. `claude_session`
        (phase 5) PINS the claude session id (`--session-id`) so the
        trained base id is known up front and branchable. `mode`
        (v2.3): "monitor" spawns a VISIBLE console the user can converse
        with directly (interactive training); "headless" otherwise.
        `resume_session` (2026-05-24): resume an EXISTING trained base to
        UPDATE it (refine the recipe) rather than train fresh — the SME
        keeps prior expertise; claude_session is the refined snapshot."""

    @abstractmethod
    async def spawn_reviewer(
        self, parent_id: str, handle: str, session_id: str,
        model: str | None = None,
    ) -> ToolResult:
        """SPECIALIST-COMPILED-DOCS.md (2026-06-02): a FRESH domain-reviewer
        shell — NOT a fork of the trained base. It loads the specialist's
        COMPILED doc (`get_specialist_doc`) for its rubric and reviews from a
        clean context, so review is as cheap as a worker (no chat replay).
        `session_id` pins a fresh `--session-id` (no `--resume`)."""

    # (spawn_consult — the DESIGN-v6 W5 convened-consult spawn — was DELETED
    # in the 2026-08-12 dead-surface sweep with the consult shell role; its
    # only caller was the deregistered ConveneConsult tool.)

    @abstractmethod
    async def liveness(self, handle: str) -> dict:
        """W7: {"state": "alive"|"dead"|"unknown", "last_output_ts": float|None}.
        `state` is the pid/fingerprint liveness (unchanged semantics);
        `last_output_ts` is the epoch mtime of the shell's PTY-drain log
        (the busyness signal — a recently-grown log = alive-and-busy even
        inside a silent reasoning block), or None when unknown. Callers
        that only need liveness read `["state"]`."""
        ...

    async def sessions(self, recipe_id: str | None = None) -> list[dict]:
        """GET-backed list of all pool sessions (object-model `session` /
        `lock` readers). Each: session_id, role, handle, parent, state.
        W11: `recipe_id` narrows the listing to one recipe's shells (what
        suspend_recipe's manifest enumerates); None lists everything.
        Default returns [] so an implementation that doesn't expose it
        degrades gracefully; HttpPool + StubPool override it."""
        return []

    async def locks(self) -> list[dict]:
        """GET-backed list of held locks (object-model `lock` reader).
        Each: handle, session_id, liveness. Default derives from
        sessions() so an impl without GET /v1/locks degrades gracefully;
        HttpPool + StubPool override with the truthful endpoint."""
        return [
            {"handle": s["handle"], "session_id": s.get("session_id"),
             "liveness": "alive"}
            for s in await self.sessions()
            if s.get("state") == "active" and s.get("handle")
        ]

    @abstractmethod
    async def release(self, session_id: str, park: bool = False) -> ToolResult:
        """Release the session's lock + reap the shell. DESIGN-v7 1.5.2
        `park=True` turns the close into an IMMEDIATE park (the pool's
        POST /v1/release body flag → park_session): state="parked", lock and
        resume token KEPT, process killed after a transcript flush-wait.
        Prefer `close_when_idle(park=True)` when the PARKING SHELL IS THE
        CALLER — an immediate park kills it mid-turn and can truncate the
        very transcript the resume exists to reload."""

    @abstractmethod
    async def resume(self, handle: str) -> ToolResult:
        """DESIGN-v7 1.5.3: fork-resume the PARKED shell holding `handle`'s
        lock (POST /v1/resume/{handle}). The pool's parked→resuming CAS makes
        a double caller (resume watchdog + the neuron's pool_resume_planner
        backstop) a no-op, never a double-spawn. A failed fork-resume falls
        back pool-side to a fresh spawn on the same handle (cold reground)."""

    @abstractmethod
    async def reap(self, handle: str) -> ToolResult:
        """2026-05-25: force-kill the worker holding `handle`'s lock +
        release the lock. The deliberate, neuron-invoked escape for a
        worker JUDGED stuck/dead (replaces OS-kill). Not auto — reaping
        is a reasoned act."""


class BrokerPort(ABC):
    @abstractmethod
    async def send(self, msg: BrokerMessage) -> ToolResult: ...

    @abstractmethod
    async def poll(
        self, recipient: str, since_ts: datetime | None = None
    ) -> list[BrokerMessage]: ...

    @abstractmethod
    async def get_message(self, msg_id: str) -> BrokerMessage | None:
        """Look up a previously-sent message by id. The `reply()` tool
        uses this to find the original sender so the agent never has
        to know about addressing — they pass msg_id, the tool routes."""

    async def query(
        self,
        to: str | None = None,
        from_: str | None = None,
        kind: str | None = None,
        since: datetime | None = None,
    ) -> list[BrokerMessage]:
        """GET-only cross-inbox query (object-model `message` reader).
        Wide lens over broker traffic the caller did NOT receive. Default
        falls back to recipient-scoped poll when `to` is given (impl
        without GET /v1/messages degrades); HttpBroker + StubBroker
        override with the real cross-query."""
        if to is None:
            return []
        msgs = await self.poll(to, since_ts=since)
        return [
            m for m in msgs
            if (from_ is None or m.from_ == from_)
            and (kind is None or m.kind == kind)
        ]

    async def register_alias(
        self, alias: str, target: str, owner_session: str = "*"
    ) -> None:
        """Register an absolute (ownerless) identity alias `alias → target`
        on the broker (s12 item c). Mirrors the s16 colon→dash bridge the
        pool registers at planner spawn (edp-pool/service.py:356-371). Used
        by the neuron's reconcile tick to bridge its symbolic send-identity
        `"neuron"` to the recipe_id inbox it actually polls. Best-effort by
        contract: a broker that is down must NOT fail the caller's tick.
        Concrete no-op default (like `query`) so port impls/test-doubles
        that don't bridge stay valid; HttpBroker + StubBroker override."""
        return None


class MemoryPort(ABC):
    @abstractmethod
    async def recall(
        self,
        query: str,
        scope: str | None = None,
        *,
        recipe_id: str | None = None,
        domain: str | None = None,
    ) -> list[dict]:
        """Fan out over the caller's lineage scopes (global + recipe +
        domain, resolved by the tool layer) and merge; legacy fallback when
        no scoped trail exists yet (DESIGN-v6 W4)."""
        ...

    @abstractmethod
    async def remember(
        self,
        fact: dict,
        domain: str | None,
        *,
        scope: str = "recipe",
        recipe_id: str | None = None,
    ) -> ToolResult:
        """Append a fact to its lineage-scoped trail. The tool layer resolves
        (scope, recipe_id, domain) and enforces the global-neuron guard."""
        ...


class FsmPort(ABC):
    """Nuanced next_action path. Stub returns FSM_UNDECIDABLE until #5."""

    @abstractmethod
    async def decide(
        self, handle: str, snapshot: dict, events: list[dict]
    ) -> ToolResult: ...


class EmbedPort(ABC):
    """Text → vector for the neuron DB's discovery index (vision phase
    2). The ONLY model-backed seam in the helper layer, and it is OFF
    the control-flow path — it ranks specialists, it does not decide
    anything. StubEmbed (deterministic, offline) for tests; ollama
    nomic-embed-text in prod. `embed` may raise on backend failure; the
    caller degrades to NeuronStore.search_text (token overlap).

    `kind` distinguishes a stored specialist DESCRIPTION ("document")
    from a search QUERY ("query"). nomic-embed-text needs the
    `search_document:` / `search_query:` task prefixes for good
    asymmetric retrieval — without them ranking is noisy (verified live
    2026-05-22). StubEmbed ignores `kind`."""

    @abstractmethod
    async def embed(
        self, text: str, kind: Literal["document", "query"] = "document"
    ) -> list[float]: ...
