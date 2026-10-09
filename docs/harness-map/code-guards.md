# Code guards inventory — v8 board (v8/src/edp8/) and pool (edp-pool/src/edp_pool/)

Repo: `<repo>`. Sections 1-4 are the read-only survey (grep/sed) taken before s-0b8d2e5393; section 5 records which refusal was kept and which became a hint.

## 1. Counts

### 1a. `raise BoardError(` sites per file (225 total)

| File | Sites | By code (first arg) |
|---|---|---|
| board.py | 130 | scope 50, invalid 26, schema 12, transition 11, not_found 11, validation 5, forbidden 5, state 2, precondition 2, conflict 2, version_mismatch 1, version_conflict 1, too_long 1, `r.code` 1 (workflow-precondition dispatcher, l.331) |
| topics.py | 27 | invalid 13, forbidden 6, not_found 4, `code` (variable) 3, transition 1 |
| service.py | 24 | scope 15, schema 3, invalid 3, not_found 2, range 1 |
| fixes.py | 10 | invalid 4, transition 3, scope 1, not_found 1, forbidden 1 |
| api_tools.py | 9 | forbidden 3, not_found 2, invalid 1, unavailable 1, internal 1, `e.code` 1 |
| library.py | 7 | invalid 6, not_found 1 |
| design_review.py | 7 | scope 3, schema 2, conflict 2 |
| doc_tools.py | 3 | edit_match, edit_overlap, section_match |
| quotes.py | 2 | schema 2 |
| help.py | 2 | forbidden 2 |
| context_delta.py | 2 | resync_required, range |
| secret_screen.py | 1 | secret |
| doctor.py | 1 | not_found |

Totals by literal code (all files): scope 69, invalid 53, not_found 22, schema 19, forbidden 17, transition 15, validation 5, conflict 4, state 2, precondition 2; 1 each: version_mismatch, version_conflict, unavailable, too_long, section_match, range, internal, edit_overlap, edit_match, secret, resync_required. A few sites pass the code as a variable.

### 1b. Other refusal forms (not in 1a)

- asks.py: 23 `raise _err(...)` (builds a BoardError) — validation 7, scope 6, transition 4, schema 3, not_found 2, invalid 1.
- workflow.py: 23 declared preconditions `_pre(...)`, raised as BoardError via `board._wf_check` (board.py:331) — role_in 5, criteria_min 3, design_ref 2; 1 each: actor_is_assignee, assignee_or_claim, blockers_released, checker_criteria, design_ready, design_signed, evidence_all, human_epic_owner, kind_in, not_terminal, signoff_lint, story_cap, verdicts_passed.
- bundles.py (MCP layer): 22 `{"ok": False, "error": ...}` envelopes — scope 5, schema 4, conflict 3, internal 2, not_found 2; 1 each: identity, invalid, invalid_name, precondition, transition, unavailable.
- `HTTPException(`: ~130 sites, mostly admin/HTTP plumbing (admin/teammates 18, service.py 17, admin/access 15, admin/integrations 13, admin/harnesses 12, ...; guest_scope.py 1).
- Pool (edp-pool service.py): `POOL_CAPACITY_EXCEEDED` x5, `POOL_ROLE_REFUSED` x1, `PanelRefused` x5, `"refused":` envelopes on approval/recipe/resume paths, and one silent effort clamp.

## 2. Categorized inventory

Counts are a manual classification of board.py's 130 sites; other modules noted per heading. Plain input validation (41) and not_found (11) in board.py are not counted as guards.

### (T) State transitions — board.py 7; + ~14 workflow preconditions; asks.py 4

- board.py:1049-1053 — "{t.kind} {t.id} is {t.status}; cannot go to {to}"
  ```python
  if to.value not in legal:
      raise BoardError("transition", f"{t.kind} {t.id} is {t.status}; cannot go to {to}", ...)
  edge = wf.edge(t.status.value, to.value)
  self._wf_check(wf, edge.requires, wflow.Ctx(self, actor, t, wf, frm=t.status.value, to=to.value))
  ```
- board.py:1507-1508 — "criteria cannot be added to a {t.status} ticket" (status list hard-coded)
  ```python
  if t.status in (TicketStatus.in_review, TicketStatus.done, TicketStatus.partial, TicketStatus.dropped):
      raise BoardError("transition", f"criteria cannot be added to a {t.status} ticket")
  ```
- workflow.py:645-647 — "in_review needs evidence_ref on every criterion"
  ```python
  _pre("evidence_all", "in_review needs evidence_ref on every criterion",
       "criteria without evidence: {missing} — /verify, doc_create(report), criterion_update",
       hook="evidence_before_review"),
  ```
- workflow.py:657 — "done needs every criterion verdict=pass"
  ```python
  _pre("verdicts_passed", "done needs every criterion verdict=pass", "not passed: {failing}"),
  ```
- Also: board.py:1045 "topic {t.id} is opened and closed by the owner, not moved"; 1000 "{t.id} is {t.status.value}; its type is part of the record"; 2428 "the acceptance gate waits on the asks ledger: {held}".

### (R) Role / authority / scope — board.py 37; + workflow role_in x5, actor_is_assignee, human_epic_owner; service.py ~12; asks.py 6

- board.py:537-538 — "{actor.role} may not create a {kind}"
  ```python
  if str(actor.role) not in creators:
      raise BoardError("scope", f"{actor.role} may not create a {kind}",
  ```
- board.py:935-936 — "{actor.role} may not assign tickets"
  ```python
  if not wf.allowed("assign", actor.role):
      raise BoardError("scope", f"{actor.role} may not assign tickets",
  ```
- board.py:1617-1618 — "this criterion is checked_by {c.checked_by}; you are {actor.role}"
  ```python
  if role != c.checked_by and actor.role != Role.owner:
      raise BoardError("scope", f"this criterion is checked_by {c.checked_by}; you are {actor.role}")
  ```
- board.py:3418-3420 — "{actor.role} may not record a binding decision or replace one" (m-1637080c9a)
  ```python
  if (binding is True or replaces_binding) and actor.role not in (Role.architect, Role.owner):
      raise BoardError("forbidden", f"{actor.role} may not record a binding decision or replace one",
  ```

### (E) Evidence / verdict — board.py 10; asks.py 1

- board.py:1625-1626 — "a verdict needs evidence_ref first"
  ```python
  if verdict != Verdict.pending and not c.evidence_ref:
      raise BoardError("transition", "a verdict needs evidence_ref first", "criterion_update(evidence_ref=...)")
  ```
- board.py:1627-1631 — "criterion {c.id} is check=look: a pass needs a screenshot, and {t.id} has no image uploaded on it since it went in_review" (t-cf891f387b, owner m-b1fe71dcca)
  ```python
  if verdict == Verdict.passed and c.check == Check.look and actor.role != Role.owner \
          and c.checked_by != CheckedBy.sme.value and not self._ticket_screenshots(t.id):
      raise BoardError("transition", f"criterion {c.id} is check=look: a pass needs a screenshot, and "
  ```
- board.py:1644-1646 — "you are ruling version {evidence_version} but the doc is now v{cur}; re-read and pass evidence_version={cur}, or stale_ok=true to sign the old one" (ruling m-fb5296bfbd)
  ```python
  if cur is not None and evidence_version < cur and not stale_ok:
      raise BoardError("transition",
                       f"you are ruling version {evidence_version} but the doc is now v{cur}; "
  ```
- board.py:1700-1701 — "an sme passes a line only after its evidence doc cites sources"
  ```python
  if ed is None or not self.cites_sources(ed.body_md):
      raise BoardError("validation", "an sme passes a line only after its evidence doc cites sources",
  ```
- Also: stale-criterion rules (1574, 1622); doc version conflicts (1840, 1896).

### (S) Safety / security — board.py 4; + secret_screen 1, guest_scope 403/404, topics.py private-host x3, mcp_server `_refused`

- board.py:361-362 — "a guest may not {what}"
  ```python
  if guest_scope.is_guest(actor):
      raise BoardError("forbidden", f"a guest may not {what}",
  ```
- secret_screen.py:196-198 — "{where} refused: it matches a secret ({cls}) and this epic has guest members"
  ```python
  raise BoardError(
      "secret", f"{where} refused: it matches a secret ({cls}) and this epic has guest members",
  ```
- guest_scope.py:231-232 — "a guest may not use {request.method} {path} ({why})"
  ```python
  if treat not in ("scoped", "allowed"):
      raise HTTPException(403, f"a guest may not use {request.method} {path} ({why})")
  ```
- topics.py:112 — "{what} host {host!r} is a local or private address"
  ```python
  raise BoardError(code, f"{what} host {host!r} is a local or private address", "use a public https site")
  ```

### (Q) Resource / capacity — board.py 5; + story_cap precondition, pool x5, quotes 1, fetch-size x2, one-qa-per-epic

- board.py:705-706 — "an epic holds at most {cap} open stories" (STORY_CAP = 8)
  ```python
  if len(self._open_stories(epic_id)) >= cap and not self._scope_cap_raised(epic_id):
      raise BoardError("scope", f"an epic holds at most {cap} open stories",
  ```
- board.py:713-714 — "a story holds at most {cap} tasks" (TASK_CAP = 5)
  ```python
  if len(tasks) >= cap:
      raise BoardError("scope", f"a story holds at most {cap} tasks",
  ```
- board.py:1527-1528 — "a story carries at most {cap} freshly-written criteria" (CRITERIA_CAP = 6; total ceiling 2xcap at l.1531)
  ```python
  if is_fresh and len(fresh) >= cap:
      raise BoardError("scope", f"a story carries at most {cap} freshly-written criteria",
  ```
- edp-pool service.py:1210-1214 — "max total shells = {total_cap} (EDP_MAX_TOTAL_SHELLS); {total} alive across all roles; cannot spawn another"
  ```python
  if total >= total_cap:
      return Tool.propagate(source="edp-pool", code=ErrorCode.POOL_CAPACITY_EXCEEDED,
          message=f"max total shells = {total_cap} "
  ```
- No RAM guard: pool service.py:1241-1242 "No RAM guard here (owner ruling 2026-09-07) ... the pool never refuses a spawn for it." No free-disk refusal found.

### (P) Process / behaviour policing — board.py 15; + signoff_lint, asks.py serves x2, bundles close_self + resident-architect, qa_spawn_refusal, sme_spawn_refusal

- board.py:898-899 — "a task's title is fixed at create"
  ```python
  if t.kind == TicketKind.task:
      raise BoardError("scope", "a task's title is fixed at create",
  ```
- board.py:1619-1620 — "the doer cannot verdict its own ticket"
  ```python
  if actor.id == t.assignee:
      raise BoardError("scope", "the doer cannot verdict its own ticket")
  ```
- board.py:3304-3307 — "{n} message(s) await you before you can record {status.value}: ..." (e0cec S3)
  ```python
  if status in (StatusValue.done, StatusValue.handed_off):  # e0cec S3: close_self's rule, at the earlier call
      waiting = self.inbox(actor)
      if waiting:
          raise BoardError("precondition",
  ```
- asks.py:379-380 — "a task must name the ask or finding ids it serves" (E6)
  ```python
  if not ids:
      raise _err("schema", "a task must name the ask or finding ids it serves",
  ```
- Rest of this category: see the section 3 table.

### (A) Silent auto-corrections — ~10 sites, none raise

- board.py:1515-1518 — checked_by ignored unless owner + override_reason (§24)
  ```python
  derived = self.checker_for(t)
  final = derived
  if checked_by is not None and checked_by != derived and actor.role == Role.owner and override_reason:
      final = checked_by
  ```
- board.py:553-554 — owner's parentless story auto-tagged quick
  ```python
  if kind == TicketKind.story and not parent_id and actor.role == Role.owner and not quick:
      quick, clean_tags = True, [*clean_tags, QUICK_TAG]  # the owner's parentless story IS a quick task
  ```
- board.py:1652-1656 — missing evidence_version defaulted to the doc's current version
  ```python
  elif cur is not None:
      ...
      c.evidence_version = cur
  ```
- edp-pool service.py:1131-1134 — effort clamped to the model's cap (S7)
  ```python
  clamped, note = clamp_effort(str(asked), cap) if asked else (None, None)
  if clamped:
      out["EDP_SEAT_EFFORT"] = clamped
  ```
- Others: board.py:577 over-long epic title replaced by `derive_title`; 1008-1014 retype moves pending criteria to the new checker; 2397/2425 blank gate note filled with the default question; 2431 acceptance gate note prefixed with the asks summary; quotes.py:35 `heading` "accepted and ignored"; board.py:3423 decision `binding` inherited from the decision it replaces.
- Board-authored transitions (no agent request rewritten, but the board moves state itself): `auto_carry` (1017), `_advance_epic_phase` (667), release cascade (1109).

## 3. Guards that look like judgement calls (P and A mainly)

"Cite" = decision/owner message id in nearby comments; "none" = none found.

| file:line | Verbatim message / behaviour | Cite |
|---|---|---|
| board.py:899 | "a task's title is fixed at create" | none |
| board.py:905 | "title is at most {self.TITLE_MAX} characters" (code `scope`, TITLE_MAX = 80) | Ruling #32 (2026-09-10) |
| board.py:574 | "explicit title is at most {self.TITLE_MAX} characters" | Ruling #32 |
| board.py:921 | "the `{QUICK_TAG}` tag is set when the owner opens a quick task" | S-QUICK |
| board.py:925 | "the `{HELP_TAG}` tag marks a help thread and is fixed at create" | S19 |
| board.py:997 | "a task's or a topic's work_type is fixed at create" | owner m-b9f93cddf0 (`_retype` docstring) |
| board.py:1002 | "a review story is review from create to close" | "the review-story-last hook" |
| board.py:534 | "only an epic chooses a workflow" | S13 |
| board.py:551 | "only the owner opens a quick task (tag `{QUICK_TAG}`)" | S-QUICK |
| board.py:1506 | "the doer of a ticket does not write its criteria" | pain 2026-08-23 architect epic deadlock (exemption added) |
| board.py:1620 | "the doer cannot verdict its own ticket" | none |
| board.py:941 (+ service.py:1717) | `checker_as_doer_reason`: "a {doer.role.value} seat checks {t.id} and never becomes its assignee" | S-QUICK c-3000a9760a; S-ADV finding 3 |
| board.py:1603 | "an architect fallback verdict records its reason" | e0cec S3, dec-49f1f6a911 |
| board.py:1696 | "an sme verdict records what it checked against the sources" | e0cec S6 |
| board.py:1701 | "an sme passes a line only after its evidence doc cites sources" (`##` heading regex, l.1666) | e0cec S6 |
| board.py:1631 | "criterion {c.id} is check=look: a pass needs a screenshot, ..." | t-cf891f387b, owner m-b1fe71dcca |
| board.py:1645 | "you are ruling version {evidence_version} but the doc is now v{cur}; ..." | §14 finding 3, ruling m-fb5296bfbd |
| board.py:1528 / 1531 | "a story carries at most {cap} freshly-written criteria" / "...at most {2 * cap} criteria in total (fresh + inherited)" | #37(b) (Astra, 2026-09-10), §24 |
| board.py:706 | "an epic holds at most {cap} open stories" | §24.1; lift via scope gate owner m-b0a7f9cda9, pain p-b618055b |
| board.py:714 | "a story holds at most {cap} tasks" | §24.1 |
| board.py:3306 | "{n} message(s) await you before you can record {status}: ..." | e0cec S3 |
| bundles.py:2125 | close_self `precondition`: "... message(s) await you" / "no status recorded yet" | none |
| board.py:2401 | "a {gate.value} gate needs a note: the question the answerer is asked" | t-cfd8462f9d |
| board.py:2428 | "the acceptance gate waits on the asks ledger: {held}" | e0cec S4 E5 |
| board.py:1961 | "extends links DOCS only; {x!r} is not a doc" | none |
| board.py:1786 | "a topic's sme files proposed docs; the owner activates them" | none |
| board.py:1914 / 1918 | "{id_} is active; a topic's sme proposes its next version" / "...carries a board-stamped source; a topic's sme does not edit docs" | adversary 09-23 #6 |
| asks.py:380 | "a task must name the ask or finding ids it serves" | E6 |
| asks.py:376 | "only a task names what it serves" | E6 |
| board.py:2839-2850 (`qa_spawn_refusal`; raised service.py:1687/1711) | "qa is one seat per epic: spawn it on the epic, never on a story"; `qa_wait`: "{n} stories are not in_review or done yet ..." / "a qa seat is already up on {epic.id}: one qa per epic" | Guard C1, m-ffb5b04081 |
| epic_policy.py:45 (via service.py:1681/1714, bundles.py:1942) | "SMEs are off for {epic.id}: its knowledge work is the architect's, and a spawn(role=sme) is ..." | e0cec S6 |
| bundles.py:1954 | "resident architect {resident} is up" (conflict) | none (comment: "qa full run on bb17851") |
| harness.py:110 (via service.py:1684/1745) | "adversary spawn on Fable refused until a human acknowledges the risk: ..." | S4, design-e963c656f5 §4.11, R5 |
| board.py:2483-2498 (`_design_signoff_lint`, via signoff_lint) | "criterion {c.id} on story {s.id} is checked by owner, which has no seat path ... drop the owner override"; "non-review story {to.id} is blocked by the review story {frm.id} — ... remove that blocks link" | Design §24 rule 2 (v22) |
| board.py:1512-1518 (A) | checked_by ignored unless owner + override_reason | §24, owner ruling v22 2026-09-08 |
| board.py:553 (A) | owner's parentless story silently tagged `quick` | S-QUICK |
| board.py:577 (A) | over-long epic title silently derived | Ruling #32 |
| pool service.py:1160 (A) | `_clamp_seat_effort`: effort lowered to model cap or dropped | S7 (owner §6 "max effort high") |
| quotes.py:35 (A) | `heading` accepted and ignored | none |

## 4. Data-driven vs hard-coded

### Data-driven

- Status moves: `_guard_transition` (board.py:1041-1053) takes legal edges from `wf.legal()` and runs each edge's declared `requires` via `_wf_check` / `wf.missing`. All `_arrive_guards` preconditions (workflow.py:608-661) and gate preconditions (`_signoff_gate`, `_plain_gates`) are data; Lean/Solo presets rewrite their messages and roles (workflow.py:785-807).
- Permissions: `wf.allowed(name, role)` (workflow.py:532-533), used 7 times in board.py (set_title, edit_ticket, assign, set_design_ref, evidence, task_verdict). Standard's table: workflow.py:752-757.
- Creators / criterion authors / checkers / doc authors come from role definitions (`wf.creators`, `wf.criterion_authors`, `wf.criterion_checkers`, `wf.doc_authors`).
- Caps via `wf.cap(...)`, but the values come from constants at board.py:146-148 (STORY_CAP 8, TASK_CAP 5, CRITERIA_CAP 6).
- Hooks: closed registry (workflow.py:439-451), queried via `wf.hook` / `hook_param` at board.py:673, 1109, 1113, 1145, 1151, 1196, 1470-1475, 1501, 1760, 2477-2478, 2868, 2889; `one_checker_per_epic` via `_hook_roles` at board.py:2657.

### Hard-coded in Python

- 51 `Role.<name>` literals in board.py (e.g. owner bypasses at 1517, 1594, 1617, 1627, 1685; architect/owner checks at 3177, 3192, 3418).
- Criteria-add status list (1507); quick/help tag, task title and work_type "fixed at create" (899, 921, 925, 997, 1002); TITLE_MAX = 80 (502).
- Screenshot rule (1627); sources rule (1666-1701); evidence-version rule (1641-1650); stale rules (1573, 1621).
- `checker_as_doer_reason` names qa/adversary (3229); `qa_spawn_refusal` (Role.qa, 2844); inbox-before-status (3304); decision length caps (3386).
- asks.py `check_serves`; bundles.py close_self and resident-architect; doer-writes-criteria / doer-verdict guards (1502-1506, 1619).

### Standard workflow hooks (verbatim)

workflow.py:758: `"hooks": _all_hooks_on(),` (every registry hook on with default params).

workflow.py:705-706:
```python
def _all_hooks_on() -> dict[str, dict[str, Any]]:
    return {name: {"on": True, "params": dict(params)} for name, params in HOOKS.items()}
```

workflow.py:439-451:
```python
HOOKS: dict[str, dict[str, Any]] = {
    "epic_auto_advance": {},  # the board carries an epic's phase from facts (in_progress, in_review, signed_off)
    "release_cascade": {"review_work_type": "review"},  # released tickets promote signed_off successors to ready
    "criteria_auto_done": {"epic_checker": "qa"},  # in_review → done once every criterion passed (an epic needs the epic checker)
    "signoff_before_start": {},  # a quick task starts only after the owner's design sign-off
    "evidence_before_review": {},  # in_review needs evidence on every criterion
    "acceptance_pairs_checker": {"role": "qa"},  # the acceptance gate pairs `<role>.<epic>` once
    "resident_designer": {"role": "architect"},  # the epic's own designer walks its epic and is addressed as it
    "review_story_last": {"work_type": "review"},  # the review story waits on its siblings, never blocks them
    "knowledge_tickets": {"checked_by": "sme"},  # knowledge tickets are checked by this role (e0cec S6: their own sme)
    "one_checker_per_epic": {"role": "qa"},  # a `<role>.<epic>` checker seat verdicts only its own epic
    "quick_task": {"tag": "quick", "checked_by": "owner"},  # the owner's parentless story is a quick task
}
```

Solo turns off `acceptance_pairs_checker` and `one_checker_per_epic` and sets `criteria_auto_done.epic_checker` = "owner" (workflow.py:827-831). Lean and Solo set `resident_designer.role` and `knowledge_tickets.checked_by` to "owner".

### Which guards a hook can switch off

- `evidence_before_review` gates the in_review `evidence_all` precondition (workflow.py:647).
- `signoff_before_start` gates the quick-task `design_signed` precondition (workflow.py:636).
- `review_story_last` and `acceptance_pairs_checker` gate parts of the signoff lint.
- The other P and E guards in section 3 (screenshot, sources, doer-verdict, fixed-at-create, title, serves, inbox, qa-spawn) cannot be turned off by any hook or permission.

## 5. Kept or hinted (s-0b8d2e5393, design-63db8a7d42 item I; owner m-d611346eca, m-f65239bfa7)

The rule: the board refuses state transitions, who may change status or approve, safety and security, `evidence_ref`,
the doc version check, the shell cap and "no one approves their own work". Every other refusal became **advice**: the
call goes ahead and `advice.advise(...)` puts one line in the reply's `hint` (`src/edp8/advice.py`; `service.ok()` adds
it, `close_self` and `spawn` carry it in their own result). A silent rewrite of an agent's input says so the same way.
Plain input validation (`schema`/`invalid`/`not_found`: a missing id, an empty title, a field the call cannot use) is
not a guard and stays a refusal. Line numbers in sections 2-3 are the pre-change survey.

### 5a. Changed to a hint (the call goes ahead)

| Site | Rule | Reply now says |
|---|---|---|
| board.py ticket_update (title, task) | a task's title is fixed at create | "a task's title is normally fixed at create ... changed anyway" |
| board.py `_retype` (task) | a task's work_type is fixed at create | "a task's work_type is normally fixed at create; changed anyway" |
| board.py criterion_create | the doer of a ticket does not write its criteria | "the doer ... does not normally write its criteria ... added anyway" |
| board.py criterion_create | at most 6 fresh / 12 total criteria per story | "a story normally carries at most 6 ... this is number N" |
| board.py `_enforce_task_cap` | a story holds at most 5 tasks | "a story normally holds at most 5 tasks and this is number N" |
| board.py criterion_update (architect fallback) | an architect fallback verdict records its reason | "should record its reason; recorded without one" |
| board.py criterion_update (look) | a look pass needs a screenshot | "a pass should rest on a screenshot ... passed as given" |
| board.py `_sme_verdict_guard` (note) | an sme verdict records what it checked | "should record what it checked ...; recorded without a note" |
| board.py `_sme_verdict_guard` (sources) | an sme passes a line only after its evidence doc cites sources | "should pass a line only after its evidence doc cites sources; passed as given" |
| board.py record_status | unread messages before done/handed_off | "N message(s) still await you; recorded done anyway: ..." |
| bundles.py `_close_self` | unread messages or no status before close | the shell closes; the hint lists what was left |
| board.py `require_gate_note` | a gate needs a note | the gate opens with the default question; "should carry a note" |
| epic_work.py `check_serves` (was asks.py) | a task names the asks it serves; only a task names them | task created without; "serves ignored" on a story |
| service.py spawn + seat-token | qa is one seat per epic, once every story is in review | spawned anyway; the hint names what is not ready (carried through the MCP `spawn` result) |
| bundles.py `_spawn` | a second architect on a story while the epic's architect is up | spawned anyway; the hint names the resident |

### 5b. Silent rewrites that now say so

| Site | Rewrite | Reply now says |
|---|---|---|
| board.py criterion_create | `checked_by` ignored unless owner + override_reason | "checked_by=X ignored: the board derives the checker (Y)" |
| board.py criterion_update | missing `evidence_version` defaulted to the doc's current version | "evidence_version not given: recorded ... (vN)" |
| board.py ticket_create | the owner's parentless story tagged `quick` | "tagged `quick`" |
| board.py ticket_create | an over-long epic title replaced by a derived one | "derived the short title ...; the full text is kept as the epic's words" |
| board.py record_decision | `binding` inherited from the decision it replaces | "binding inherited" |
| quotes.py | locator `heading` accepted and ignored | "quote locator `heading` ignored" |

Not changed, still silent: the pool's effort clamp (edp-pool `_clamp_seat_effort`, S7; the pool's own spawn reply
carries `effort_note`), `_retype` moving pending criteria to the new checker (the reply's `rechecked` list and the
`criterion_checker_overridden` events name it), board-authored transitions (`auto_carry`, `_advance_epic_phase`,
the release cascade: they are the board's own acts, with events).

### 5c. Kept as refusals, with the reason

| Site | Rule | Why it stays |
|---|---|---|
| `_guard_transition`, `_wf_check` preconditions (`evidence_all`, `verdicts_passed`, `not_terminal`, ...) | state transitions | state transitions |
| board.py criteria-add status list; `_retype` on done/dropped; topic opened/closed by owner | a ticket past review takes no new criteria; a closed ticket keeps its type | state transitions |
| board.py gate acceptance waits on open requirements (`requirements_mod.blocked_reason`); `signoff_lint` | gate preconditions on the epic walk | state transitions (a gate opens or answers a move) |
| board.py story cap (`_enforce_story_cap`, `story_cap` precondition) | an epic holds at most 8 open stories | design J: stays hard; the refusal says to ask the owner in chat and pass the owner's yes as `cap_lift_message`. The board checks the sender (this epic's own owner, on this epic or one of its tickets), never the meaning (m-28ed419c47); a valid id is recorded when passed, even below the cap, as one `scope_cap_lifted` event (Astra F1, F2, Q1) |
| `wf.creators`, `assign`, `set_title`, `set_design_ref`, `criterion_authors`, `criterion_checkers`, `task_verdict`, `evidence`, `edit_ticket` | who may do what | who may change status or approve |
| board.py binding authority, `set_binding`, `retire_lesson` | only architect/owner bind or retire | who may approve |
| board.py doer cannot verdict its own ticket; `checker_as_doer_reason` (board + service spawn assign) | a checker never becomes the doer it checks | no one approves their own work |
| board.py verdict needs `evidence_ref` | evidence first | `evidence_ref` |
| board.py evidence_version older than the doc | re-read before ruling | the doc version check |
| board.py stale criterion cannot pass | the owner amended its ask | a pass would sign words the owner changed (the version-check family) |
| board.py doc version conflicts; topic sme proposes docs, does not edit | doc versions; who edits | the doc version check; who may act |
| `_refuse_guest`, `guest_scope`, `secret_screen`, topics private-host | guests, secrets, SSRF | safety and security |
| harness.py `fable_refusal` | adversary on Fable until a human acknowledges | safety (design-63db8a7d42 v9 row I) |
| `epic_policy.sme_refusal` | SMEs are off for the epic | enforces the owner's explicit `sme:off` setting; not an agent convention (design-63db8a7d42 v9 row I) |
| edp-pool `POOL_CAPACITY_EXCEEDED`, `PanelRefused`, `POOL_ROLE_REFUSED` | the shell cap | the shell cap |
| board.py: `QUICK_TAG` / `HELP_TAG` fixed after create, only the owner opens a quick task, a topic's work_type, a review story stays review | the tag or type selects the lifecycle or the resident seat | state transitions: changing it mid-life would change the state machine (checker, design step, seat role) (design-63db8a7d42 v9 row I) |
| board.py: only an epic chooses a workflow; explicit epic title vs words, and a title over 80 characters at create AND at update (one refusal, one hint; Astra Q2); `extends` links docs only; a serves id that is not a requirement or finding of this epic | the call cannot be honoured as asked | input the call cannot use (not a convention) |
| bundles.py `_close_self`: a topic's resident sme | the owner closes a topic | state transition (topic lifecycle) |
