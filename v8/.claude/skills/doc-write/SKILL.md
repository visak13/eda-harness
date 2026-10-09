---
name: doc-write
description: Trigger before you write or rewrite a board doc (doc_create, doc_update, doc_edit) of any type.
---
<!-- roles: architect, engineer, qa, sme, adversary -->

# /doc-write

## Purpose
Decide small or large before you write, by what the doc is. A small doc makes one point (a note, an answer, a short
report): write plain prose. A large doc has several parts that readers pick from (a design, a strategy, a domain guide):
open with its summary. Then edit it in place; do not rewrite it.

## Key points
- **Small (one point) = plain prose.** No template, no sections you do not need. One H1 title, then the text.
- **Large (several parts) = summary first.** `doc_read(id)` returns the first page (~8 KB), a heading map with each
  section's size, and a continuation. **The full summary is in the first page**: what a reader must do, must not do, or
  must know to decide whether to read on. A rule that lives only below page one will be missed.
- Large shape (guidance, not a format check; no write is refused for its layout): title as the only H1, then `## Purpose`,
  the key slot for your doc type, `## Keywords`, `## Outline`, and `## Topics` with a `###` per topic.
- Key slot by type: design = `## Key decisions`; strategy_hl, strategy_ll and domain = `## Rules` (numbered MUST
  lines, each tagged [required], [expected] or [preferred]); report = `## Key findings`; note = `## Key points`.
- **Edit, don't rewrite.** (not sme) Change a doc the way you use the Edit tool: `doc_edit(id, old_string,
  new_string)`, `replace_all=true` for every occurrence, or `edits=[{old_string, new_string}, ...]` for several. It
  uses the version you last read; pass `expected_version` only to pin another. An sme seat has only `doc_update`.
- A doc you read is also on disk, read-only, at `docs/<scope>/<id>.md` in the agent home: Read, grep and sed it there.
  (not sme) Every change still goes through `doc_edit`; a native Edit on that file fails.
  A native Read pins no version: after reading the file, pass `expected_version` from its front-matter `version:`.
- Deviate from the large shape only with a `## Reading strategy` first, saying how to read the doc instead.

## Keywords
small doc, large doc, plain prose, summary first, edit don't rewrite, doc_edit, old_string, replace_all, first page,
heading map, section read, key decisions, rules, key findings, mirror, legacy

## Outline
- Why: what the head-first read does and what a buried rule costs.
- The shape: each slot of a large doc, and what goes in it.
- Old docs: the legacy layout flag.
- Revising: edit a section instead of resending the body.

## Topics

### Why
Every seat that opens a large doc pays for what it reads, on every read. The head read gives them page one and the map.
They choose sections from the map by heading and size, so headings must say what the section holds, not "Misc".
A section read returns that section's own text, up to its first subsection, plus the subsections' headings and
sizes; `include_children=true` returns the whole subtree. Put a section's point in its own text, before its
subsections. `section=` takes a heading, a near match of one, or a number (`3`, `3.2`); an ambiguous name answers with
the candidates.
Search (`find`) indexes each section separately and returns the heading, so a clear heading also makes the section
findable.

### The shape
- **`# Title`**: the only H1. A second H1 breaks section reads: a section runs to the next heading of the same or
  higher level.
- **`## Purpose`**: why the doc exists and what decision or work it serves. Short, but no token limit.
- **Key slot** (named per type, above): the summary a reader acts on. Self-contained lines; cite the topic that holds
  the detail (`→ §Topic`). Overrides, exceptions, superseded rules and precedence go here too, with what they replace.
- **`## Keywords`**: the words someone would search for, including synonyms the body does not use.
- **`## Outline`**: one line per topic: what it is and why it matters.
- **`## Topics`**: a `###` per topic, with the detail, evidence and examples.

### Old docs
Docs written before the summary-first change carry `layout=legacy`; a read says so and nothing more. Read them by the
heading map and edit them in place. Rewriting a whole body costs far more than the edit; do it only when the doc's
structure is itself the problem, and then pass `layout="summary_first"` to `doc_update` to clear the flag.

### Revising
Read the section (`doc_read(id, section=<heading>)`), then (not sme) `doc_edit(id, old_string=…, new_string=…)`; an
sme seat sends the whole body with `doc_update`. A changed obligation must also change the key slot of a large doc,
so the summary stays the truth.
