---
name: doc-read
description: Trigger before you read a board doc (doc_read), especially a design or strategy linked to your ticket.
---
<!-- roles: architect, engineer, qa, sme, adversary, doctor -->

# /doc-read

## Purpose
Board docs are written top-to-bottom: the first page is the writer's summary, and the rest is detail. `doc_read(id)`
gives you that first page (~8 KB), a map of every section with its size, and how to read on. You decide what else
you need.

## Key points
- Read the first page first. Its Purpose, key slot (Key decisions / Rules / Key findings / Key points), Keywords and
  Outline tell you what the doc holds and where.
- Then choose: read the sections your work touches (`doc_read(id, section=<a heading from the map>)`), or read on
  page by page (`offset` from the continuation) when you need the whole doc. Both are fine; it is your judgement.
- Your ticket's description may name the sections written for it. Start there, but the design's Key decisions apply
  to every story.
- The same doc id is the same doc. A design linked to your story is usually the epic's design.
- If a reply says you already hold part of what you asked for, it serves the rest. Ask again with the offset it names
  if you have lost that text.
- A doc marked `layout=legacy` was written before this shape; its first page may not hold the summary, so read on.

## Keywords
read, head, first page, summary, map, section, page, offset, continuation, design, strategy, legacy

## Outline
- What the first read returns.
- Choosing sections or reading on.
- Your ticket's named sections.
- Already-read text.
