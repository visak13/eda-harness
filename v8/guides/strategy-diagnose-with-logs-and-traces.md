# strategy_hl: diagnose-with-logs-and-traces

**Intent + why.** A bug's fix is only as good as the diagnosis behind it; guessing at a fix
before understanding the failure produces instance-patches that recur. This strategy forces
evidence before a fix is proposed.

**When it applies.** work_type=bug, or any story that starts from "X is broken/wrong" with
an unclear cause.

**Phases**
1. Reproduce — get the failure to happen on demand; if it cannot be reproduced, say so and
   treat "make it reproducible" as the actual first deliverable.
2. Trace — add or read logs/traces until the failure's proximate cause is visible, not
   inferred. Prefer reading existing instrumentation before adding new.
3. Root-cause — classify per /ocak's Comprehension/Awareness questions: symptom or root
   cause; instance-fix or class-fix. Name the sibling cases an instance-fix will not cover.
4. Fix and verify — the smallest change that addresses the classified cause; re-run the
   original repro as the primary criterion evidence.

**Exit condition.** The repro no longer fails, the root cause is stated in the report doc
(not just "fixed"), and the fix's class (instance vs. class) is recorded.

**Typical gates.** None by default; a fix that touches shared/critical code may warrant a
reviewer's early look before wider changes.
