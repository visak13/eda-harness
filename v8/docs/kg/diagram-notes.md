These diagrams describe the supplied working-tree implementation, using design-d2c4f39fc6.md sections 2–4 for context.

Visual acceptance bars: exact 2000 × 1400 and 2000 × 1200 PNGs; minimum 26 px type (16.9 px at 1300 px display width); Segoe UI; dark labels on light backgrounds; arrows must not run through labels; 2× rendering downsampled for smooth type. The render script and Mermaid source are editable.

Implementation details that affect the diagrams:

- schemas.py defines three content types (Decision, Claim, Lesson) and the KgLink connection type. Scope accepts an epic or ticket ID; knowledge.py resolves the ticket to its epic for isolation.
- board.py record_decision writes decision → scope (decides), decision → old decision (replaces), and decision → source (came_from). record_claim writes claim → scope (part_of), claim → source (came_from), and claim → evidence (proves). record_lesson writes lesson → evidence (learned_from). The diagram shows representative links rather than every possible link. must_follow is a supported stored link; the displayed decision → reference is an illustrative relation, not a claim that record_decision automatically writes it. Grey part_of/touches are classified as derived per the design; current record_claim explicitly persists part_of.
- knowledge.py _always_include selects binding and must-follow decisions regardless of the question. As of 736d248 (architect ruling F6, 2026-09-23) binding text is never cut: the always section takes what binding needs, the ranked section absorbs the rest, and the receipt reports always_bytes. The 2,000-byte trim shown in kg-lookup.png step 2 and its footer line are historical (pre-736d248) and should be removed at the next re-render.
- Search combines keyword and optional meaning rankings with RRF. Each main search leg contributes 8–24 candidates according to epic size, rather than the design's top five. Lessons also have their own search pool. If meaning search is unavailable, keyword search still works.
- _adjacency walks connections in both directions but skips came_from and replaces. A separate shared-source lookup can add related claims/decisions. Replaced decisions can appear as inline history, not active rules.
- Ranking favors direct matches over walk-only records. Scores use match/link weight, age, lesson usefulness and record-type weight. Weak matches and inactive records are excluded; old records linked to changed files can remain with stale labels.
- MAX_BYTES=16000 (was 8000; owner ruling m-5e2ff72e19) counts serialized entries. Lessons have up to 1500 bytes and three entries within that total. Answers and optional source excerpts use remaining space. The full response also includes body text and a receipt; 16000 is not the size of the whole response envelope.
- MAX_RECORDS=40 is still reported in the receipt, but the current packing loop enforces the byte cap, not a 40-record cutoff. The diagram avoids presenting that obsolete limit as active.
- “About six records instead of a 400-message thread” is the user's requested explanatory scale, not an observed lookup measurement. It is labelled as an illustration.
- The receipt lists budget cuts by type, up to 20 IDs per type, trimmed binding IDs, weak-hit counts/IDs and a fetch instruction. It does not enumerate every omitted lesson or source excerpt.

Re-render with the installed Pillow interpreter:

    C:/Projects/Learning/eda-base3/v8/.venv/Scripts/python.exe render_kg.py
