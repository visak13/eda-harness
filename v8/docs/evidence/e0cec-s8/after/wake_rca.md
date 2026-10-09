# Why monitor wakes end with no action (owner m-6f53271ba1)

Read-only analysis of the seat transcripts with `wake_costs.parse_session`, classified by the first wake line of
each turn. Windows match `after_table.py`. A turn's copy in a second transcript file is counted once.

## What the feed driver prints (v8/src/edp8/feed_driver.py)

| Line | When | Dedupe |
|---|---|---|
| `{"listening": …}` | on every driver start (`run()`, l.347-355) | none: the same fixed text `subscribe()` already returned |
| `{"event": …}` | each board event the board deems relevant (`/v1/feed`, l.293-295) | server-side relevance only |
| `{"broker_msg": …}` | each broker message for the seat (l.316-318) | none, and no check against events already printed |
| `{"heartbeat": …}` | every `EDP8_HEARTBEAT_S` (1800 s) | sleeps a full interval before its first tick (l.247-252) |
| `{"error": …}` | every failed reconnect, backoff 1 s to 30 s (l.333-336, 373-376) | none |

## No-action monitor turns by what woke the seat

| Class | Before: share of no-action | After: share of no-action | Information? |
|---|---|---|---|
| A. `listening` banner after a Monitor re-arm | 24.2% | 64.4% | none: fixed text |
| C. driver `{"error"}` retry lines | 9.7% | 0% | none: one line per retry |
| D. broker copy of an event already delivered | 6.2% | 5.1% | none |
| E. broker `progress` the feed filters on purpose | 4.7% | 0% | near none |
| G. answers, notes, statuses with nothing to do | 25.4% | 8.5% | yes, low value |
| H. lifecycle events (status, criteria, docs) | 23.3% | 1.7% | yes, mostly routine |
| I. `ask_judged` / `ask_created` | 0% | 20.3% | yes; about half are verdict `met` |
| other (expiry notices, broker fyi, other Monitors) | 6.5% | 0% | |
| **No-action share of monitor turns** | **46.3%** (1,265 of 2,730) | **55.7%** (59 of 106) | |

## Root causes

1. **RC1, the re-arm cycle.** The Monitor stops after 30 minutes; the re-armed driver prints the banner again. Each
   idle half hour costs a re-arm turn and a banner turn. The AFTER window is two mostly idle architects, so this
   cycle is 76 of its 106 monitor turns. Nothing new started waking seats; the mix changed.
2. **RC2, two delivery planes with no correlation.** A message addressed to a seat is emitted as a board event
   (`service.py:2149`) and published to the broker (`delivery.py:246-251`). The broker body carries
   `board_msg_id` equal to the event's `data.message`, but the driver never compares them. Of 1,907 pairs before,
   69% landed in one notification, 25% in the same turn, and 6.4% (123) woke the seat twice.
3. **RC3, the broker status path skips the feed's filter.** `record_status` always adds the resident architect
   (`board.py:3330`) and publishes `progress` (`delivery.py:307-310`), while the feed pages the architect only for
   blocked/failed/deferred (`board.py:3911`).
4. **RC4, every reconnect retry is a wake** (feed_driver.py:333-336, 373-376).
5. **RC5, routine information:** lifecycle events, acknowledgements, routine statuses and `ask_judged` met.

Side defects: the driver heartbeat never fires (its first tick is due exactly when the 30-minute Monitor kills the
driver), and a re-armed driver starts at "now" on both planes, so anything posted between expiry and re-arm is
never delivered.

## Fix options (not built)

| Fix | No-action turns removed (before / after) |
|---|---|
| Print the banner only on the first start (or to stderr); `subscribe()` already returns it | 24.2% / 64.4% |
| One error line per outage, then "recovered" | 9.7% / 0% |
| Drop a `broker_msg` whose `board_msg_id` was already printed as an event | 6.2% / 5.1% |
| Broker status copies follow the feed's relevance rule | 4.7% / 0% |
| Don't page the architect for `ask_judged` met | about 10% of after |
| Heartbeat first tick inside the Monitor lifetime; resume from saved cursors on re-arm | correctness, not turns |

The first four together remove about 45% of the before no-action turns and about 69% of the after ones.
