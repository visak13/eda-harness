## The seat law (spawned shells)

There is no human on this window: never prompt the user, never render a
choice menu, never narrate an introduction, never invent work. Every
need routes over the broker — mechanics of your task to the shell that
dispatched you (`ask_above`), goal/scope/decision-class questions to
the neuron (`ask_above(question=…, audience="neuron")`). Send, end the
turn; your subscription wakes you on the answer — never poll in a
foreground loop. On a `steer`: `notify_above(kind="steer_ack",
body={"restatement": …, "steer_msg_id": …})` BEFORE acting on it.
Epoch discipline: echo the epoch from your last context push on
interactive turns; on cron ticks `check_inbox(ack_epoch=<it>)` — a
stale echo hands back a `reground` block; execute it VERBATIM.

**Everything you arm, you disarm — the close mirrors the open.** Before
`pool_close_self`: `CronDelete` every cron you created and `TaskStop`
every Monitor you armed (a dead subscription's driver is a leaked
process; an orphan cron wakes a corpse). One resource, one owner, one
close. Parking is the exception by design: a parked shell's wiring dies
with the process and the resume rewire re-arms it — never re-arm from
memory. If you armed nothing, you disarm nothing; never blanket-kill.
