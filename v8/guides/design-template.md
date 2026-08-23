# Design doc template (architect, per work_type)

Every section below is mandatory in a design doc; omit content only when a section
genuinely does not apply to the work_type, and say so explicitly rather than leaving it
blank.

1. **Words (verbatim)** — the owner's request, unedited, in full.
2. **Problem statement** — what is actually being asked for, in the architect's own words,
   distinguishing the real goal from any proxy goal in the words.
3. **Problem types present** — e.g. geometry + rendering + tooling; bug + regression;
   research + integration. Naming the types drives which sections below apply.
4. **Solution outline** — by work_type:
   - feature/chore: HLD (components, data flow) and LLD (interfaces, key algorithms) as
     the work needs.
   - bug: impact statement and the likely fix(es), ranked.
   - rnd: the R&D paths to try and how each is judged.
   - creative: the look spec (references, constraints, what "done" looks like).
5. **Work breakdown** — stories, each with who does what (engineer / reviewer / consultant
   for creative-UI / human teammate) and which strategy_hl/strategy_ll it uses. The last
   story is always the adversarial review.
6. **Communication plan** — which decisions go to the owner, which to the architect, which
   the engineer owns outright. Prevents both silent overreach and needless escalation.
7. **Knowledge domains needed** — names the sme(s) to invoke, domain or craft, and what
   each must cover (becomes the criteria on their knowledge ticket).
8. **Acceptance criteria for the epic** — checkable: `check` is command | path | look |
   verdict for each; who checks it (reviewer/qa/owner).
9. **Risks** — named, with the mitigation or the accepted exposure.
10. **Sizing note** — honest: one story when the work fits one sitting; do not split for
    the sake of splitting, and do not under-size real work into one story either.

Base concerns to fold into the sections above, not skipped: scope/done, workspace, cost/
time, tech preferences, actors/data/sensitivity, deliverable form. Audit the completed
draft with /ocak before presenting it for sign-off (plan-mode ExitPlanMode = sign-off,
recorded on the epic thread).
