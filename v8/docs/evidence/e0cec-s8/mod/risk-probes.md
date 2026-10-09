# Risk probes for the wake mod (s-e60c3d42ad, c-918f247845)

Build: Claude Code 2.1.293, Windows 11, run 2026-10-09 from the pool-launched engineer seat 01d58a79-04fb-425b-a706-1ec050e66d01
(env: CLAUDE_CODE_CHILD_SESSION=1, EDP_SKIP_PERMISSIONS=1, CLAUDE_CONFIG_DIR=the pool's).

## Risk 1: does `$.prompt.submit` start a turn in a pool-launched seat? YES
- Mod `wake-probe` (`session.start` -> `$.process.spawn` of a child that prints `probe-line-1` after 15 s ->
  `$.prompt.submit({ text })`), loaded by hot reload in the seat itself.
- Result: the seat received a new turn, framed by the engine as "The wake-probe plugin sent a message: WAKE-PROBE: …",
  with no human input in between. Board record: m-799ab09b71.
- `claude plugin validate` on the mod: passes; it reports `hooks: session.start`, `calls: $.process.spawn, $.prompt.submit`.

## Risk 2: how do seats load the mod? `CLAUDE_CODE_PLUGIN_DIRS` in the seat's launch environment
Mod `load-probe` writes `marker-seat.txt` / `marker-plain.txt` at `session.start`, from `$.env.get('EDP8_PARTICIPANT')`.

| load route (all `claude -p`, claude-haiku-5-5) | loaded? |
| --- | --- |
| `CLAUDE_CODE_PLUGIN_DIRS=<abs dir>` in the process env, `EDP8_PARTICIPANT` set | yes, `loaded who=engineer.probe` |
| same, `EDP8_PARTICIPANT` unset | yes, mod runs, sees `who=unset` (the gate input works) |
| `env.CLAUDE_CODE_PLUGIN_DIRS` inside a `--settings` file | yes |
| `env.CLAUDE_CODE_PLUGIN_DIRS` in the cwd's `.claude/settings.json`, relative path | no |
| same, absolute path | no |

Chosen: set `CLAUDE_CODE_PLUGIN_DIRS=<agent home>/.claude/mods` in the pool's launch env (`spawner.py`, next to
`lean_boot.apply_env`). The agent home does not need a settings file, and a plugin install is not used. Reaching every
seat takes one pool restart by the owner (a seat never restarts the pool); seats spawned before it keep their old path.
The hot-reload dev-mods folder is not a production path: it needs a per-session owner answer.
