# Design doc template (architect, per work_type)

## Purpose
The shape of every design doc. A design is the implementation spec seats build from, and `doc_read(id)` hands them
its first page and heading map first. So the decisions go on page one and the detail goes in Topics. The general
shape and why it pays are in the /doc-write skill.

## Key points
- Write it summary-first: `# <title>` → `## Purpose` → `## Key decisions` → `## Keywords` → `## Outline` → `## Topics`.
- `## Key decisions` is numbered and self-contained. Every ruling, scope limit and owner answer a seat must follow
  sits there, citing the topic that holds the detail. A folded-in owner answer changes this section, not only a topic.
- The ten Topics below are mandatory. Omit content only when a topic genuinely does not apply to the work_type, and
  say so explicitly rather than leaving it blank.
- Audit the completed draft with /ocak before presenting it for sign-off on the board. The owner's design_signoff
  answer is the sign-off, recorded on the epic thread.

## Keywords
design doc, template, key decisions, words, problem statement, work breakdown, acceptance criteria, risks, sizing

## Outline
- Topics 1-3 (Words, Problem statement, Problem types): what is asked, verbatim and in the architect's words.
- Topics 4-5 (Solution outline, Work breakdown): what gets built, and by which seat.
- Topics 6-7 (Communication plan, Knowledge domains): who decides what, and which smes are needed.
- Topics 8-10 (Acceptance criteria, Risks, Sizing note): how done is checked, what could go wrong, honest size.

## Topics

### 1. Words (verbatim)
The owner's request, unedited, in full.

### 2. Problem statement
What is actually being asked for, in the architect's own words, distinguishing the real goal from any proxy goal in
the words.

### 3. Problem types present
For example geometry + rendering + tooling; bug + regression; research + integration. Naming the types drives which
topics below apply.

### 4. Solution outline
By work_type:
- feature/chore: HLD (components, data flow) and LLD (interfaces, key algorithms) as the work needs.
- bug: impact statement and the likely fix(es), ranked.
- rnd: the R&D paths to try and how each is judged.
- creative: the look spec (references, constraints, what "done" looks like).

### 5. Work breakdown
Stories, each with who does what (engineer / adversary / codex seat for creative-UI / human teammate) and which
strategy_hl/strategy_ll it uses. The last story is always the adversarial review.

### 6. Communication plan
Which decisions go to the owner, which to the architect, which the engineer owns outright. Prevents both silent
overreach and needless escalation.

### 7. Knowledge domains needed
Names the sme(s) to invoke, domain or craft, and what each must cover (becomes the criteria on their knowledge
ticket).

### 8. Acceptance criteria for the epic
Checkable: `check` is command | path | look | verdict for each; who checks it (qa/owner). A story that changes UI (v8/web, vscode-ext, desktop) gets a `look` criterion, checked by qa, naming its screens; qa walks them with the browser tool.

### 9. Risks
Named, with the mitigation or the accepted exposure.

### 10. Sizing note
Honest: one story when the work fits one sitting; do not split for the sake of splitting, and do not under-size real
work into one story either.

Base concerns to fold into the topics above, not skipped: scope/done, workspace, cost/time, tech preferences,
actors/data/sensitivity, deliverable form.
