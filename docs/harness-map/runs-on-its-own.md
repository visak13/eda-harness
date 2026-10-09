# Autonomous actions inventory (board, pool, broker)

Repo: `<repo>`. `board.py` = `v8/src/edp8/board.py`; `pool/` = `edp-pool/src/edp_pool/`.
Broker (`edp-broker`): no autonomous behaviour (only the SSE stream loop at `service.py:262`).

Categories: A = ticket/epic status change · B = starts/resumes/revives/wakes/kills a seat or process · C = creates owner work · D = posts messages/notes · E = service self-healing · F = other.

## Table (70 rows: items 1-64 plus 60a-60f)

| # | Cat | What | Trigger | file:line |
|---|---|---|---|---|
| 1 | B/F | Board pool-watch thread: mirror sessions + drain pairing queue every 10 s | Board start if EDP_POOL_URL or EDP8_POOL_WATCH | v8/src/edp8/service.py:2193-2220 |
| 2 | F | Pool sessions mirrored to board as alive/dead | Pool-watch tick | v8/src/edp8/pool_adapter.py:259-318 |
| 3 | D/B | shell_dead/stalled event; epic checkers requeued | Mirrored death/stall | board.py:2600-2632 |
| 4 | D/C | "crashed"/"fyi" broker page to recovery seat (epic owner first) | PUT /v1/sessions death | v8/src/edp8/service.py:1622-1634 |
| 5 | F | Dead seat's browser session closed | Same | v8/src/edp8/service.py:1617-1621 |
| 6 | B/D | run_pending_pairings: spawn/resume seat; "queued"/"spawn failed" notes | Pool-watch tick | board.py:1271-1317 |
| 7 | B | _spawn_seat/_resume_saved_seat: participant, token, resume or spawn | From #6 | board.py:1344-1423 |
| 8 | C/D | Boot rebuilds owed pairings as held; one question to architect, else owner | Board constructor | board.py:269-270, 1294-1298, 1319-1342 |
| 9 | B | stage_qa queues qa.<epic> when qa_ready and qa owes a verdict | #15, #11, #12, boot rebuild | board.py:2865-2870 |
| 10 | C | open_acceptance: board opens acceptance gate (by="board") when ledger clear | _stage_acceptance | board.py:2872-2881 |
| 11 | C/B | after_ledger_change retries #9 + #10 | ask_triage, ask_verdict, criterion reword | board.py:2883-2893; asks.py:162, 262 |
| 12 | B/A | gate_open staffs qa (acceptance) / auto-carries epic (design_signoff) | Any gate_open | board.py:2413-2416, 2433-2438 |
| 13 | A | _advance_epic_phase: forward-only epic move, by board | #14, #15, #18, #23 | board.py:667-686 |
| 14 | A | auto_carry drafted→designed | design_ref set; criterion added; design_signoff opened | board.py:1017-1039, 985, 1542, 2416 |
| 15 | A/C | Epic → in_review when all stories released (stages qa, opens acceptance) | Child/epic status change | board.py:1140-1149, 1194-1199 |
| 16 | A | Parent ready/signed_off → in_progress when a child is active | Child status change | board.py:1164-1169 |
| 17 | A | Epic in_review → in_progress on story reopen | Child in_progress/blocked | board.py:1170-1176 |
| 18 | A | Epic drafted/designed → in_progress when a child starts | Child status change | board.py:1177-1186 |
| 19 | D | Note event "all tasks done; hand the story to review" | Last task released | board.py:1200-1201 |
| 20 | A | Successors signed_off → ready when all blockers released | Ticket released | board.py:1102-1125 |
| 21 | A | Own signed_off → ready | Own status change | board.py:1150-1156 |
| 22 | A | ready → signed_off on new unreleased blocker | link_create(blocks) | board.py:1976-1993 |
| 23 | A | Design sign-off answer → epic signed_off; descendants released | Owner answers design_signoff | board.py:2556-2571 |
| 24 | A | _auto_advance in_review → done when all criteria passed | Criterion update; hand-off; message on active non-epic; epic in_review | board.py:1753-1772, 1724, 975-981, 2343-2347 |
| 25 | A | Quick task in_review → in_progress | Owner fails its criterion | board.py:1740-1751 |
| 26 | A/C | Terminal ticket's open gates closed, by board | Status → done/partial/dropped | board.py:1132-1133, 2592-2597 |
| 27 | B/D | requeue_checkers: queue fresh checker for stuck criteria (cap 3) + note | in_review; record_status done/handed_off/reviewed; seat death | board.py:2988-3031, 1134-1135, 3325-3326, 2630 |
| 28 | F | architect_fallback: resident architect may verdict stuck criterion; owner not asked | Architect criterion_update | board.py:2960-2969, 1598-1605 |
| 29 | C | Every human message with text on an epic tree becomes an Ask | message_send (ledger=True) | asks.py:58-69; board.py:2321-2322 |
| 30 | F/A | Ask amend: criteria stale, verdicts reset to pending, checker → qa | ask_triage amends | asks.py:195-232 |
| 31 | F | Asks auto-settled: reply/resolves/owner message; phase past (by board); author seat dead | message_send; status emit; read time | board.py:3090-3111, 3117-3127, 2796-2801 |
| 32 | F | Auto-claim from verdict note (created_by board) | criterion_update with note | records.py:169-186; board.py:1721-1722 |
| 33 | F | Auto-decision from accepted deviation | Answer to a deviation | records.py:189-206; board.py:2341-2342 |
| 34 | F | Auto-decision from answered gate | gate_answer | records.py:209-219; board.py:2506-2507 |
| 35 | F | Open pains turned into lessons | Every context() read | board.py:2686-2688; records.py:230-272 |
| 36 | F/D | Library auto-link + board note | Quick task create; design_signoff | library.py:213-243; board.py:618-619, 2508-2509 |
| 37 | B/A | topics.ensure_seat: resident seat assigned and queued | Topic create; non-assignee message on topic; help thread | topics.py:172-191; board.py:2338-2340; help.py:71 |
| 38 | C | Criteria checked_by owner (quick tasks, Library topics, Lean/Solo) | criterion_create derivation | board.py:1459-1476, 1515; workflow.py:450, 812-831 |
| 39 | B/D | Revive self-closed seat addressed by a message; refusal as fyi | after_message | delivery.py:184-228, 262-267 |
| 40 | D/C | Other closed seats: fyi to recovery seat (owner first) | after_message | delivery.py:268-276 |
| 41 | C | Question/deviation with no recipients falls back to epic owner | Every delivery plan | delivery.py:38-45 |
| 42 | D | Status recipients auto-chosen (architect, owner, spawner), published | record_status | board.py:3327-3335; delivery.py:298-311 |
| 43 | D | Gate broker wake only on route path; board-opened gates reach owner via feed only | POST gate open | delivery.py:314-321; service.py:1572 |
| 44 | D | Owner feed paged by board-authored gate/status/shell events | Every emit | board.py:3981-4035 |
| 45 | E | Supervisor restarts service after 3 failed probes (15 s); >5 in 10 min = crash_loop | Supervisor loop | v8/src/edp8/supervisor.py:59-89, 160-191 |
| 46 | D | service_restarted event on board | Supervisor POST | v8/src/edp8/service.py:1482-1490 |
| 47 | F | Startup migrations, pins, epic_id backfill, index rebuild, upload sweep, hourly DB optimize | Start; timers | store.py:163-218; board.py:264; service.py:465-474, 2300-2339 |
| 48 | D | RSI tripwire finding (off by default) | Timer | v8/src/edp8/rsi.py:590-613 |
| 49 | F | Plane mirror + webhook notes (off by default) | Timer; webhook | v8/src/edp8/plane_adapter.py:205-246, 274-291 |
| 50 | F | Browser sessions idle 30 min released (every 60 s) | Timer | v8/src/edp8/browser_proxy.py:355-378 |
| 51 | D | Slack ping per broker message (if bridge runs) | Per-person SSE thread | v8/src/edp8/slack_bridge.py:119-140, 231 |
| 52 | B | Feed-driver heartbeat (1800 s) wakes doing seat with in_progress ticket, or on unseen changes | Seat-side timer | v8/src/edp8/feed_driver.py:134-232, 361-365 |
| 53 | F/B | Codex seat cron ticker (seat-created jobs) + delivery retry | Seat-side timers | v8/src/edp8/codex_seat/tools.py:677-680, 1036-1040, 383-392 |
| 54 | F | Harness update waits (≤12 h) until no live seats, then installs | Admin "update when idle" | v8/src/edp8/admin/harnesses.py:169-184 |
| 55 | F/E | Desktop app starts services if down | Opening the app | v8/src/edp8/desktop.py:698-720 |
| 56 | B/E | Update helper resumes parked seats; on failure rolls back and resumes | heronry update runner | v8/src/edp8/update_helper.py:347-377 |
| 57 | A/F | Pool start marks previously-live seats dead ("interrupted") | Pool startup | pool/service.py:745-790 |
| 58 | B | Pool start resumes park_for_update rows | Pool startup thread | pool/service.py:757, 792-819 |
| 59 | B | Pool start re-spawns neuron heartbeat drivers | Pool startup | pool/service.py:522-556 |
| 60 | B | Resume watchdog thread (5 s) runs 60a-60f | Pool startup (default on) | pool/service.py:857-867; pool/resume_watchdog.py:177-205 |
| 60a | B | Kill turn running past 2400 s | Watchdog tick | pool/resume_watchdog.py:332-346 |
| 60b | D/F | Crash sweep marks rows dead; publishes `crashed` to parent handle | Watchdog tick | pool/service.py:1711-1756; pool/resume_watchdog.py:297-348 |
| 60c | B | Resume parked channel member addressed by `for:`/`@all` | Watchdog tick | pool/resume_watchdog.py:257-287 |
| 60d | B | Resume parked shell whose inbox grew past watermark | Watchdog tick | pool/resume_watchdog.py:356-400 |
| 60e | B | Resume parked shell on rx file growth | Watchdog tick | pool/resume_watchdog.py:403-451 |
| 60f | B | Resume any shell parked >1800 s, no traffic needed | Watchdog tick | pool/resume_watchdog.py:454-471 |
| 61 | F | reconcile_sessions marks active rows with dead process as done | Usage/capacity reads | pool/service.py:1004-1036 |
| 62 | F | Phantom handle lock of dead holder reaped | Spawn admission | pool/service.py:1347-1369 |
| 63 | B | Out-of-tree pause watchdog resumes suspended tree if observer died | Detached process | pool/pause_watchdog.py:205-229 |
| 64 | B | Quick task create spawns engineer.<story> | Owner opens a quick task | v8/src/edp8/service.py:1770-1806 |


## Category B quotes (verbatim, sed-extracted)

**#1** `v8/src/edp8/service.py:2210-2220`
```python
                    # design §24 rule 3: drain the checker-pairing queue on the same tick — spawn a
                    # qa seats whose RAM headroom is now sufficient, retry the ones still under the
                    # seat floor (the queued-note guard keeps the retry quiet).
                    res = board.run_pending_pairings()
                    if res.get("spawned"):
                        log.info("paired checkers: %s", res["spawned"])
                except Exception as e:
                    log.warning("pairing drain error: %s", e)
                time.sleep(10)  # death-detection latency rides this cadence

        threading.Thread(target=_pool_watch, name="edp8-pool-watch", daemon=True).start()
```

**#3** `v8/src/edp8/board.py:2626-2630`
```python
            # (closed itself deferred, or the owner reaped or force-quit it): a fresh checker would undo the park
            # and pop a new window per close (owner m-b0c290f469: qa was respawned three times while told to hold)
            parked = any(k in (reason or "").lower() for k in ("closed by self: deferred", "reaped", "interrupted"))
            if kind == EventKind.shell_dead and not parked:
                records.safely(self._requeue_epic_checkers, ticket_id)
```

**#6** `v8/src/edp8/board.py:1294-1310`
```python
                if info.get("held"):  # owner m-e2edc8d256: a restart never launches a shell; ask once instead
                    if not info.get("held_asked"):
                        self._held_pairing_ask(pid, info)
                        info["held_asked"] = True
                    continue
                free = self._host_free_mb()
                if free is not None and free < self.SEAT_FLOOR_MB:
                    queued.append(pid)
                    if not info.get("noted"):
                        self._pairing_note(info["ticket"],
                                           f"{info['role']} for {info['ticket']} queued: {free} MB free")
                        info["noted"] = True
                    continue
                if self._spawn_seat(info["role"], pid, info["ticket"]):
                    spawned.append(pid)
                    self._pending_pairings.pop(pid, None)
                else:
```

**#7** `v8/src/edp8/board.py:1388-1396`
```python
        if self._resume_saved_seat(participant_id, env):
            return True
        spec = self.seat_spawn_spec(ticket_id, role)  # S13: the pinned workflow's card + capacity
        if spec["env"]:
            env = {**(env or {}), **spec["env"]}
        try:
            res = self._pool_adapter().spawn(role, participant_id, env=env,
                                             model=choice.pool_model, effort=choice.effort,
                                             **spec["capacity"])
```

**#7 resume** `v8/src/edp8/board.py:1410-1416`
```python
        if not self.store.query("session", {"participant_id": participant_id}, limit=1):
            return False
        resume = getattr(self._pool_adapter(), "resume", None)
        if resume is None:
            return False
        try:
            res = resume(participant_id, env=env) if env else resume(participant_id)
```

**#9** `v8/src/edp8/board.py:2868-2870`
```python
        checker = self.workflow_of(epic).hook_param("acceptance_pairs_checker", "role")
        if checker == Role.qa.value and epic.status not in _TERMINAL and self.qa_ready(epic) and self._qa_owes(epic):
            self._enqueue_pairing(f"{checker}.{epic.id}", checker, epic.id, held=held)
```

**#11** `v8/src/edp8/board.py:2891-2893`
```python
        kids = self.children(epic.id)  # type: ignore[union-attr]
        if kids and all(k.status == TicketStatus.dropped or self._released(k) for k in kids):
            records.safely(self._stage_acceptance, epic)
```

**#12** `v8/src/edp8/board.py:2433-2438`
```python
                note = f"{gen}. {note}"
        ev = self._emit(t.id, EventKind.gate_opened, {"gate": gate, "by": by, "note": note})
        # §24 rule 3, moved by e0cec S4: qa is staffed on qa_ready (Board.stage_qa), not by the gate: qa judges the asks
        # that hold the gate. Opening the gate by hand still stages it when qa is ready and owes a verdict.
        if gate == Gate.acceptance and t.kind == TicketKind.epic:
            self.stage_qa(t)
```

**#27** `v8/src/edp8/board.py:3011-3019`
```python
            if len(prior) >= self.REQUEUE_CAP:
                continue
            ids = [i for i, _ in items]
            self._enqueue_pairing(pid, role, tid)
            self._emit(t.id, EventKind.checker_requeued, {"role": role, "seat": pid, "cause": items[0][1],
                                                          "criteria": ids})
            self._pairing_note(t.id, f"a fresh {role} checker ({pid}) is queued for {', '.join(ids)}: "
                                     f"{items[0][1].replace('_', ' ')}. If it cannot clear them, the epic's architect may, "
                                     f"with its reason recorded; the owner is not asked.")
```

**#37** `v8/src/edp8/topics.py:186-190`
```python
        if t.assignee != pid:
            t.assignee = pid
            board.store.put("ticket", t)
            board._emit(t.id, EventKind.assigned, {"assignee": pid, "by": "board"})
        board._enqueue_pairing(pid, role, t.id)
```

**#39** `v8/src/edp8/delivery.py:262-267`
```python
        if p.type == "agent" and "." in to and _seat_alive(board, to) is not True and m.kind.value != "status":
            last = _closed_by_self(board, to) if to != actor_id else None
            seat_ticket = _seat_ticket(board, to, last, m) if last is not None else None
            if seat_ticket is not None and seat_ticket.status.value not in _ENDED:
                receipts[to] = _revive(board, actor_id, to, m, seat_ticket.id)
                continue
```

**#39 worker** `v8/src/edp8/delivery.py:215-227`
```python
        board._emit(ticket_id, EventKind.seat_revive_started, {"seat": pid, "by": actor_id, "message": m.id})

    def run() -> None:
        try:
            why = _revive_call(board, pid)
            if why is not None:
                refuse(why)
        finally:
            _workers.discard(threading.current_thread())

    worker = threading.Thread(target=run, name=f"revive-{pid}", daemon=True)
    _workers.add(worker)
    worker.start()
```

**#52** `v8/src/edp8/feed_driver.py:222-229`
```python
        except Exception:  # noqa: BLE001 — a failed read never wakes a seat
            return None
        if tid:
            return self._wake({"reason": "liveness", "ticket": tid, "next": _LIVENESS_NEXT})
        return None

    def _wake(self, body: dict) -> dict:
        line = {"heartbeat": body}
```

**#53** `v8/src/edp8/codex_seat/tools.py:1036-1040`
```python
        while not self._stop.wait(self._tick_s):
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001
                self.log(f"cron tick failed: {e}")
```

**#56** `v8/src/edp8/update_helper.py:352-354`
```python
        reason = "the new version did not come up healthy"
    parked = list(plan.get("parked") or [])  # S10 #7: the in-process apply parked them before it stopped anything
    if not reason:
```

**#56 rollback** `v8/src/edp8/update_helper.py:370-371`
```python
    _restore(plan)
    up = _run(plan, "start previous", plan["start_argv"], timeout=300) and _healthy(plan["health_url"])
```

**#58** `edp-pool/src/edp_pool/service.py:802-813`
```python
            return resumed
        for sid, s in list(self.sessions.items()):
            if s.get("state") != "parked" or not s.get("park_for_update"):
                continue
            handle = s.get("handle")
            if not handle or _proc_alive(s.get("proc")) is not False:
                continue
            s.pop("park_for_update", None)
            self._persist()
            try:
                self.resume(handle)
                resumed.append(handle)
```

**#59** `edp-pool/src/edp_pool/service.py:550-555`
```python
                                      float(row.get("heartbeat_secs", 1800)),
                                      self.broker_url)
            if pid is not None:
                row["pid"] = pid
                row["armed_at"] = _utc_now_iso()
        self._persist()
```

**#60** `edp-pool/src/edp_pool/service.py:861-867`
```python
        if not edp_settings.get("EDP_RESUME_WATCHDOG"):
            _log.info("resume_watchdog_disabled",
                      "EDP_RESUME_WATCHDOG is off")
            return
        from .resume_watchdog import ResumeWatchdog
        self._resume_watchdog = ResumeWatchdog(self)
        self._resume_watchdog.start()
```

**#60a** `edp-pool/src/edp_pool/resume_watchdog.py:334-346`
```python
            bound = _turn_timeout_secs()
            if bound > 0:
                for _tsid, _ts in list(self.svc.sessions.items()):
                    if _ts.get("state") != "active":
                        continue
                    runtime = getattr(self.svc.spawner, "turn_runtime",
                                      lambda _s: None)(_tsid)
                    if runtime is not None and runtime > bound:
                        _log.warning(
                            "turn_timeout_kill", _ts.get("handle") or _tsid,
                            handle=_ts.get("handle"), sid=_tsid,
                            runtime_secs=int(runtime), bound_secs=int(bound))
                        self.svc.spawner.kill(_tsid)
```

**#60c** `edp-pool/src/edp_pool/resume_watchdog.py:279-287`
```python
                if target == "@all":
                    for h, sid in parked.items():
                        if h in members:
                            self.svc.resume(h)
                    continue
                if target in parked:
                    _log.info("channel_member_wake", target,
                              handle=target, channel=name)
                    self.svc.resume(target)
```

**#60d** `edp-pool/src/edp_pool/resume_watchdog.py:395-398`
```python
                if depth > watermark:
                    _log.info("resume_watchdog_fire", handle, handle=handle,
                              watched=h, depth=depth, watermark=watermark)
                    self.svc.resume(handle)
```

**#60e** `edp-pool/src/edp_pool/resume_watchdog.py:445-449`
```python
                if fire:
                    _log.info("resume_watchdog_rx_file_fire", handle,
                              handle=handle, watched=str(path),
                              size=size, baseline=base)
                    self.svc.resume(handle)
```

**#60f** `edp-pool/src/edp_pool/resume_watchdog.py:457-470`
```python
            beat = _heartbeat_secs()
            parked_at = parked.get("parked_at")
            if beat > 0 and parked_at:
                try:
                    age = (datetime.now(timezone.utc)
                           - datetime.fromisoformat(parked_at)
                           ).total_seconds()
                except ValueError:
                    age = None
                if age is not None and age > beat:
                    _log.info("resume_watchdog_heartbeat", handle,
                              handle=handle, parked_secs=int(age),
                              band_secs=int(beat))
                    self.svc.resume(handle)
```

**#63** `edp-pool/src/edp_pool/pause_watchdog.py:215-224`
```python
    fire, why = _wait_then_decide(
        a.token_dir, a.pid, a.runid, a.deadline_epoch)
    if not fire:
        print(f"stand down: {why}")
        return 0

    # Fire. `resume_tree` re-checks the fingerprint, so a recycled pid is
    # refused here exactly as it would be on the pool's own resume path.
    from .proctree import resume_tree
    res = resume_tree(a.pid, ct, token_dir=a.token_dir, runid=a.runid)
```

**#64** `v8/src/edp8/service.py:1796-1799`
```python
        seat = f"engineer.{t.id}"
        spawned = _spawn_seat(a, SessionSpawnIn(role=Role.engineer, participant_id=seat, ticket_id=t.id,
                                                model=b.model or None, effort=b.effort or None,
                                                assign=True))
```

## Category C quotes (verbatim, sed-extracted)

**#4** `v8/src/edp8/service.py:1628-1634`
```python
        if (not b.presence_stale and s.state in (SessionState.dead, SessionState.stalled)
                and (prev is None or prev.state != s.state)
                and "interrupted" not in (b.reason or "").lower()):  # a force quit is the owner's act, never a crash page
            clean = any(k in (b.reason or "").lower() for k in ("closed by self", "reaped", "clean exit"))
            who = board.recovery_seat(b.ticket_id, exclude={b.participant_id}) if b.ticket_id else None
            if who:  # THIS epic's human owner, else its live resident architect — never a shared handle
                broker_adapter.publish("pool", who, "fyi" if clean else "crashed",
```

**#8** `v8/src/edp8/board.py:1328-1342`
```python
        to = self.resident_architect(epic)
        if self.store.get("participant", to) is None:
            to = self.epic_owner(t.id) or to
        text = (f"pending pairing: {info['role']} for {t.id}, not started because of a restart. "
                f"Spawn or resume {pid} when you want it; nothing starts on its own.")
        if any(x.created_by == "board" and x.text == text and not self.ask_resolved(x)
               for x in self.store.query("message", {"ticket_id": t.id, "kind": MessageKind.question},
                                         limit=1000)):
            return
        m = Message(id=new_id("m"), ticket_id=t.id, to=to, kind=MessageKind.question, text=text,
                    created_by="board")
        self.store.put("message", m)
        self._emit(t.id, EventKind.message_sent,
                   {"message": m.id, "to": to, "kind": MessageKind.question, "from": "board",
                    "from_type": "agent", "from_role": "board", "text": text[:280], "mentions": []})
```

**#10** `v8/src/edp8/board.py:2872-2881`
```python
    def open_acceptance(self, epic: Ticket) -> None:
        """The board opens the acceptance gate by itself once the ledger is clear (E5); until then it stays closed."""
        if epic.status in _TERMINAL or self.open_gates(epic.id, Gate.acceptance):
            return
        if asks_mod.blocked_reason(self, epic.id) is None:
            self.gate_open(epic.id, Gate.acceptance, by="board", note=self.gate_question(epic, Gate.acceptance))

    def _stage_acceptance(self, epic: Ticket) -> None:
        self.stage_qa(epic)
        self.open_acceptance(epic)
```

**#15** `v8/src/edp8/board.py:1194-1199`
```python
            if kids and all(k.status == TicketStatus.dropped or self._released(k) for k in kids):
                if (parent.kind == TicketKind.epic and parent.status not in (TicketStatus.done, TicketStatus.partial)
                        and self.workflow_of(parent).hook("epic_auto_advance") is not None):
                    self._stage_acceptance(parent)
                    self._advance_epic_phase(self.ticket(parent.id), TicketStatus.in_review,
                                             trigger="every story released")
```

**#26** `v8/src/edp8/board.py:2592-2597`
```python
    def _close_open_gates(self, t: Ticket) -> None:
        """§24.1(a): retire every open gate on a ticket that has gone terminal (dropped/done/partial),
        so a dead epic never keeps an acceptance/design_signoff gate that re-derivation would honour."""
        for e in self.open_gates(t.id):
            self._emit(t.id, EventKind.gate_closed, {"gate": e.data.get("gate"), "by": "board",
                                                     "reason": f"{t.kind} {t.id} is {t.status}"})
```

**#29** `v8/src/edp8/asks.py:58-68`
```python
def record_message(board: "Board", actor: Participant, t: Ticket, m: Message) -> Ask | None:
    """The board's own write at message_send: a human's message with text on an epic's tree is an ask. None for an
    agent, an empty text, a ticket outside an epic (a quick task, a topic) or a message already recorded."""
    if actor.type != "human" or not (m.text or "").strip():
        return None
    epic = board.epic_of(t)
    if epic.kind != TicketKind.epic or board.store.query("ask", {"source": m.id}, limit=1):
        return None
    a = Ask(id=new_id("ask"), epic_id=epic.id, ticket_id=t.id, source=m.id, created_by=actor.id)
    board.store.put("ask", a)
    board._emit(a.id, EventKind.ask_created, {"epic": epic.id, "ticket": t.id, "source": m.id, "by": actor.id})
```

**#29 call site** `v8/src/edp8/board.py:2321-2322`
```python
        if ledger:
            records.safely(asks_mod.record_message, self, actor, t, m)  # a human's message on an epic is an ask
```

**#38** `v8/src/edp8/board.py:1470-1475`
```python
        if t.work_type == WorkType.knowledge and wf.hook("knowledge_tickets") is not None:
            if is_topic(t):  # a Library topic is the owner's own (e0cec S6: an epic's knowledge ticket is its sme's)
                return CheckedBy.owner.value
            return wf.hook_param("knowledge_tickets", "checked_by")
        if is_quick(t) and wf.hook("quick_task") is not None:
            return wf.hook_param("quick_task", "checked_by")  # S-QUICK: the owner verdicts from Needs you
```

**#38 workflow** `v8/src/edp8/workflow.py:450-450`
```python
    "quick_task": {"tag": "quick", "checked_by": "owner"},  # the owner's parentless story is a quick task
```

**#40** `v8/src/edp8/delivery.py:268-276`
```python
            fyi_to = board.recovery_seat(m.ticket_id, exclude={to, actor_id})
            if fyi_to:
                broker_adapter.publish("board", fyi_to, "fyi",
                                       {"ticket_id": m.ticket_id,
                                        "text": f"{m.kind.value} from {actor_id} awaits CLOSED seat {to} "
                                                f"on {m.ticket_id} — it reads its inbox first thing on its "
                                                f"next shell; spawn(participant_id={to!r}) revives it "
                                                f"without reassigning the ticket",
                                        "board_msg_id": m.id, "closed_seat": to})
```

**#41** `v8/src/edp8/delivery.py:40-44`
```python
    if not plan and ev.kind == EventKind.message_sent \
            and ev.data.get("kind") in (MessageKind.question, MessageKind.deviation):
        owner = board.epic_owner(ev.subject_id)
        if owner:
            plan.append((owner, [Reason.recovery]))
```

## Notes
- The board-opened acceptance gate (#10) gets no broker wake (#43); the owner sees it via the feed and Needs you only.
- Token spend with no new messages: #60f (parked heartbeat, 1800 s) and #52 (feed-driver heartbeat, 1800 s).
- Off by default: #48 RSI, #49 Plane, #51 Slack bridge, hourly upload sweep in #47.
