/**
 * edp-drivers — native Monitor + Cron toolset for the opencode harness.
 *
 * Two halves, one file:
 *  - TOOLS (loaded in every opencode process): edp_cron_create/list/delete,
 *    edp_monitor_arm/list/disarm, edp_driver_status. A tool call only writes
 *    a registration row — durable JSON, zero background work.
 *  - ENGINE (runs ONLY when EDP_DRIVER_HOST=1, i.e. inside the seat's
 *    `opencode serve`): timers + file tails + broker SSE, all plain JS
 *    (zero tokens while idle). A trigger fires exactly ONE turn into the
 *    registered session via POST /session/:id/prompt_async, coalesced on
 *    the session.idle bus event — never a stack of queued prompts.
 *
 * Seat gate is structural: the engine lives inside the seat's server, so
 * server closed ⇒ engine gone ⇒ driving holds.
 */
import { type Plugin, tool } from "@opencode-ai/plugin"
import * as fs from "node:fs"
import * as path from "node:path"

// ---------------------------------------------------------------- store ---

type Reg = {
  id: string
  kind: "cron" | "monitor"
  name: string
  sessionID: string
  agent?: string
  prompt: string
  // cron
  intervalSeconds?: number
  lastFiredAt?: number
  // monitor
  file?: string
  brokerInbox?: string
  once?: boolean
  createdAt: number
}

const DRIVER_DIR = path.join(__dirname, "..", "drivers")
const REG_FILE = path.join(DRIVER_DIR, "registrations.json")

function loadRows(): Reg[] {
  try {
    return JSON.parse(fs.readFileSync(REG_FILE, "utf8")) as Reg[]
  } catch {
    return []
  }
}

function saveRows(rows: Reg[]): void {
  fs.mkdirSync(DRIVER_DIR, { recursive: true })
  const tmp = REG_FILE + ".tmp"
  fs.writeFileSync(tmp, JSON.stringify(rows, null, 2), "utf8")
  fs.renameSync(tmp, REG_FILE)
}

function mutate(fn: (rows: Reg[]) => Reg[]): Reg[] {
  const rows = fn(loadRows())
  saveRows(rows)
  return rows
}

const newId = () => `drv-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`

function fmtRow(r: Reg): string {
  const src =
    r.kind === "cron"
      ? `every ${r.intervalSeconds}s`
      : r.file
        ? `file:${r.file}`
        : `broker:${r.brokerInbox}`
  return `[${r.kind}] ${r.name} (${src}) session=${r.sessionID}${r.once ? " once" : ""}`
}

// --------------------------------------------------------------- plugin ---

// OWNERSHIP RULE (HARNESS.md "Native driver tools"): only SEAT agents may
// arm wakes — pool-spawned shells are ResumeWatchdog-owned, and two wake
// authorities on one session = double-dispatch. `build` stays allowed as
// the drill/test agent.
const ALLOW_AGENTS = new Set(
  (process.env.EDP_DRIVER_ALLOW_AGENTS || "edp-neuron,build")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean),
)

export const EdpDrivers: Plugin = async ({ client, serverUrl }) => {
  const isHost = process.env.EDP_DRIVER_HOST === "1"
  const log = (msg: string) => {
    try {
      fs.mkdirSync(DRIVER_DIR, { recursive: true })
      fs.appendFileSync(
        path.join(DRIVER_DIR, "engine.log"),
        `${new Date().toISOString()} ${msg}\n`,
      )
    } catch {}
  }

  // ---- engine state (host only) ----
  const fileSizes = new Map<string, number>() // follow-only tails
  const pending = new Map<string, { row: Reg; payload: string }>() // sessionID -> owed wake
  const inFlight = new Set<string>() // sessions we just prompted
  const sseAbort = new Map<string, AbortController>() // reg id -> broker SSE

  async function sessionIdle(sessionID: string): Promise<boolean> {
    try {
      const res: any = await (client as any).session.status()
      const st = res?.data?.[sessionID]
      return !st || st.type === "idle"
    } catch (e) {
      log(`status check failed: ${e}`)
      return true // fail open: prompt_async queues server-side anyway
    }
  }

  async function fire(row: Reg, payload: string): Promise<void> {
    if (inFlight.has(row.sessionID)) {
      pending.set(row.sessionID, { row, payload })
      return
    }
    if (!(await sessionIdle(row.sessionID))) {
      pending.set(row.sessionID, { row, payload })
      log(`coalesced ${row.kind}:${row.name} (session busy)`)
      return
    }
    inFlight.add(row.sessionID)
    try {
      await (client as any).session.promptAsync({
        path: { id: row.sessionID },
        body: {
          ...(row.agent ? { agent: row.agent } : {}),
          parts: [
            {
              type: "text",
              text: `${row.prompt}\n\n[edp-driver ${row.kind}:${row.name}] ${payload}`,
            },
          ],
        },
      })
      log(`fired ${row.kind}:${row.name} -> ${row.sessionID}`)
      if (row.kind === "cron") {
        mutate((rows) =>
          rows.map((r) => (r.id === row.id ? { ...r, lastFiredAt: Date.now() } : r)),
        )
      } else if (row.once) {
        mutate((rows) => rows.filter((r) => r.id !== row.id))
      }
    } catch (e) {
      log(`fire failed ${row.kind}:${row.name}: ${e}`)
    } finally {
      // released on session.idle; timeout backstop so a lost event can't wedge
      setTimeout(() => inFlight.delete(row.sessionID), 60_000)
    }
  }

  function watchBroker(row: Reg): void {
    if (sseAbort.has(row.id)) return
    const brokerUrl = process.env.EDP_BROKER_URL || "http://127.0.0.1:9300"
    const ac = new AbortController()
    sseAbort.set(row.id, ac)
    ;(async () => {
      while (!ac.signal.aborted) {
        try {
          const res = await fetch(`${brokerUrl}/v1/events`, { signal: ac.signal })
          const reader = res.body!.getReader()
          const dec = new TextDecoder()
          let buf = ""
          for (;;) {
            const { done, value } = await reader.read()
            if (done) break
            buf += dec.decode(value, { stream: true })
            const lines = buf.split("\n")
            buf = lines.pop() ?? ""
            for (const line of lines) {
              if (!line.startsWith("data:")) continue
              try {
                const msg = JSON.parse(line.slice(5).trim())
                const to = msg?.to ?? msg?.body?.to
                if (to === row.brokerInbox) {
                  await fire(row, `broker message: ${JSON.stringify(msg).slice(0, 1500)}`)
                }
              } catch {}
            }
          }
        } catch (e) {
          if (!ac.signal.aborted) log(`broker SSE reconnect for ${row.name}: ${e}`)
        }
        await new Promise((r) => setTimeout(r, 3000))
      }
    })()
  }

  function tick(): void {
    const rows = loadRows()
    const now = Date.now()
    const liveIds = new Set(rows.map((r) => r.id))
    // reap SSE watchers whose row is gone
    for (const [id, ac] of sseAbort) {
      if (!liveIds.has(id)) {
        ac.abort()
        sseAbort.delete(id)
      }
    }
    for (const row of rows) {
      if (row.kind === "cron") {
        const base = row.lastFiredAt ?? row.createdAt
        if (now - base >= (row.intervalSeconds ?? 1800) * 1000) void fire(row, "tick")
      } else if (row.file) {
        try {
          const size = fs.statSync(row.file).size
          const prev = fileSizes.get(row.file)
          if (prev === undefined) {
            fileSizes.set(row.file, size) // follow-only: arm at current size
          } else if (size > prev) {
            fileSizes.set(row.file, size)
            let delta = ""
            try {
              const fd = fs.openSync(row.file, "r")
              const len = Math.min(size - prev, 2000)
              const b = Buffer.alloc(len)
              fs.readSync(fd, b, 0, len, prev)
              fs.closeSync(fd)
              delta = b.toString("utf8")
            } catch {}
            void fire(row, `file grew by ${size - prev} bytes:\n${delta}`)
          } else if (size < prev) {
            fileSizes.set(row.file, size) // truncated/rotated: re-arm
          }
        } catch {} // file not there yet — keep waiting
      } else if (row.brokerInbox) {
        watchBroker(row)
      }
    }
  }

  if (isHost) {
    log(`engine start (serverUrl=${serverUrl})`)
    setInterval(tick, 2000)
  }

  // ---- shared arg fragments ----
  const nameArg = tool.schema.string().describe("unique name for this registration (per session)")
  const promptArg = tool.schema
    .string()
    .describe("the prompt the harness re-invokes you with when this fires")

  return {
    event: async ({ event }) => {
      if (!isHost) return
      if (event.type === "session.error") {
        // Crash flowback — wire-identical to ResumeWatchdog._publish_crashed
        // so the same reconcile re-dispatch path serves both harnesses.
        const sid = (event as any).properties?.sessionID
        if (!sid) return
        const inboxes = [
          ...new Set(
            loadRows()
              .filter((r) => r.sessionID === sid && r.brokerInbox)
              .map((r) => r.brokerInbox as string),
          ),
        ]
        const brokerUrl = process.env.EDP_BROKER_URL || "http://127.0.0.1:9300"
        for (const to of inboxes) {
          try {
            await fetch(`${brokerUrl}/v1/publish`, {
              method: "POST",
              headers: { "content-type": "application/json" },
              body: JSON.stringify({
                msg_id: crypto.randomUUID(),
                ts: new Date().toISOString(),
                from: sid,
                to,
                kind: "crashed",
                body: { handle: to, session_id: sid, exit_code: -1 },
              }),
            })
            log(`crash flowback published: ${sid} -> ${to}`)
          } catch (e) {
            log(`crash flowback failed for ${to}: ${e}`)
          }
        }
        return
      }
      if (event.type === "session.idle") {
        const sid = (event as any).properties?.sessionID
        if (!sid) return
        inFlight.delete(sid)
        const owed = pending.get(sid)
        if (owed) {
          pending.delete(sid)
          await fire(owed.row, owed.payload)
        }
      }
    },

    tool: {
      edp_cron_create: tool({
        description:
          "Arm a recurring wake (heartbeat) for THIS session. While you are idle, the harness re-invokes you with `prompt` every `interval_seconds`. Use this at adoption to arm your reconcile heartbeat, then end your turn — do NOT sleep or poll.",
        args: {
          name: nameArg,
          interval_seconds: tool.schema
            .number()
            .min(60)
            .describe("seconds between wakes (min 60; heartbeat convention: 1800)"),
          prompt: promptArg,
        },
        async execute(args, ctx) {
          if (!ALLOW_AGENTS.has(ctx.agent)) {
            return `REFUSED: agent '${ctx.agent}' is pool-owned — the ResumeWatchdog is your wake plane (HARNESS.md items 1/2). Driver tools are for seat shells only.`
          }
          mutate((rows) => [
            ...rows.filter((r) => !(r.sessionID === ctx.sessionID && r.name === args.name)),
            {
              id: newId(),
              kind: "cron",
              name: args.name,
              sessionID: ctx.sessionID,
              agent: ctx.agent,
              prompt: args.prompt,
              intervalSeconds: args.interval_seconds,
              createdAt: Date.now(),
            },
          ])
          return `armed cron '${args.name}': every ${args.interval_seconds}s this session is re-invoked. You can end your turn now; the heartbeat holds.`
        },
      }),

      edp_cron_list: tool({
        description: "List the recurring wakes (crons) armed for THIS session.",
        args: {},
        async execute(_args, ctx) {
          const mine = loadRows().filter(
            (r) => r.kind === "cron" && r.sessionID === ctx.sessionID,
          )
          return mine.length ? mine.map(fmtRow).join("\n") : "no crons armed for this session"
        },
      }),

      edp_cron_delete: tool({
        description: "Delete a recurring wake (cron) previously armed for THIS session, by name.",
        args: { name: nameArg },
        async execute(args, ctx) {
          let found = false
          mutate((rows) =>
            rows.filter((r) => {
              const hit =
                r.kind === "cron" && r.sessionID === ctx.sessionID && r.name === args.name
              if (hit) found = true
              return !hit
            }),
          )
          return found ? `deleted cron '${args.name}'` : `no cron named '${args.name}' for this session`
        },
      }),

      edp_monitor_arm: tool({
        description:
          "Arm a watch for THIS session, then END YOUR TURN. When the source fires, the harness re-invokes you with `prompt` plus the trigger payload. Sources (pass exactly one): `file` = absolute path watched for growth (worklog, events.jsonl, any log); `broker_inbox` = broker handle whose incoming messages wake you. This replaces polling — never loop-and-check after arming.",
        args: {
          name: nameArg,
          file: tool.schema
            .string()
            .optional()
            .describe("absolute path of a file to watch for appended content"),
          broker_inbox: tool.schema
            .string()
            .optional()
            .describe("broker handle (e.g. your plan:action handle) whose inbox wakes you"),
          prompt: promptArg,
          once: tool.schema
            .boolean()
            .optional()
            .describe("if true, the monitor disarms itself after the first fire"),
        },
        async execute(args, ctx) {
          if (!ALLOW_AGENTS.has(ctx.agent)) {
            return `REFUSED: agent '${ctx.agent}' is pool-owned — the ResumeWatchdog is your wake plane (HARNESS.md items 1/2). Driver tools are for seat shells only.`
          }
          if (!args.file === !args.broker_inbox) {
            return "error: pass exactly one of `file` or `broker_inbox`"
          }
          mutate((rows) => [
            ...rows.filter((r) => !(r.sessionID === ctx.sessionID && r.name === args.name)),
            {
              id: newId(),
              kind: "monitor",
              name: args.name,
              sessionID: ctx.sessionID,
              agent: ctx.agent,
              prompt: args.prompt,
              file: args.file,
              brokerInbox: args.broker_inbox,
              once: args.once,
              createdAt: Date.now(),
            },
          ])
          return `armed monitor '${args.name}' on ${args.file ? `file ${args.file}` : `broker inbox ${args.broker_inbox}`}. End your turn now — you will be re-invoked when it fires.`
        },
      }),

      edp_monitor_list: tool({
        description: "List the watches (monitors) armed for THIS session.",
        args: {},
        async execute(_args, ctx) {
          const mine = loadRows().filter(
            (r) => r.kind === "monitor" && r.sessionID === ctx.sessionID,
          )
          return mine.length ? mine.map(fmtRow).join("\n") : "no monitors armed for this session"
        },
      }),

      edp_monitor_disarm: tool({
        description: "Disarm a watch (monitor) previously armed for THIS session, by name.",
        args: { name: nameArg },
        async execute(args, ctx) {
          let found = false
          mutate((rows) =>
            rows.filter((r) => {
              const hit =
                r.kind === "monitor" && r.sessionID === ctx.sessionID && r.name === args.name
              if (hit) found = true
              return !hit
            }),
          )
          return found
            ? `disarmed monitor '${args.name}'`
            : `no monitor named '${args.name}' for this session`
        },
      }),

      edp_driver_status: tool({
        description:
          "Report the driver harness state: whether a firing engine is hosting this fleet, and every cron/monitor registration (all sessions). Diagnostic — safe to call anytime.",
        args: {},
        async execute() {
          const rows = loadRows()
          const head = isHost
            ? "engine: HOSTED IN THIS PROCESS (EDP_DRIVER_HOST=1)"
            : "engine: not in this process (fires from the seat's `opencode serve`; registrations below still hold)"
          const body = rows.length
            ? rows.map(fmtRow).join("\n")
            : "no registrations"
          return `${head}\nregistrations file: ${REG_FILE}\n${body}`
        },
      }),
    },
  }
}
