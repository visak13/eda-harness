# v7 commands retired (2026-08-24)

The v7 role commands (/neuron, /agentic-plan, /worker, /reviewer, /curiosity, /specialist,
/acceptor) are retired; the files live in `commands-v7-retired/`. The framework is now v8:

- agent home: `../../v8` — cards in `v8/.claude/commands/` (/owner /coordinator /architect
  /sme /engineer /reviewer /qa), skills in `v8/.claude/skills/`, guides in `v8/guides/`
- start/stop: `start-v8.bat` / `stop-v8.bat` at the repo root (board :9400 + web UI at /ui,
  pool :9301 pinned to v8)
- spec + build log: `claude/docs/design/FRAMEWORK-V8-DRAFT-v2.md`, `V8-DELIVERY-PLAN.md`

To temporarily run the old fleet, move the files back and use start-stack-claude.bat.
