# Contextual revision for architect inspection — not approved

Read exact epic/review/Usage renders from design-8434ebac74 before preparing this small sample. Owner m-bf2f47dbd2 rejects prior standalone family; m-027bb87c0d asks architect+engineer to finalize together before bringing it back. No new generated sheet, no production integration.

## What went wrong
The earlier contact sheet optimized family coverage rather than the actual board. Arbitrary robot costumes replaced established identity character; tray/flag/ruler/clock/half-circle metaphors were assigned without checking related controls. Generic symbols looked tidy in a grid but did not explain what their destinations held. Tiny details and extra badges made meaning worse, not better. Size/security checks could not answer these design questions.

## This limited proposal
Keep the exact epic/review composition, labels, typography, existing human and architect avatars and restrained flat surfaces. Do not compete with conversation. Shape supplies a familiar cue; the label names the board concept. Icons cannot independently encode project-specific vocabulary like “Epic”; do not promise an unfamiliar symbol can replace that word.

|Placement|Treatment and meaning|Why different from rejected family|
|---|---|---|
|Epics rail|Overlapping titled work cards + Epics|Collection of project records, not warning list or completed checklist. Work uses a single task list below.|
|Work contextual link|Single task list + Work|List of actionable child work; not inbox tray, archive box or completion claim.|
|Design contextual link/viewer breadcrumb|Keep reference folded document with text lines, v3/review-requested words|The thing opened is the actual versioned document. Do not use a ruler for the concept of design or an eye that means show/hide.|
|Files & evidence|Folder + words|Collected linked files/evidence, distinct from Attach (paperclip adds a file to a message).|
|History|Backward clock + History|Earlier events, not work actively running.|
|In progress status|Circle with play/start triangle + words|Work started; no implied 50% complete and no clock confused with History. No animation.|
|Review requested attention|Conversation bubble with lines + words|An explicit request for feedback, not generic hazard/blocked warning. This is attention, NOT automatic mapping of every in_review status.|
|Reply / Attach|Keep reference bent reply arrow / paperclip beside words|Established action semantics. No visual novelty needed.|
|Approve design|Keep simple check beside exact action words|Affirmative review decision, not a completion badge for the whole epic. Request changes stays text so it cannot resemble an approving check.|
|Identities|Keep existing human and architect avatar exports|Character comes from established identity illustrations. Bot refresh is deferred until contextual language accepted, not silently dropped from final scope.|

No new state mappings beyond representative in-progress/attention treatment. Other states remain outside this sample; don't proliferate metaphors before alignment. Controls remain 20px, status marks 18px as the exact baseline. Principal target sizing and final 16/18/24/theme verification remain production obligations, not promised by this reference.

## Review questions for architect (before owner)
- Are Epics collection and Work task list now distinct in this exact composition?
- Does the status/History distinction reduce ambiguity? Would an unfilled started-work ring be clearer than play, without implying playback? Keep literal label either way.
- Does review-request bubble imply feedback without conflating it with the document link or blocked warning?
- Is preserving existing avatars the right identity continuity anchor? No arbitrary role mascots in this proposal.

`build_sample.py` creates sample.html from original static HTML; source refs preserved. The vectors here are hand-authored/refined standard geometry, NOT generated SVG. Actual previous image_gen source remains rejected history; no attempt to relabel it as owner-approved. New generation, if required after contextual direction is agreed, must use the accepted full composition as its anchor and preserve exact provenance.
