"""Object model — the uniform CRUD surface over the domain object graph.

The recipe/plan/action/step/outcome objects are ONE connected graph (a
**recipe** owns **steps**; a step spawns a **plan**; a plan owns
**actions**; spawned shells are **sessions** holding **locks** and
talking via **messages**, all leaving a **worklog** trail). Five tools
wrap this graph:
- `describe_objects` — schema + which verbs each object actually supports
- `read_object` — one object by id
- `query_objects` — filtered list (some objects only; see each `ops`)
- `create_object` / `update_object` — mutate through the object's OWN
  encapsulated invariants (delegates to the intent tools; you never
  re-implement a rule).

NOT every object supports every verb — the `ops` field on each catalog
entry is the source of truth (e.g. a **plan** has no cross-list query and
no direct patch; you change it through its **actions**). Steps and
actions are EDITABLE and DELETABLE (P3 advisory FSM): risky-but-legal
mutations PROCEED and return `advisories` (warning + audit-trail record)
instead of refusing; only terminal-state mutation and deleting under a
LIVE shell stay hard-blocked. `describe_objects` surfaces `ops` so the
agent never guesses.

Every reader returns plain JSON-able dicts/lists. Pool/broker readers
are async (HTTP); store readers are sync but wrapped uniformly.
"""

from typing import Any

from .fsm.state_machines import STATE_MACHINES, render_state_machine

# ── schema catalog (the docs `describe_objects` surfaces) ──────────────────
# name → {cls, what, fields, ops (which verbs REALLY work), read, query,
#         note?}.  `ops` is honest about the edges — the model contradicted
#         reality before (plan/step advertised "full CRUD" but errored on
#         query/update). Keep ops in sync with read_object/query_objects/
#         create_object/update_object below.
_CATALOG: dict[str, dict] = {
    "recipe": {
        "cls": "mutate",
        "ops": "read, query, create, update",
        "what": "the goal map (owns comprehension, steps, outcomes).",
        "fields": "recipe_id, state, user_goal_verbatim, domain, "
                  "comprehension{expected_outcomes[], curiosity_cleared, "
                  "user_signoff}, context{decisions,assumptions,...}, "
                  "steps[], final_outcome",
        "read": "read_object('recipe', recipe_id=...)",
        "query": "query_objects('recipe', where={'state': 'executing'})",
    },
    "plan": {
        "cls": "mutate",
        "ops": "read, create",
        "note": "NO cross-plan query and NO direct patch — change a plan "
                "through its `action`s (update_object('action', ...)). To "
                "list a recipe's plans, query its `step`s.",
        "what": "one recipe step's plan (actions + dep graph).",
        "fields": "plan_id, recipe_id, recipe_step_id, state, shape, goal, "
                  "actions[], terminal_status, version",
        "read": "read_object('plan', plan_id=...)",
        "query": "(unsupported — query `action`s within the plan instead)",
        "rx": "no direct plan stream — a plan changes only through its "
              "`action`s. Observe its actions (`rx.worklog(plan_id)`) + its "
              "workers (`rx.pool(scope=plan_id)`).",
        "when": "`read_object` for a snapshot. `next_action(plan)` is the "
                "FLOW pacer (the next move); the object surface is the STATE "
                "truth (what's real now) — use both, don't fight the FSM's "
                "rough status.",
    },
    "action": {
        "cls": "mutate",
        "ops": "read, query, create, update, delete",
        "what": "one unit of work in a plan.",
        "fields": "action_id, status (pending|in_progress|verify|done|"
                  "failed|skipped), depends_on[], executor_mode, "
                  "acceptance{kind,expected,verify,actual}, spec_ids[], "
                  "specializations[] (MULTI-SPEC: an action may carry N "
                  "specs; legacy scalar spec_id/specialization still accepted "
                  "and folded to a 1-element list), concerns[], attempt, "
                  "result_ref",
        "read": "read_object('action', plan_id=..., action_id=...)",
        "query": "query_objects('action', plan_id=..., "
                 "where={'status': 'needs_review'})",
        "rx": "`rx.worklog(plan_id)` emits on every status transition — a "
              "`done` line means this action finished (worker-done-awaiting-"
              "review), so re-pull `next_action`. `rx.pool(scope="
              "plan_id)` emits when a worker's lock releases = a slot freed → "
              "a `pending` action can now dispatch.",
        "when": "SUBSCRIBE (rx.worklog) to be WOKEN on progress; read/query "
                "for a SNAPSHOT on wake or heartbeat. `in_progress` + worker "
                "not `dead` = working (don't force-fail; a reasoning block "
                "writes nothing for minutes). `pending` RIGHT AFTER you "
                "dispatched it = capacity-rolled-back (pool was full), NOT a "
                "phantom and NOT a stall — it re-dispatches when a slot "
                "frees; that is a legitimate `wait`.",
    },
    "step": {
        "cls": "mutate",
        "ops": "read, query, create, update, delete",
        "note": "EDITABLE + DELETABLE in any non-closed recipe state (P3 "
                "advisory FSM): update_object('step', ids={recipe_id, "
                "step_id}, patch={description|kind|depends_on|execution|"
                "status|...}) and delete_object('step', ids=..., reason=...) "
                "PROCEED with `advisories` (warning + audit-trail record) "
                "instead of refusing — edit the map in place rather than "
                "recording a replacement step. Hard blocks only: a closed "
                "recipe, deleting under a LIVE planner, deleting the last "
                "step past comprehending. The events trail (step_deleted / "
                "advisory_override records) keeps the honest history the old "
                "APPEND-ONLY rule used to provide.",
        "what": "one recipe step (drives a planner).",
        "fields": "step_id, status, execution, depends_on[], attempt",
        "read": "read_object('step', recipe_id=..., step_id=...)",
        "query": "query_objects('step', recipe_id=..., where={'status':...})",
    },
    "outcome": {
        "cls": "mutate",
        "ops": "read, query, create, update",
        "what": "an expected outcome the recipe must meet.",
        "fields": "id, description, verification, met, met_evidence",
        "read": "read_object('outcome', recipe_id=..., outcome_id=...)",
        "query": "query_objects('outcome', recipe_id=..., "
                 "where={'met': False})",
    },
    "north_star": {
        "cls": "inspect",
        "ops": "read",
        "note": "READ-ONLY here — it is CREATED/UPDATED only via "
                "record_context(kind='north_star_update') (neuron-only). "
                "`user_goal_verbatim` is IMMUTABLE; `active_constraints` is "
                "auto-derived from the recipe's active decision/ban "
                "constraints (never hand-written); `evolution_log` is "
                "append-only. Returns null until first materialized.",
        "what": "the per-recipe north star (immutable goal + current shape + "
                "auto-derived active constraints + append-only evolution log).",
        "fields": "recipe_id, user_goal_verbatim (immutable), current_shape, "
                  "active_constraints[] (auto-derived), evolution_log[], "
                  "created_at, updated_at",
        "read": "read_object('north_star', recipe_id=...)",
        "query": "(unsupported — read by recipe_id)",
    },
    "neuron": {
        "cls": "mutate",
        "ops": "read, query, create, update",
        "what": "a specialist/comprehension/orchestrator neuron.",
        "fields": "neuron_id, name, category, status, base_session_id, "
                  "spec_id, use_count, flag_count",
        "read": "read_object('neuron', neuron_id=...)",
        "query": "query_objects('neuron', where={'status':'stable', "
                 "'category':'domain'})",
    },
    "spec": {
        "cls": "mutate",
        "ops": "read, create, update",
        "note": "update appends an entry (no cross-spec query; read by "
                "spec_id).",
        "what": "a specialization recipe (SME standards/checklists).",
        "fields": "spec_id, neuron_id, name, subject, entries[], version",
        "read": "read_object('spec', spec_id=...)",
        "query": "(unsupported — read by spec_id)",
    },
    "session": {
        "cls": "inspect",
        "ops": "read, query",
        "note": "inspect-only — lifecycle is the spawn/reap action tools, "
                "not create/update_object.",
        "what": "a spawned shell (worker/planner/curiosity/...) in the pool.",
        "fields": "session_id, role, handle, parent, state; liveness "
                  "(alive|dead|unknown) via the pool",
        "read": "read_object('session', handle='<plan_id>:<action_id>')",
        "query": "query_objects('session', where={'role':'worker'}, "
                 "scope={'recipe_id':'<recipe>'})  # scope to YOUR shells",
        "rx": "`rx.pool(scope=<recipe_id|plan_id>)` emits on a real liveness "
              "CHANGE (a worker crashed or finished) — change-detected, so a "
              "wake means something actually happened, not idle noise. ALWAYS "
              "`scope=` your handle prefix or it floods you with every "
              "recipe's shells.",
        "when": "Liveness is the POOL's truth, not the FSM's. query for who's "
                "REALLY alive now; rx.pool to be WOKEN when that changes. "
                "`alive`→working (keep waiting); `dead`→reap, FSM "
                "re-dispatches; `unknown`→conservative, keep waiting (a spawn "
                "really happened — dispatch failures roll the action back to "
                "`pending`).",
    },
    "lock": {
        "cls": "inspect",
        "ops": "read, query",
        "what": "an action/step lock held by a session (pool GET /v1/locks).",
        "fields": "handle, session_id (the holder), liveness "
                  "(alive|dead|unknown — dead = phantom lock, reap it)",
        "read": "read_object('lock', handle=...)",
        "query": "query_objects('lock', scope={'recipe_id':'<recipe>'})",
        "rx": "the same `rx.pool(scope=...)` stream as `session` — a lock "
              "appearing/releasing IS the liveness signal. A lock RELEASE = a "
              "freed worker slot (dispatch the queued action).",
        "when": "query for what's held now; rx.pool to be woken on "
                "acquire/release. A `dead` lock is a phantom (holder exited "
                "without releasing) → reap it.",
    },
    "message": {
        "cls": "inspect",
        "ops": "read, query",
        "what": "an inter-shell broker message (broker GET /v1/messages "
                "cross-inbox query).",
        "fields": "msg_id, from, to, kind, body, ts",
        "read": "read_object('message', msg_id=...)",
        "query": "query_objects('message', where={'to':'<recipient>', "
                 "'from':'curiosity-..', 'kind':'question', "
                 "'since':'<iso-ts>'})  # all filters OPTIONAL; omit 'to' "
                 "to scan every inbox",
        "rx": "`rx.broker(me, kinds=[...])` PUSHES messages to you the "
              "instant they're sent — this is what makes you responsive "
              "instead of heartbeat-latent. `me`=your handle; filter `kinds` "
              "to what you act on (e.g. ['question','answer','steer']).",
        "when": "SUBSCRIBE FIRST, always — otherwise a reply/steer waits a "
                "full heartbeat tick. Bind `me` to `whoami().self_address` — "
                "NOT `$EDP_HANDLE` (a planner's inbox is its dash plan_id, "
                "NOT its colon handle; binding the handle = a dead inbox). On "
                "a wake, `reply(msg_id, body)`. query (omit `to`) to scan "
                "inboxes you don't own, for diagnosis.",
    },
    "worklog": {
        "cls": "inspect",
        "ops": "read, query",
        "what": "the append-only durable trail (plan worklog / recipe "
                "events). Written by tool side-effects; read-only here.",
        "fields": "ts, kind (plan_saved|action_status_changed|plan_closed|"
                  "message_sent|message_received|"
                  "action_reset|dispatch_failed|recipe_saved|"
                  "comprehension_signoff), "
                  "agent_role (planner|executor|worker|neuron), + "
                  "kind-specific fields",
        "read": "read_object('worklog', plan_id=..., tail=20)  OR "
                "recipe_id=... — optional filters kinds=['…'], "
                "since='<ISO ts>', action_id='…' apply BEFORE the tail "
                "cut (tail=20 + kinds = last 20 of that kind)",
        "query": "query_objects('worklog', scope={'plan_id':...}, "
                 "where={'kind':'action_reset','agent_role':'planner',"
                 "'since':'<ISO>','action_id':'a1'})",
        "rx": "`rx.worklog(plan_id)` (plan) / `rx.worklog(recipe_id=...)` "
              "(recipe events) TAILS new appends — follow-only (history is "
              "NOT replayed as wakes). Each emission is one entry; act on its "
              "`kind`. This is your PRIMARY progress wake.",
        "when": "SUBSCRIBE to be woken the instant a worker records progress "
                "(don't poll). `read_object('worklog', plan_id, tail=N)` to "
                "catch up after a gap / on the heartbeat. The worklog is the "
                "durable truth of what HAPPENED; an action's `status` is the "
                "current state.",
    },
    "memory": {
        "cls": "mutate",
        "ops": "read, query, create",
        "note": "APPEND-ONLY knowledge facts — no per-fact id, so NO "
                "update/delete (add a new fact instead). `query` is FUZZY "
                "substring recall (every query word must appear in the "
                "record). `create` runs the domain kg_filter gate and may "
                "REJECT a fact as not-durable — check the returned "
                "`stored`. Separate from the neuron DB's embedding search.",
        "what": "the durable fact memory (remember/recall over "
                ".memory/facts.jsonl).",
        "fields": "text, domain, + any fact keys you store (durable, "
                  "tags, ...); recall matches over the whole record",
        "read": "read_object('memory', domain='software_engineering')  "
                "# dump facts (omit domain for all)",
        "query": "query_objects('memory', where={'query':'<words>', "
                 "'domain':'<d>'})  # fuzzy recall",
    },
}


class ObjectError(Exception):
    """Bad object type / missing scope id / inspect-only mutation."""


def describe_objects(name: str | None = None) -> str:
    """Render the schema docs. name=None → the whole catalog index +
    how-to; name=<obj> → that object's schema + read/query examples."""
    if name and name in _CATALOG:
        e = _CATALOG[name]
        out = (
            f"# `{name}` ({e['cls']} object)\n\n{e['what']}\n\n"
            f"**Ops (what actually works):** {e['ops']}\n"
        )
        if e.get("note"):
            out += f"**Note:** {e['note']}\n"
        out += (
            f"\n**Fields:** {e['fields']}\n\n"
            f"**Read:** `{e['read']}`\n"
            f"**Query:** `{e['query']}`\n"
        )
        # The rx plane + when-to-use-which-plane for THIS object — the
        # situated knowledge that was trapped in the reactive-streams guide
        # (2026-06-01: objects shipped with schema/CRUD only, so the agent
        # never learned to subscribe and fell back to brute-force polling).
        if e.get("rx"):
            out += f"\n**React (rx):** {e['rx']}\n"
        if e.get("when"):
            out += f"**When to use which plane:** {e['when']}\n"
        # Fixed-state objects expose their state machine as data: the
        # legal transitions ARE the deterministic progression (the LLM
        # mutates correctly because the type says which moves are legal).
        if name in STATE_MACHINES:
            states, transitions = STATE_MACHINES[name]
            field = "status" if name == "action" else "state"
            out += (
                f"\n**State machine (`{field}` — legal transitions):**\n"
                f"{render_state_machine(states, transitions)}\n"
            )
        return out
    lines = [
        "# Object model — the connected domain graph (CRUD + rx)",
        "",
        "recipe → steps → (each step spawns a) plan → actions → (each "
        "action spawns a) worker session. Shells hold locks, talk via "
        "messages, and leave a worklog trail. You INSPECT/MUTATE this graph "
        "with CRUD, and REACT to changes in it with rx (see "
        "get_guide('reactive-streams')).",
        "",
        "**Three planes — compose them, don't pick one (they answer "
        "different questions):**",
        "- CRUD (`read`/`query_object`) = what is TRUE now — a snapshot.",
        "- rx (`observe` + Monitor) = what just CHANGED — a wake, no "
        "polling. Subscribe FIRST so a worker's `done` / a steer reaches "
        "you instantly, not on the next heartbeat tick.",
        "- `reconcile` then `next_action` = sync-the-record then "
        "decide-the-next-move — the heartbeat BACKSTOP (rarely what should "
        "wake you once a subscription is live).",
        "",
        "**VERIFY BEFORE YOU ASSERT (read-side discipline — s27 Item 8).** "
        "Before stating a LOAD-BEARING fact about this graph — a shell is "
        "dead/stuck, an inbox is dead, a step is done, a value is settled — "
        "READ the owning object (`read_object` / `query_objects` / "
        "`reconcile`); never assert it from assumption or stale memory. "
        "Targeted, NOT a poll: only the few load-bearing claims, where one "
        "cheap read is the ground truth (so it never burns tokens on every "
        "claim). The read-side twin of settled decisions reaching the worker "
        "(see `action.injected_context`).",
        "",
        "**\"Is my worker alive / queued / done / dead?\"** No single field "
        "says it — COMPOSE (this is the exact thing not to re-derive by "
        "hand every wait):",
        "- done/failed → the `action`'s `status` (+ its `acceptance_"
        "verified` worklog line). `rx.worklog` WAKES you on it.",
        "- alive-and-working → action `in_progress` + `session` "
        "`liveness=alive` (writes nothing for minutes during a reasoning "
        "block — that is NOT hung; never force-fail it).",
        "- dead → session `liveness=dead` → reap; the FSM re-dispatches.",
        "- queued-on-capacity → action back to `pending` right after you "
        "dispatched it (the pool was full; the spawn rolled back). NOT a "
        "phantom, NOT a stall — it dispatches when a slot frees, so a "
        "`wait` here is legitimate. `rx.pool(scope=you)` WAKES you on the "
        "lock-release that frees the slot.",
        "Use rx.pool (scoped) + rx.worklog to be WOKEN on these flips — "
        "don't re-poll inspect_worker on every heartbeat.",
        "",
        "- `read_object(type, **ids)` → one object (or null)",
        "- `query_objects(type, where={…}, **scope)` → filtered list",
        "- `create_object(type, fields={…})` / "
        "`update_object(type, ids={…}, patch={…})` → mutate via the "
        "object's own invariants",
        "- `describe_objects(name)` → that object's schema + `ops` (the "
        "verbs it REALLY supports — not every object takes every verb)",
        "",
        "MUTATE objects (state you change):",
    ]
    for n, e in _CATALOG.items():
        if e["cls"] == "mutate":
            lines.append(f"  - `{n}` [{e['ops']}] — {e['what']}")
    lines.append("")
    lines.append("INSPECT-ONLY objects (read/query only; lifecycle is the "
                 "spawn/reap/publish action tools):")
    for n, e in _CATALOG.items():
        if e["cls"] == "inspect":
            lines.append(f"  - `{n}` [{e['ops']}] — {e['what']}")
    lines.append("")
    lines.append("Vocabulary (system objects, first-class): " +
                 ", ".join(f"`{n}`" for n in _CATALOG))
    lines.append("Call describe_objects(name='<obj>') for fields, ops + "
                 "examples.")
    return "\n".join(lines)


# ── readers ────────────────────────────────────────────────────────────────

def _need(ids: dict, *keys) -> None:
    missing = [k for k in keys if not ids.get(k)]
    if missing:
        raise ObjectError(f"this object needs id(s): {missing}")


def _resolve_action_injected(d: dict, plan) -> dict:
    """s17 RP-A — resolve an action's by-id `injected_context_ids` pointers to
    full TEXT at READ time, against the plan's store-once `injected_context`
    by-id map, so a worker calling read_object('action') receives the SAME
    full-text grounding dict it did pre-RP-A (byte-identical), with NO
    per-action text duplication on disk.

    Shape produced (identical to the legacy stamp):
        {"load_bearing_decisions": [text…], "banned_options": [text…]}

    Back-compat: an OLD action (pre-RP-A) carries full-text `injected_context`
    and NO `injected_context_ids` — it passes straight through unchanged. The
    resolved `injected_context_ids` pointer is removed from the read view (it is
    an internal storage detail; the worker never needs the raw ids)."""
    from .tools._bounds import budget_report
    ids = d.pop("injected_context_ids", None)
    if not ids:
        # No pointer → legacy full-text injected_context (if any) passes
        # through — but self-labels when oversize (context-diet Phase 1a: a
        # pre-budget action can still carry a ~47k-token full-text stamp, and
        # the reader must at least be told it is holding one).
        legacy = d.get("injected_context")
        if legacy:
            report = budget_report(legacy)
            if report["oversize"]:
                d["injected_context_report"] = report
        return d
    pmap = getattr(plan, "injected_context", None) or {}
    resolved: dict = {}
    for bucket, idlist in ids.items():
        texts = [pmap[i] for i in idlist if i in pmap]
        if texts:
            resolved[bucket] = texts
    if resolved:
        d["injected_context"] = resolved
        report = budget_report(resolved)
        if report["oversize"]:
            d["injected_context_report"] = report
    return d


def _trim(text: Any, limit: int = 160) -> str:
    """First-line, length-capped projection for digest views."""
    s = str(text or "").strip().splitlines()
    first = s[0].strip() if s else ""
    return (first[:limit].rstrip() + "…") if len(first) > limit else first


def _full_hint(obj_type: str, ids_hint: str) -> str:
    return f"read_object(type='{obj_type}', ids={{{ids_hint}}}, detail='full')"


def _digest_recipe(d: dict) -> dict:
    """P1 digest projection: scalars + state + counts stay; the long texts
    (decision bodies, step descriptions, outcome descriptions) become
    trimmed rows. Self-labels as a digest so it is never mistaken for the
    whole object."""
    from .fsm.recipe_fsm import _decision_title
    from .tools._bounds import windowed
    ctxd = d.get("context") or {}
    out = {
        k: v for k, v in d.items()
        if k in ("recipe_id", "user_goal_distilled", "domain", "state",
                 "final_outcome", "version", "created_at", "updated_at")
    }
    comp = d.get("comprehension") or {}
    out["comprehension"] = {
        "curiosity_cleared": comp.get("curiosity_cleared"),
        "user_signoff": comp.get("user_signoff"),
        "baseline": comp.get("baseline"),
        "expected_outcomes": [
            {"id": o.get("id"), "met": o.get("met"),
             "description": _trim(o.get("description"))}
            for o in comp.get("expected_outcomes", [])
        ],
    }
    # a3: window the steps + decisions rows (<=WINDOW + cursor) so a recipe
    # with hundreds of either can't unbound the digest. The projections STAY
    # JSON lists (only capped) with a count/cursor sibling — full fidelity is
    # one detail='full' read away (the _full hint below).
    steps_rows = [
        {"step_id": s.get("step_id"), "status": s.get("status"),
         "kind": s.get("kind"), "description": _trim(s.get("description")),
         "depends_on": s.get("depends_on"), "plan_ref": s.get("plan_ref"),
         "attempt": s.get("attempt")}
        for s in d.get("steps", [])
    ]
    sw = windowed(steps_rows)
    out["steps"] = sw["items"]
    out["steps_count"] = sw["count"]
    out["steps_cursor"] = sw["cursor"]
    dec_rows = [
        {"id": x.get("id"), "title": _decision_title(x.get("text", "")),
         "load_bearing": x.get("load_bearing", False),
         "status": x.get("status", "active")}
        for x in ctxd.get("decisions", [])
    ]
    dw = windowed(dec_rows)
    out["context"] = {
        "decisions": dw["items"],
        "decisions_count": dw["count"],
        "decisions_cursor": dw["cursor"],
        "assumptions": len(ctxd.get("assumptions", [])),
        "rejected_options": len(ctxd.get("rejected_options", [])),
        "open_questions": len(ctxd.get("open_questions", [])),
    }
    out["_detail"] = "digest"
    out["_full"] = _full_hint("recipe", f"'recipe_id': '{d.get('recipe_id')}'")
    return out


def _digest_plan(d: dict) -> dict:
    """P1 digest projection: drops the injected_context map and per-action
    evidence blobs; actions become status rows."""
    out = {
        k: v for k, v in d.items()
        if k in ("plan_id", "recipe_id", "recipe_step_id", "domain",
                 "shape", "state", "terminal_status", "version")
    }
    out["goal"] = _trim(d.get("goal"), 240)
    out["actions"] = [
        {"action_id": a.get("action_id"), "status": a.get("status"),
         "description": _trim(a.get("description")),
         "depends_on": a.get("depends_on"),
         "spec_ids": a.get("spec_ids") or (
             [a["spec_id"]] if a.get("spec_id") else []),
         "attempt": a.get("attempt"),
         "has_actual": bool((a.get("acceptance") or {}).get("actual"))}
        for a in d.get("actions", [])
    ]
    out["_detail"] = "digest"
    out["_full"] = _full_hint("plan", f"'plan_id': '{d.get('plan_id')}'")
    return out


def _digest_action(d: dict) -> dict:
    """P1 digest projection of ONE action: keeps the working fields, drops
    the resolved grounding text and the evidence blob, leaves indicators so
    the reader knows what a full read adds."""
    out = dict(d)
    inj = out.pop("injected_context", None)
    out.pop("injected_context_ids", None)
    acc = out.get("acceptance")
    if isinstance(acc, dict):
        actual = acc.get("actual")
        acc = dict(acc)
        acc["actual"] = _trim(actual) if actual else None
        acc["actual_bytes"] = (
            len(str(actual).encode("utf-8")) if actual else 0)
        out["acceptance"] = acc
    out["has_injected_context"] = bool(inj)
    out["_detail"] = "digest"
    out["_full"] = _full_hint(
        "action",
        f"'plan_id': …, 'action_id': '{d.get('action_id')}'")
    return out


async def read_object(ctx, obj_type: str, detail: str = "full", **ids) -> Any:
    """Return one object as a JSON-able dict (or None).

    detail='full' (default) returns today's complete object, byte-identical
    to the pre-P1 behavior. detail='digest' returns a trimmed projection for
    recipe/plan/action (long texts become one-line rows + indicators); other
    types ignore it. Digests self-label with `_detail`/`_full`."""
    if obj_type not in _CATALOG:
        raise ObjectError(
            f"unknown object {obj_type!r}; known: {sorted(_CATALOG)}")
    digest = detail == "digest"

    if obj_type == "recipe":
        confirm_oversize = bool(ids.pop("confirm_oversize", False))
        _need(ids, "recipe_id")
        if not ctx.recipes.exists(ids["recipe_id"]):
            return None
        d = ctx.recipes.load(ids["recipe_id"]).model_dump(mode="json")
        if digest:
            return _digest_recipe(d)
        # Context-diet Phase 1d — HYDRATION INTERLOCK. Tiering shrinks disk
        # only: a full recipe hydrates every decision body, and the biggest
        # live recipe measures ~194k tokens of decision text alone — one
        # detail='full' read blows a whole context window, and the default
        # detail IS 'full'. Past 3x BUDGET (recipes legitimately exceed the
        # 9k digest budget) the full read degrades to the digest plus a loud
        # oversize note; confirm_oversize=true in `ids` is the explicit
        # override for a caller that truly needs the whole object.
        from .tools._bounds import BUDGET, budget_report
        report = budget_report(d, budget=BUDGET * 3)
        if report["oversize"] and not confirm_oversize:
            out = _digest_recipe(d)
            out["oversize"] = True
            out["approx_tokens_full"] = report["approx_tokens"]
            out["full_available_via"] = (
                "read_object(type='recipe', ids={'recipe_id': …, "
                "'confirm_oversize': true}, detail='full') — but prefer "
                "get_recipe_digest / search_context / windowed reads; the "
                f"full object is ~{report['approx_tokens']} tokens.")
            return out
        return d

    if obj_type == "north_star":
        _need(ids, "recipe_id")
        rid = ids["recipe_id"]
        if not ctx.north_star.exists(rid):
            return None
        from .store.north_star import derive_active_constraints
        d = ctx.north_star.load(rid).model_dump(mode="json")
        # active_constraints is an AUTO-DERIVED read-only view — never persisted
        # on the north star, always recomputed from the LIVE recipe so it can't
        # go stale or be hand-forged.
        active: list = []
        if ctx.recipes.exists(rid):
            active = [c.model_dump(mode="json")
                      for c in derive_active_constraints(ctx.recipes.load(rid))]
        d["active_constraints"] = active
        return d

    if obj_type == "plan":
        _need(ids, "plan_id")
        if not ctx.plans.exists(ids["plan_id"]):
            return None
        d = ctx.plans.load(ids["plan_id"]).model_dump(mode="json")
        return _digest_plan(d) if digest else d

    if obj_type == "action":
        _need(ids, "plan_id", "action_id")
        if not ctx.plans.exists(ids["plan_id"]):
            return None
        plan = ctx.plans.load(ids["plan_id"])
        for a in plan.actions:
            if a.action_id == ids["action_id"]:
                if digest:
                    return _digest_action(a.model_dump(mode="json"))
                # s17 RP-A: resolve the by-id injected_context pointer to full
                # text against the plan map so the worker view is byte-identical.
                d = _resolve_action_injected(a.model_dump(mode="json"), plan)
                # W2: stamp the recipe's STATELESS grounding epoch onto the
                # action-grounding delivery seam (this read fires on every
                # dispatch/worker read), so the current ground fingerprint
                # reaches the worker alongside its injected_context. Recomputed
                # from the live recipe — never stored (d13). Omitted when no
                # backing recipe is resolvable (packet shape stays stable).
                rid = getattr(plan, "recipe_id", None)
                if rid and ctx.recipes.exists(rid):
                    from .fsm.recipe_fsm import grounding_epoch
                    d["grounding_epoch"] = grounding_epoch(ctx.recipes.load(rid))
                return d
        return None

    if obj_type == "step":
        _need(ids, "recipe_id", "step_id")
        if not ctx.recipes.exists(ids["recipe_id"]):
            return None
        for s in ctx.recipes.load(ids["recipe_id"]).steps:
            if s.step_id == ids["step_id"]:
                return s.model_dump(mode="json")
        return None

    if obj_type == "outcome":
        _need(ids, "recipe_id", "outcome_id")
        if not ctx.recipes.exists(ids["recipe_id"]):
            return None
        for o in ctx.recipes.load(
                ids["recipe_id"]).comprehension.expected_outcomes:
            if o.id == ids["outcome_id"]:
                return o.model_dump(mode="json")
        return None

    if obj_type == "neuron":
        _need(ids, "neuron_id")
        rec = ctx.neurons.get(ids["neuron_id"])
        return rec.model_dump(mode="json") if rec else None

    if obj_type == "spec":
        _need(ids, "spec_id")
        if not ctx.specs.exists(ids["spec_id"]):
            return None
        return ctx.specs.load(ids["spec_id"]).model_dump(mode="json")

    if obj_type == "session":
        _need(ids, "handle")
        handle = ids["handle"]
        live = (await ctx.pool.liveness(handle))["state"]  # W7 dict → state
        sess = await _all_sessions(ctx)
        match = next((s for s in sess if s.get("handle") == handle), None)
        return ({**match, "liveness": live} if match
                else {"handle": handle, "liveness": live, "session": None})

    if obj_type == "lock":
        _need(ids, "handle")
        for lk in await _locks(ctx):
            if lk["handle"] == ids["handle"]:
                return lk
        return None

    if obj_type == "message":
        _need(ids, "msg_id")
        m = await ctx.broker.get_message(ids["msg_id"])
        return m.model_dump(mode="json", by_alias=True) if m else None

    if obj_type == "worklog":
        tail = int(ids.get("tail", 20))
        flt = {"kinds": ids.get("kinds"), "since": ids.get("since"),
               "action_id": ids.get("action_id")}
        if ids.get("plan_id"):
            return ctx.plans.read_worklog(ids["plan_id"], tail=tail, **flt)
        if ids.get("recipe_id"):
            return _recipe_events(ctx, ids["recipe_id"], tail=tail, **flt)
        raise ObjectError("worklog read needs plan_id= or recipe_id=")

    if obj_type == "memory":
        # read = dump facts (empty query → all via recall); optional
        # domain filter. No per-fact id, so this returns a LIST (like
        # worklog). For a targeted search use query_objects('memory').
        from .tools._bounds import WINDOW
        facts = await ctx.memory.recall(ids.get("query", ""))
        dom = ids.get("domain")
        facts = [f for f in facts if dom is None or f.get("domain") == dom]
        # s17 a7: a raw dump is a LIST that scales with the store, so #18
        # requires it bounded. query_objects('memory') is the count-first
        # windowed path; this inspect read stays a bare list but is capped to
        # `limit` (default WINDOW). Widen via ids={'limit': N} for the
        # full-fidelity-one-read escape.
        limit = int(ids.get("limit", WINDOW))
        return facts[:limit] if limit >= 0 else facts

    raise ObjectError(f"no reader for {obj_type!r}")


async def query_objects(ctx, obj_type: str, where: dict | None = None,
                        offset: int = 0, limit: int | None = None,
                        **scope) -> dict:
    """Return a count-first WINDOW over a filtered list of objects.

    a3: every list branch (recipe/action/step/outcome/message and the
    inspect-only session/lock/worklog/memory) is bounded BY CONSTRUCTION
    through the SINGLE shared ``windowed(seq, offset, limit)`` helper — it
    previously honored a bound (``tail``) only on the worklog branch, so an
    unscoped recipe/message query could dump every object and blow the token
    limit (the 2026-05-29 ~62 KB blowout). The return is now the count-first
    envelope ``{items, count, offset, cursor, elided}`` — ``items`` is the
    ``<=limit`` slice, ``count`` the FULL match total, ``cursor`` the next
    offset to page from (``None`` at the end). Full fidelity stays one call
    away: page with ``offset``/``limit`` (or read each item by id).

    ``limit`` defaults to ``WINDOW``; pass a larger ``limit`` to widen the
    page. Filtering/scoping semantics are unchanged — only the OUTPUT shape.
    """
    from .tools._bounds import WINDOW, windowed
    rows = await _query_raw(ctx, obj_type, where=where, **scope)
    return windowed(rows, offset, WINDOW if limit is None else limit)


async def _query_raw(ctx, obj_type: str, where: dict | None = None,
                     **scope) -> list:
    """Return the full filtered list of objects (pre-window). `where` filters
    by field equality (+ a few special keys: handle_prefix, since, tail).
    ``query_objects`` wraps this with the shared count-first window."""
    where = where or {}
    if obj_type not in _CATALOG:
        raise ObjectError(
            f"unknown object {obj_type!r}; known: {sorted(_CATALOG)}")

    def _match(d: dict) -> bool:
        for k, v in where.items():
            # action_id is handled by the worklog filter (field OR worker-
            # handle suffix), not plain field equality — skip it here so a
            # handle-suffix match isn't immediately re-dropped. For other
            # object types action_id stays exact via their own readers.
            skip = ("handle_prefix", "since", "tail")
            if obj_type == "worklog":
                skip = skip + ("action_id",)
            if k in skip:
                continue
            if d.get(k) != v:
                return False
        if "handle_prefix" in where:
            if not str(d.get("handle", "")).startswith(where["handle_prefix"]):
                return False
        return True

    def _in_scope(d: dict) -> bool:
        """Scope a handle-keyed object (session/lock) to a recipe/plan/step.
        Handles: planner = `<recipe_id>:<step_id>`; worker =
        `<plan_id>:<action_id>` where `plan_id` = `<recipe_id>-<step_id>`
        — so EVERY shell under a recipe starts with `<recipe_id>`. Without
        this, query_objects('session'/'lock', scope=…) returned every
        recipe's shells (the 2026-05-29 unscoped-query bug: dumped ~62 KB
        across 14 recipes and blew the token limit)."""
        handle = str(d.get("handle", ""))
        if "plan_id" in scope:
            pid = scope["plan_id"]
            return handle == pid or handle.startswith(pid + ":")
        if "recipe_id" in scope:
            rid = scope["recipe_id"]
            return (handle == rid or handle.startswith(rid + ":")
                    or handle.startswith(rid + "-"))
        if "step_id" in scope:
            sid = scope["step_id"]
            return (handle.endswith(":" + sid)        # planner recipe:step
                    or ("-" + sid + ":") in handle)    # worker plan:action
        return True

    if obj_type == "recipe":
        # LIST = DIGEST ROWS, never full dumps (v7 follow-up, 2026-07-12,
        # measured live): a single hydrated recipe is ~1MB, so the old
        # full-dump list made `query_objects(type="recipe")` a payload bomb —
        # the codex neuron's MCP client hard-cancelled the call, and even a
        # Claude shell would eat a 250k-token result for a discovery query.
        # The digest projection (the same one read_object serves by default)
        # carries everything discovery needs — id/state/goal/steps/decision
        # titles — and every row self-labels with the `_full` hint naming the
        # one-object full read. The windowing above bounded the COUNT of
        # objects; this bounds their SIZE.
        out = []
        for rid in ctx.recipes.list_ids():
            try:
                d = ctx.recipes.load(rid).model_dump(mode="json")
            except Exception:
                continue
            if _match(d):
                row = _digest_recipe(d)
                # discovery needs the goal; the digest keeps only the
                # distilled form, which older recipes may lack.
                row.setdefault(
                    "goal", _trim(d.get("user_goal_verbatim"), 240))
                out.append(row)
        return out

    if obj_type == "action":
        _need(scope, "plan_id")
        if not ctx.plans.exists(scope["plan_id"]):
            return []
        return [a.model_dump(mode="json")
                for a in ctx.plans.load(scope["plan_id"]).actions
                if _match(a.model_dump(mode="json"))]

    if obj_type == "step":
        _need(scope, "recipe_id")
        if not ctx.recipes.exists(scope["recipe_id"]):
            return []
        return [s.model_dump(mode="json")
                for s in ctx.recipes.load(scope["recipe_id"]).steps
                if _match(s.model_dump(mode="json"))]

    if obj_type == "outcome":
        _need(scope, "recipe_id")
        if not ctx.recipes.exists(scope["recipe_id"]):
            return []
        return [o.model_dump(mode="json")
                for o in ctx.recipes.load(
                    scope["recipe_id"]).comprehension.expected_outcomes
                if _match(o.model_dump(mode="json"))]

    if obj_type == "neuron":
        recs = ctx.neurons.list(status=where.get("status"),
                                category=where.get("category"))
        return [r.model_dump(mode="json") for r in recs]

    if obj_type == "session":
        return [s for s in await _all_sessions(ctx)
                if _in_scope(s) and _match(s)]

    if obj_type == "lock":
        return [lk for lk in await _locks(ctx)
                if _in_scope(lk) and _match(lk)]

    if obj_type == "message":
        # GET /v1/messages cross-inbox query — all filters optional now
        # (no `to` means scan every inbox). from/kind/since are pushed
        # server-side; anything else stays a client-side _match.
        since = where.get("since")
        if isinstance(since, str):
            from datetime import datetime
            since = datetime.fromisoformat(since)
        msgs = await ctx.broker.query(
            to=where.get("to"), from_=where.get("from"),
            kind=where.get("kind"), since=since)
        out = [m.model_dump(mode="json", by_alias=True) for m in msgs]
        residual = {k: v for k, v in where.items()
                    if k not in ("to", "from", "kind", "since")}
        return [m for m in out if all(m.get(k) == v
                                      for k, v in residual.items())]

    if obj_type == "worklog":
        tail = int(where.get("tail", 200))
        flt = {
            "kinds": [where["kind"]] if where.get("kind") else None,
            "since": where.get("since"),
            "action_id": where.get("action_id"),
        }
        if scope.get("plan_id"):
            rows = ctx.plans.read_worklog(scope["plan_id"], tail=tail, **flt)
        elif scope.get("recipe_id"):
            rows = _recipe_events(ctx, scope["recipe_id"], tail=tail, **flt)
        else:
            raise ObjectError("worklog query needs plan_id= or recipe_id=")
        return [r for r in rows if _match(r)]

    if obj_type == "memory":
        # fuzzy recall on where['query']; remaining where keys (e.g.
        # domain) are exact post-filters.
        facts = await ctx.memory.recall(where.get("query", ""))
        residual = {k: v for k, v in where.items()
                    if k not in ("query", "tail")}
        return [f for f in facts
                if all(f.get(k) == v for k, v in residual.items())]

    raise ObjectError(f"query not supported for {obj_type!r}")


# ── pool/broker/worklog helpers ────────────────────────────────────────────

async def _all_sessions(ctx) -> list[dict]:
    """All pool sessions (GET /v1/sessions via the pool port). Returns []
    if the pool doesn't expose a session list."""
    fn = getattr(ctx.pool, "sessions", None)
    if fn is None:
        return []
    res = await fn()
    if isinstance(res, list):
        return res
    return list(getattr(res, "data", []) or [])


async def _locks(ctx) -> list[dict]:
    """Held locks via the pool's GET /v1/locks (truthful liveness). Falls
    back to deriving from active sessions if the pool lacks the endpoint."""
    fn = getattr(ctx.pool, "locks", None)
    if fn is not None:
        res = await fn()
        if isinstance(res, list):
            return res
    return [
        {"handle": s["handle"], "session_id": s.get("session_id"),
         "liveness": "alive"}
        for s in await _all_sessions(ctx)
        if s.get("state") == "active" and s.get("handle")
    ]


def _recipe_events(ctx, recipe_id: str, tail: int = 20,
                   kinds: list[str] | None = None,
                   since: str | None = None,
                   action_id: str | None = None) -> list[dict]:
    """Read the recipe's append-only events.jsonl trail. P1: optional
    kinds/since/action_id filters, applied BEFORE the tail cut."""
    from pathlib import Path

    from .store.atomic import filter_entries, read_jsonl
    p = Path(ctx.recipes.root) / recipe_id / "events.jsonl"
    rows = filter_entries(read_jsonl(p), kinds=kinds, since=since,
                          action_id=action_id)
    return rows[-tail:]


# ═══════════════════════════════════════════════════════════════════════════
# write-side CRUD (OBJECT-MODEL.md increment 2)
#
# update_object / create_object DELEGATE to the existing intent tools so
# the invariants (verify gate, comprehension gate, spec resolution, legal
# transitions, …) live in ONE place — the object layer is a uniform
# façade, not a second copy of the rules. Inspect-only objects refuse
# writes (their lifecycle is the purpose-built action tools).
# ═══════════════════════════════════════════════════════════════════════════

async def _run_intent(ctx, tool_cls_name: str, **kwargs) -> dict:
    """Invoke an intent tool by class name; normalize its envelope."""
    from edp_contracts import ToolError, ToolOk

    from . import tools as _t
    cls = getattr(_t._tools, tool_cls_name)
    res = await cls(ctx)._run(cls.InputModel(**kwargs))
    if isinstance(res, ToolOk):
        d = (res.data.model_dump(mode="json")
             if hasattr(res.data, "model_dump") else dict(res.data))
        d.setdefault("ok", True)
        return d
    if isinstance(res, ToolError):
        return {"ok": False, "error": res.message, "code": res.code}
    return {"ok": True}


async def create_object(ctx, obj_type: str, fields: dict | None = None) -> dict:
    """Create a domain object. Delegates to the intent tool that owns the
    object's creation invariants. Refused for inspect-only objects."""
    fields = fields or {}
    if obj_type not in _CATALOG:
        raise ObjectError(
            f"unknown object {obj_type!r}; known: {sorted(_CATALOG)}")
    if _CATALOG[obj_type]["cls"] != "mutate":
        raise ObjectError(
            f"`{obj_type}` is inspect-only — cannot create. Its lifecycle "
            "is the action tools (spawn/publish), not create_object.")
    if obj_type == "recipe":
        return await _run_intent(ctx, "StartRecipe", **fields)
    if obj_type == "plan":
        return await _run_intent(ctx, "CreatePlan", **fields)
    if obj_type == "action":
        return await _run_intent(ctx, "AddAction", **fields)
    if obj_type == "step":
        return await _run_intent(ctx, "AddStep", **fields)
    if obj_type == "outcome":
        return await _run_intent(ctx, "RecordOutcome", **fields)
    if obj_type == "neuron":
        return await _run_intent(ctx, "CreateSpecialization", **fields)
    if obj_type == "spec":
        # a spec is created with its neuron (create_specialization);
        # entries are appended via add_spec_entry.
        return await _run_intent(ctx, "AddSpecEntry", **fields)
    if obj_type == "memory":
        # create = remember(fact, domain). `domain` is pulled from
        # fields; the rest IS the fact. The kg_filter gate may reject it
        # (returned `stored: false`) — that's a valid outcome, not an
        # error.
        f = dict(fields)
        domain = f.pop("domain", "generic")
        return await _run_intent(ctx, "Remember", fact=f, domain=domain)
    raise ObjectError(f"create not supported for {obj_type!r}")


async def update_object(ctx, obj_type: str, ids: dict | None = None,
                        patch: dict | None = None) -> dict:
    """Patch a domain object through its encapsulated validation.
    Refused for inspect-only objects."""
    ids = ids or {}
    patch = patch or {}
    if obj_type not in _CATALOG:
        raise ObjectError(
            f"unknown object {obj_type!r}; known: {sorted(_CATALOG)}")
    if _CATALOG[obj_type]["cls"] != "mutate":
        raise ObjectError(
            f"`{obj_type}` is inspect-only — cannot update. Use the action "
            "tools (reap a session, etc.), not update_object.")
    if not patch:
        raise ObjectError("update_object needs a non-empty `patch`")

    if obj_type == "action":
        _need(ids, "plan_id", "action_id")
        # status change → record_action_status (d30 pure write: records
        # status + evidence, runs no gate; a `done` lands as done directly).
        if "status" in patch:
            return await _run_intent(
                ctx, "RecordActionStatus",
                plan_id=ids["plan_id"], action_id=ids["action_id"],
                status=patch["status"], evidence=patch.get("evidence"))
        # correctable verify / description (friction #4): a targeted edit
        # of a single action field, allowed even while dispatching — it's
        # a CORRECTION, the gate still actually checks afterward.
        return await _update_action_fields(ctx, ids["plan_id"],
                                           ids["action_id"], patch)

    if obj_type == "step":
        # P3: steps are editable (advisory-guarded) — see _update_step_fields.
        _need(ids, "recipe_id", "step_id")
        return await _update_step_fields(ctx, ids["recipe_id"],
                                         ids["step_id"], patch)

    if obj_type == "outcome":
        _need(ids, "recipe_id", "outcome_id")
        if "met" in patch:
            return await _run_intent(
                ctx, "MarkOutcomeMet", recipe_id=ids["recipe_id"],
                outcome_id=ids["outcome_id"],
                evidence=patch.get("evidence", ""))
        raise ObjectError("outcome update supports {met, evidence}")

    if obj_type == "recipe":
        _need(ids, "recipe_id")
        if "final_outcome" in patch:
            return await _run_intent(
                ctx, "CloseRecipe", recipe_id=ids["recipe_id"],
                final_outcome=patch["final_outcome"])
        if patch.get("user_signoff"):
            return await _run_intent(
                ctx, "RecordComprehensionSignoff",
                recipe_id=ids["recipe_id"],
                user_quote=patch.get("signoff_quote", patch.get("user_quote",
                                                                "")))
        raise ObjectError(
            "recipe update supports {final_outcome} (close) or "
            "{user_signoff, signoff_quote} (comprehension sign-off)")

    if obj_type == "neuron":
        _need(ids, "neuron_id")
        if "status" in patch:
            return await _run_intent(
                ctx, "NeuronSetStatus", neuron_id=ids["neuron_id"],
                status=patch["status"])
        if "base_session_id" in patch:
            return await _run_intent(
                ctx, "NeuronSetBaseSession", neuron_id=ids["neuron_id"],
                session_id=patch["base_session_id"])
        raise ObjectError("neuron update supports {status} or "
                          "{base_session_id}")

    if obj_type == "spec":
        _need(ids, "spec_id")
        return await _run_intent(
            ctx, "AddSpecEntry", spec_id=ids["spec_id"], **patch)

    if obj_type == "memory":
        raise ObjectError(
            "memory is append-only — facts have no id to patch. To change "
            "what's remembered, create_object('memory', fields={...}) a new "
            "fact; recall surfaces it. (No update/delete by design.)")

    raise ObjectError(f"update not supported for {obj_type!r}")


async def _update_action_fields(ctx, plan_id: str, action_id: str,
                                patch: dict) -> dict:
    """Correctable single-action edit (friction #4): set acceptance.verify
    / description / depends_on directly. Allowed regardless of plan state
    — fixing a wrong verify must not require a full replan, and the gate
    still actually checks the deliverable afterward (no false-done).

    2026-06-03 (SPECIALIST-COMPILED-DOCS): also `spec_id` + `concerns` — the
    planner RESOLVES a specialization to its stable neuron and stamps the
    spec_id here at dispatch, so a FRESH worker loads that spec's compiled
    doc (no fork). pool_spawn_worker's Guard B then refuses if that spec has
    no compiled doc, so a bad stamp can't spawn a groundless worker.

    2026-06-03 (MULTI-SPEC): an action may carry N specs, so the canonical
    plural fields `spec_ids`/`specializations` are stampable here too. The
    legacy singular `spec_id`/`specialization` remain accepted and are folded
    into the one-element list (amendment A1 — no parallel scalar is stored on
    the model). The planner stamps ALL relevant resolved specs in one call:
    update_object('action', ids=…, patch={'spec_ids': ['<a>', '<b>']}).

    2026-06-07 (s17 FA3 model-tiering): also `model` — the planner stamps an
    optional per-action model tier at dispatch for a genuinely NARROW worker
    (Sonnet 4.6, MEASURED-safe; see schemas.plan.Action.model). Omitted/None →
    the worker launches on the host default tier (Opus): behaviour unchanged.
    Only the worker dispatch path reads it; planner/reviewer/specialist/
    advisory/heartbeat shells never carry an override (they stay Opus)."""
    allowed = {"verify", "description", "depends_on", "concerns",
               "spec_ids", "specializations", "spec_id", "specialization",
               "model", "acceptance_kind", "acceptance_expected",
               "executor_mode"}
    bad = set(patch) - allowed
    if bad:
        raise ObjectError(
            f"action field-update allows {sorted(allowed)}; got extra "
            f"{sorted(bad)}. (status changes go through patch={{'status':…}}.)")
    if not ctx.plans.exists(plan_id):
        return {"ok": False, "error": f"no plan {plan_id!r}"}
    p = ctx.plans.load(plan_id)
    target = next((a for a in p.actions if a.action_id == action_id), None)
    if target is None:
        return {"ok": False, "error":
                f"no action {action_id!r} in {plan_id!r}"}
    if "verify" in patch:
        target.acceptance.verify = patch["verify"]
    if "description" in patch:
        target.description = patch["description"]
    if "depends_on" in patch:
        target.depends_on = patch["depends_on"]
    # spec stamps: plural is canonical; fold a legacy scalar into a list.
    if "spec_ids" in patch:
        target.spec_ids = list(patch["spec_ids"] or [])
    if "spec_id" in patch:
        target.spec_ids = [patch["spec_id"]] if patch["spec_id"] else []
    if "specializations" in patch:
        target.specializations = list(patch["specializations"] or [])
    if "specialization" in patch:
        target.specializations = (
            [patch["specialization"]] if patch["specialization"] else [])
    if "concerns" in patch:
        target.concerns = patch["concerns"]
    # P3: acceptance prose + executor mode are correctable too (the gate
    # still actually checks the deliverable at done-time).
    if "acceptance_kind" in patch:
        target.acceptance.kind = patch["acceptance_kind"]
    if "acceptance_expected" in patch:
        target.acceptance.expected = patch["acceptance_expected"]
    if "executor_mode" in patch:
        target.executor_mode = patch["executor_mode"]
    # s17 FA3 model-tiering: the planner stamps a per-action model tier here
    # at dispatch (it authored the action), ONLY for a genuinely NARROW worker
    # (Sonnet 4.6 MEASURED-safe — see Action.model). patch={'model': None}
    # clears it back to the host default (Opus). Other roles never carry one.
    if "model" in patch:
        target.model = patch["model"] or None
    ctx.plans.save(p)
    ctx.plans.append_worklog(plan_id, {
        "kind": "action_field_update", "agent_role": "planner",
        "action_id": action_id,
        "detail": f"updated {sorted(patch)} (correction, in {p.state})",
    })
    return {"ok": True, "action_id": action_id, "updated": sorted(patch)}


# ═══════════════════════════════════════════════════════════════════════════
# P3 (2026-06-10) — FULL CRUD + ADVISORY FSM
#
# The FSM stays the flow pacer, but mutation guards stop being flat refusals:
# a risky-but-legal edit PROCEEDS and returns `advisories` (warning + audit
# echo), with the same record appended to the owning trail (events.jsonl /
# worklog.jsonl) — so the honest history that append-only used to provide now
# lives in the audit trail, and the neuron can observe overrides on the rx
# plane. Only truly unsafe ops stay hard-blocked: mutating a TERMINAL object,
# and deleting an in_progress action/step whose shell is LIVE.
# ═══════════════════════════════════════════════════════════════════════════

def _actor() -> str:
    import os
    return os.environ.get("EDP_ROLE", "unknown")


def advise(ctx, *, op: str, target: str, warnings: list[tuple[str, str]],
           recipe_id: str | None = None,
           plan_id: str | None = None) -> list[dict]:
    """Build the advisory list for a proceeding-with-warnings mutation and
    append ONE audit record to the owning trail. `warnings` is a list of
    (code, message). Returns [] when there is nothing to warn about."""
    if not warnings:
        return []
    audit = {
        "kind": "advisory_override",
        "op": op,
        "target": target,
        "by": _actor(),
        "warnings": [c for c, _ in warnings],
        "detail": " | ".join(m for _, m in warnings),
    }
    try:
        if recipe_id and ctx.recipes.exists(recipe_id):
            ctx.recipes.append_worklog(recipe_id, audit)
        elif plan_id and ctx.plans.exists(plan_id):
            ctx.plans.append_worklog(plan_id, audit)
    except Exception:  # noqa: BLE001 — audit is best-effort, never blocks
        pass
    return [{"code": c, "severity": "warn", "message": m, "audit": audit}
            for c, m in warnings]


_STEP_PATCHABLE = {"description", "kind", "depends_on", "execution",
                   "rationale_for_next", "status", "outputs", "plan_ref"}
_STEP_STATUSES = {"pending", "in_progress", "done", "skipped"}


async def _update_step_fields(ctx, recipe_id: str, step_id: str,
                              patch: dict) -> dict:
    """P3: steps are EDITABLE (the old APPEND-ONLY rule is retired — the
    advisory audit trail now carries the honest history). Hard block only
    when the recipe is closed; an edit while the recipe is executing
    proceeds WITH an advisory (the planner driving this step was briefed
    against the previous text)."""
    bad = set(patch) - _STEP_PATCHABLE
    if bad:
        raise ObjectError(
            f"step field-update allows {sorted(_STEP_PATCHABLE)}; got "
            f"extra {sorted(bad)}.")
    if not ctx.recipes.exists(recipe_id):
        return {"ok": False, "error": f"no recipe {recipe_id!r}"}
    r = ctx.recipes.load(recipe_id)
    if str(r.state) == "closed" or getattr(r.state, "value", "") == "closed":
        return {"ok": False, "error":
                f"recipe {recipe_id!r} is closed (terminal) — its steps are "
                "immutable history now. Hard block, no override."}
    target = next((s for s in r.steps if s.step_id == step_id), None)
    if target is None:
        return {"ok": False, "error":
                f"no step {step_id!r} in {recipe_id!r}; known: "
                f"{[s.step_id for s in r.steps]}"}
    if "status" in patch and patch["status"] not in _STEP_STATUSES:
        raise ObjectError(
            f"step status must be one of {sorted(_STEP_STATUSES)}")

    warnings: list[tuple[str, str]] = []
    if target.status == "in_progress" and (
            set(patch) & {"description", "kind", "depends_on", "execution"}):
        warnings.append((
            "edit_in_flight",
            f"step {step_id} edited while it is in_progress — the planner "
            f"driving it (handle {recipe_id}:{step_id}) was briefed against "
            "the previous text; notify it (broker_send) or expect drift."))
    if patch.get("status") == "done" and target.plan_ref:
        warnings.append((
            "manual_done",
            f"step {step_id} marked done by hand while it has plan_ref="
            f"{target.plan_ref!r} — normally the plan's terminal state "
            "drives this; make sure that plan is genuinely finished."))

    for field, value in patch.items():
        setattr(target, field, value)
    ctx.recipes.save(r)
    advisories = advise(ctx, op="update_step", target=step_id,
                        warnings=warnings, recipe_id=recipe_id)
    out = {"ok": True, "step_id": step_id, "updated": sorted(patch)}
    if advisories:
        out["advisories"] = advisories
    return out


async def delete_object(ctx, obj_type: str, ids: dict | None = None,
                        reason: str = "") -> dict:
    """P3: delete a step or an action. PROCEEDS with advisories for risky
    cases; hard-blocks only the genuinely unsafe ones (terminal container,
    live shell still holding the work). Dependents' depends_on lists are
    auto-rewritten (with an advisory). The deletion + reason land in the
    audit trail, preserving the honest history."""
    ids = ids or {}
    if obj_type == "step":
        return await _delete_step(ctx, ids, reason)
    if obj_type == "action":
        return await _delete_action(ctx, ids, reason)
    raise ObjectError(
        f"delete supports `step` and `action` only (got {obj_type!r}). "
        "Other objects keep their purpose-built lifecycles.")


async def _delete_step(ctx, ids: dict, reason: str) -> dict:
    _need(ids, "recipe_id", "step_id")
    rid, sid = ids["recipe_id"], ids["step_id"]
    if not ctx.recipes.exists(rid):
        return {"ok": False, "error": f"no recipe {rid!r}"}
    r = ctx.recipes.load(rid)
    state = getattr(r.state, "value", str(r.state))
    if state == "closed":
        return {"ok": False, "error":
                f"recipe {rid!r} is closed (terminal) — steps are immutable "
                "history. Hard block, no override."}
    target = next((s for s in r.steps if s.step_id == sid), None)
    if target is None:
        return {"ok": False, "error":
                f"no step {sid!r} in {rid!r}; known: "
                f"{[s.step_id for s in r.steps]}"}
    if state in ("planning", "executing", "reviewing") and len(r.steps) == 1:
        return {"ok": False, "error":
                "cannot delete the recipe's LAST step past COMPREHENDING "
                "(the recipe invariant requires >=1 step) — mark it "
                "status='skipped' instead, or add the replacement step "
                "first."}
    if target.status == "in_progress":
        live = (await ctx.pool.liveness(f"{rid}:{sid}"))["state"]  # W7 dict
        if live == "alive":
            return {"ok": False, "error":
                    f"step {sid!r} is in_progress with a LIVE planner "
                    f"(handle {rid}:{sid}) — deleting under it is unsafe. "
                    "Steer or reap the planner first (pool_reap), then "
                    "delete."}

    warnings: list[tuple[str, str]] = []
    if target.plan_ref:
        warnings.append((
            "orphaned_plan",
            f"deleted step {sid} had plan_ref={target.plan_ref!r} — that "
            "plan stays on disk as an orphan (its history is preserved; "
            "nothing will dispatch it)."))
    dependents = [s.step_id for s in r.steps
                  if sid in (s.depends_on or []) and s.step_id != sid]
    if dependents:
        warnings.append((
            "dependents_rewritten",
            f"steps {dependents} depended on {sid}; their depends_on was "
            "rewritten to drop it — re-check their ordering still makes "
            "sense."))
    if target.status == "done":
        warnings.append((
            "deleting_done_step",
            f"step {sid} was DONE — its outputs {target.outputs} remain on "
            "disk but the recipe map no longer records the work."))

    r.steps = [s for s in r.steps if s.step_id != sid]
    for s in r.steps:
        if sid in (s.depends_on or []):
            s.depends_on = [d for d in s.depends_on if d != sid]
    ctx.recipes.save(r)
    ctx.recipes.append_worklog(rid, {
        "kind": "step_deleted", "step_id": sid, "by": _actor(),
        "reason": reason, "description_was": target.description[:200],
    })
    advisories = advise(ctx, op="delete_step", target=sid,
                        warnings=warnings, recipe_id=rid)
    out = {"ok": True, "deleted": sid, "reason": reason}
    if advisories:
        out["advisories"] = advisories
    return out


async def _delete_action(ctx, ids: dict, reason: str) -> dict:
    _need(ids, "plan_id", "action_id")
    pid, aid = ids["plan_id"], ids["action_id"]
    if not ctx.plans.exists(pid):
        return {"ok": False, "error": f"no plan {pid!r}"}
    p = ctx.plans.load(pid)
    state = getattr(p.state, "value", str(p.state))
    if state == "terminal":
        return {"ok": False, "error":
                f"plan {pid!r} is terminal — its actions are immutable "
                "history. Hard block, no override."}
    target = next((a for a in p.actions if a.action_id == aid), None)
    if target is None:
        return {"ok": False, "error":
                f"no action {aid!r} in {pid!r}; known: "
                f"{[a.action_id for a in p.actions]}"}

    warnings: list[tuple[str, str]] = []
    if target.status == "in_progress":
        live = (await ctx.pool.liveness(f"{pid}:{aid}"))["state"]  # W7 dict
        if live == "alive":
            return {"ok": False, "error":
                    f"action {aid!r} is in_progress with a LIVE worker "
                    f"(handle {pid}:{aid}) — deleting under it is unsafe. "
                    "Steer or reap the worker first (pool_reap), then "
                    "delete."}
        warnings.append((
            "worker_not_alive",
            f"action {aid} was in_progress with a {live!r} worker — if a "
            f"lock lingers, pool_reap('{pid}:{aid}') frees it."))
    if target.status == "done":
        ev = (target.acceptance.actual or "")[:200]
        warnings.append((
            "deleting_done_action",
            f"action {aid} was DONE with recorded evidence — the audit "
            f"trail keeps a digest ({ev!r}…), but the plan no longer "
            "records the work."))
    dependents = [a.action_id for a in p.actions
                  if aid in (a.depends_on or []) and a.action_id != aid]
    if dependents:
        warnings.append((
            "dependents_rewritten",
            f"actions {dependents} depended on {aid}; their depends_on was "
            "rewritten to drop it — re-check their ordering."))

    p.actions = [a for a in p.actions if a.action_id != aid]
    for a in p.actions:
        if aid in (a.depends_on or []):
            a.depends_on = [d for d in a.depends_on if d != aid]
    ctx.plans.save(p)
    ctx.plans.append_worklog(pid, {
        "kind": "action_deleted", "action_id": aid, "by": _actor(),
        "reason": reason, "description_was": target.description[:200],
        "status_was": target.status,
        "evidence_digest": (target.acceptance.actual or "")[:200] or None,
    })
    advisories = advise(ctx, op="delete_action", target=aid,
                        warnings=warnings, plan_id=pid)
    out = {"ok": True, "deleted": aid, "reason": reason}
    if advisories:
        out["advisories"] = advisories
    return out
