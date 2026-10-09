# S17 Summary-first docs: evidence

Story s-800c57b900, design-f39cf0db7d v5, branch e0cec/S17. Every check below can be re-run cold from `v8/` with
`PYTHONPATH=src python -m pytest -q -p no:cacheprovider <file>` (only the named files; never the full suite).

## c-698411be67 Legacy flag

| Check | Where |
|---|---|
| Migration flags every pre-existing doc `legacy`; new docs get `summary_first` | `tests/test_s17_summary_first.py::test_migration_flags_every_existing_doc_legacy_and_new_docs_summary_first` |
| A legacy doc's read carries the warning line | `test_agent_read_paths_show_the_warning_and_never_the_whole_body`, `tests/test_agent_contracts_s7.py::test_legacy_document_defaults` |
| No code parses old bodies to set the flag | `test_no_code_parses_bodies_to_set_the_flag` |
| A rewrite clears it; layout never refuses a write | `test_rewrite_clears_the_flag_and_layout_is_never_a_reason_to_refuse` |

## c-1da6f3d0a4 Head-first on every read path (ruling m-c6cdb0602c)

| Path | Test |
|---|---|
| MCP doc_read(id): first page + heading map with sizes + continuation (page, section) | `test_doc_read_defaults_to_the_head_with_map_and_continuation`, `test_a_short_doc_comes_back_whole_without_a_map` |
| MCP doc_read has no whole-body option; HTTP keeps all=true | `test_mcp_doc_read_has_no_whole_body_and_http_all_true_does`, `test_http_get_is_head_first_and_all_true_is_the_full_record` |
| Section read: own text + child map; include_children for the subtree | `test_a_parent_section_read_returns_its_own_text_and_the_child_map` |
| context, ticket_read, find: warning, never the whole body | `test_agent_read_paths_show_the_warning_and_never_the_whole_body` |
| lookup/recall excerpts quote the hit section | `tests/test_knowledge.py` (S17 section-first excerpt test) |
| Write echoes/read_ref name the head read; the head + continuation loses nothing | `tests/test_s23_t6_findings.py` (`_paged_body`) |
| Web view: banner + section map, body via all=true | `web/src/api/s17-docs.test.ts` (`vitest run`), `test_human_doc_view_has_banner_map_and_whole_body` |
| VS Code reader: banner + section sizes, body via all=true | `vscode-ext/edp-code/test/s17-docs.test.ts` |

## c-b5fb0b2752 Section-level find

- `test_find_hits_a_term_past_2000_chars_with_its_section`: a term only after char 2,000 is found, and the hit names its section.
- `test_doc_edit_moves_the_section_hit`, `test_an_old_fts_table_is_rebuilt_by_section`, `test_semantic_index_units_are_sections_within_the_embed_window`.
- Docs without headings fall back to paragraph units (`doc_tools.doc_units`). Every unit is ≤1,500 chars, under the embedder's 2,000-char window.

## c-9cbd15039e assemble_ruleset removed

`git grep -c assemble_ruleset -- . ':!v8/docs/evidence' ':!v8/tests/data/s23_tool_facts_before.json' ':!CHANGELOG.md'`
prints nothing (exit 1). The excluded paths are the changelog and the frozen pre-S23 tool facts (history). Tests:
`test_ruleset_tool_is_gone`, `tests/test_s9_tool_matrix.py`, `tests/test_tool_info_parity.py`.

## c-676a1c364f doc-write skill

- `.claude/skills/doc-write/SKILL.md` teaches the summary-first shape and explains why.
- doc_create, doc_edit and doc_update name the skill in one terse clause, "(/doc-write)", and their write hints repeat it: `test_doc_tools_name_the_skill_in_one_line`, `tests/test_skill_tool_scope.py`.
- design-template.md, sme.md, the harvest SKILL.md and architect.md use the shape.
- Nothing rejects a write for its layout (`test_rewrite_clears_the_flag_and_layout_is_never_a_reason_to_refuse`).

## c-e8ecddefcf Cost before/after

The replay is `scripts/s17_cost_replay.py`; its outputs are `before.json` and `after.json` here. The pyr reads add the
section reads a seat needs (ruling m-8c4f0d64cb).

| Set | Before | After: head | After: sections | After: total | Change |
|---|---:|---:|---:|---:|---:|
| pyr reads | 1,066,407 | 471,902 | 459,394 | 931,296 | −12.7% (target −40%: **missed**) |
| pyr writes | 266,738 | 137,769 | — | 137,769 | −48.4% |
| real-doc reads | 63,435 | 27,733 | 0 | 27,733 | −56.3% |
| real-doc writes | 61,165 | 1,161 | — | 1,161 | −98.1% |

The live completeness run (codex gpt-6-astra, 6 stories, graded by claude-opus-5-5) is reported on the ticket thread.
That run is the after-number m-8c4f0d64cb names.
