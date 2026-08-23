# strategy_ll: python craft

**Intent + why.** Craft rules exist so the code is safe to hand to a reviewer who wasn't
there and to a future engineer who has no memory of this session — not as style
preference. Each item below is intent + why + a concrete example, so a lower-tier
executing model can adapt it rather than pattern-match a rule it doesn't understand.

**Structure** — keep one responsibility per module/function so a change in one concern
doesn't ripple; a reviewer should be able to verify a function by reading only its body and
signature. Example: a `parse_ticket()` function does parsing only; it does not also write
the result to disk.

**Errors** — fail loud and typed at the boundary where the failure is first knowable, so
the caller gets a clear signal instead of a downstream `AttributeError`. Example: raise
`TicketNotFoundError` from the lookup, not `None` silently swallowed three calls later.

**Logging** — log at the decision points a maintainer would want to reconstruct without a
debugger (what was chosen and why), not every line executed. Example: log the strategy_hl
chosen and why, not each loop iteration.

**Resources** — anything opened is closed on every exit path, so a long-running shell
doesn't leak handles across many tickets. Example: use a context manager (`with open(...)`)
rather than manual `close()` calls that skip on an exception path.

**Tests** — a test exists for every criterion's `check: command`, runnable by the reviewer
without special setup, so "it works" is re-checkable rather than a claim. Example: a test
that reproduces the bug's repro from the diagnose strategy, asserting it no longer fails.

**Docs** — a docstring states what the function does and why it exists if that's not
obvious from the name, so /learn candidates are easy to spot later. Example: note *why* a
retry uses exponential backoff, not just that it does.

**Output contracts** — structured output so the caller can parse it reliably: pydantic
where the model supports structured output, plain JSON (with a documented shape) where it
does not. Example: an engineer's report section is a typed dict either way — pydantic
serializes to it when available, hand-built JSON matches the same shape otherwise.
