/**
 * edp-guard — the opencode analog of the Claude-side PreToolUse guard hook.
 *
 * Converts OPENCODE-BEHAVIOR-POLICY.md from advisory prose into ENFORCEMENT:
 * a fleet shell (any model, any prompt-injection) cannot nuke the stack or
 * the driver state, because the harness refuses the tool call before it runs.
 *
 * Blocks, via `tool.execute.before` (throw = the call never executes):
 *   1. bash commands that KILL protected stack processes — a kill verb
 *      combined with any protected token (broker :9300, pool :9301, the
 *      neuron seat :4747, stack module names, opencode serve).
 *   2. bash commands that DELETE/TRUNCATE protected state files
 *      (pool-state.json, .opencode/drivers/, .fleet-data store).
 *   3. write/edit tool calls targeting those same protected files.
 *
 * Deliberately NARROW: normal work (running tests, killing a test's own
 * child process, editing recipe artifacts through MCP) never matches.
 * The deny text tells the model WHY and what to do instead, so a
 * legitimate need surfaces as an ask_above instead of a silent workaround.
 */
import type { Plugin } from "@opencode-ai/plugin"

const KILL_VERBS =
  /\b(taskkill|stop-process|pskill|tskill|kill(?:all)?|wmic\s+process[^\n]*(terminate|delete))\b/i

const PROTECTED_PROC_TOKENS =
  /(9300|9301|4747|edp[-_]broker|edp[-_]pool|edp[-_]?claude\.mcp|stack_launcher|opencode(\.exe)?\s+(serve|attach)|edp-neuron-server)/i

const DESTROY_VERBS =
  /\b(rm|del|erase|remove-item|rmdir|rd|clear-content|mklink|move|mv|ren(ame)?)\b/i

const PROTECTED_PATHS =
  /(pool-state\.json|\.opencode[\\/](drivers|plugins)[\\/]|\.fleet-data[\\/]opencode|registrations\.json|engine\.log)/i

const DENY = (what: string) =>
  `EDP GUARD: refused — this call would ${what}. The stack (broker :9300, ` +
  `pool :9301, neuron seat :4747) and driver state are operator-owned; no ` +
  `fleet shell may modify them. If you believe this is genuinely required, ` +
  `stop and raise it via ask_above / notify_above instead of retrying.`

export const EdpGuard: Plugin = async () => {
  return {
    "tool.execute.before": async (input, output) => {
      if (input.tool === "bash") {
        const cmd: string = String(output?.args?.command ?? "")
        if (KILL_VERBS.test(cmd) && PROTECTED_PROC_TOKENS.test(cmd)) {
          throw new Error(DENY("kill a protected stack process"))
        }
        if (DESTROY_VERBS.test(cmd) && PROTECTED_PATHS.test(cmd)) {
          throw new Error(DENY("destroy protected harness state"))
        }
        if (/>\s*\S*?(pool-state\.json|registrations\.json)/i.test(cmd)) {
          throw new Error(DENY("overwrite protected harness state"))
        }
      }
      if (input.tool === "write" || input.tool === "edit") {
        const p: string = String(
          output?.args?.filePath ?? output?.args?.file_path ?? output?.args?.path ?? "",
        )
        if (PROTECTED_PATHS.test(p)) {
          throw new Error(DENY(`modify protected harness file ${p}`))
        }
      }
    },
  }
}
