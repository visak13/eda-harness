import type { Register } from 'claude-code'

// edp-wake (s-e60c3d42ad, design-7e26c12869): a harness seat runs the edp8 feed listener as a child of
// this mod and turns each line it prints into one turn. No Monitor, so no 30-minute expiry and no re-arm turn.
// A session that is not a seat (no EDP8_PARTICIPANT / EDP_HANDLE) does nothing at all.

const MAX_QUICK_DEATHS = 3   // listener exits within 10 s with no output, this many times in a row: give up
const COALESCE_MS = 1500     // lines printed within this window of the first share one turn
const WAKE_KEYS = ['event', 'msg', 'broker_msg', 'heartbeat']   // lines that deserve a turn
const NO_LISTENER_TEXT =
  'edp-wake: the feed listener could not start in this seat (it exited at once three times), so nothing wakes ' +
  'you. Call subscribe() now and run its monitor_cmd under the Monitor tool (persistent: true where offered); ' +
  're-arm it whenever it ends. Then continue your plan.'
const HEARTBEAT_TEXT =
  'heartbeat: context_delta(cursor=your last valid cursor) for anything new and answer it, then RESUME THE NEXT ' +
  'UNBUILT ITEM of your plan doc. End the turn silently when your ticket is in_review/done, you are blocked ' +
  '(said so on the board), or you hold no ticket.'

// Splits a stream of text pieces into complete lines; the tail waits for its newline.
export function lineSplitter(): (piece: string) => string[] {
  let tail = ''
  return (piece) => {
    const parts = (tail + piece).split(/\r?\n/)
    tail = parts.pop() ?? ''
    return parts.filter((l) => l.trim() !== '')
  }
}

// Whether a listener line starts a turn: only a board event, an addressed message, a broker copy or its own
// heartbeat does. The banner, `lost` / `recovered` and error lines are logged, never a turn.
export function isWake(line: string): boolean {
  try {
    const obj = JSON.parse(line)
    return obj !== null && typeof obj === 'object' && WAKE_KEYS.some((k) => k in obj)
  } catch {
    return false
  }
}

export const register: Register = (on) => {
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    if ((await $.env.get('EDP_WAKE_MOD')) === '0') return started   // the operator's kill switch
    const participant = (await $.env.get('EDP8_PARTICIPANT')) || (await $.env.get('EDP_HANDLE'))
    if (!participant) return started
    const py = await $.env.get('EDP8_FEED_PY')
    const board = await $.env.get('EDP8_BOARD_URL')
    if (!py || !board) {
      $.ui.log('edp-wake: EDP8_FEED_PY / EDP8_BOARD_URL unset; no listener started', { to: 'debug' })
      return started
    }
    const broker = await $.env.get('EDP_BROKER_URL')
    const argv = [py, '-m', 'edp8.feed_driver', '--participant', participant, '--board', board, '--wake-owner', 'mod']
    if (broker) argv.push('--broker', broker)

    // Turns go out one at a time, in arrival order. `ticking` stops heartbeats stacking behind a long turn.
    // Lines that arrive together (one close prints shell_dead and its hint within milliseconds) or while a turn
    // is still being submitted share ONE turn: a burst costs the seat one turn, not one per line.
    let chain: Promise<unknown> = Promise.resolve()
    const pending: string[] = []
    let flushQueued = false
    const wake = (text: string) => {
      pending.push(text)
      if (flushQueued) return
      flushQueued = true
      chain = chain
        .then(async () => {
          await $.clock.sleep(COALESCE_MS)
          flushQueued = false
          const batch = pending.splice(0)
          if (batch.length) await $.prompt.submit({ text: batch.join('\n') })
        })
        .catch(() => {
          flushQueued = false
        })
    }

    void (async () => {
      let backoffMs = 1000
      let quickDeaths = 0
      for (;;) {
        const split = lineSplitter()
        const startedAt = await $.clock.now()
        let heardFrom = false
        // the mod owns the tick; the listener's own heartbeat is off so a seat gets one tick, not two
        const child = $.process.spawn({ argv, env: { EDP8_HEARTBEAT_S: '0', PYTHONUNBUFFERED: '1' } })
        try {
          for await (const piece of child) {
            if (!('text' in piece) || piece.stream !== 'stdout') continue
            heardFrom = true
            backoffMs = 1000
            for (const line of split(piece.text)) {
              if (isWake(line)) wake(line)
              else $.ui.log(`edp-wake: ${line}`, { to: 'debug' })
            }
          }
        } catch (err) {
          $.ui.log(`edp-wake: listener failed: ${String(err)}`, { to: 'debug' })
        }
        // a listener that dies at once with nothing printed cannot run here (e.g. a Python without edp8):
        // say so once and stop, rather than respawning it every 30 s forever
        quickDeaths = !heardFrom && (await $.clock.now()) - startedAt < 10000 ? quickDeaths + 1 : 0
        if (quickDeaths >= MAX_QUICK_DEATHS) {
          $.ui.toast(`edp-wake: the listener (${py}) exits at once; this seat has no wake plane. Use the Monitor.`)
          // the model must hear it: a toast reaches no unattended seat. subscribe() answers with a monitor_cmd
          // now, because the listener's readiness file never appeared.
          wake(NO_LISTENER_TEXT)
          return
        }
        await $.clock.sleep(backoffMs)
        backoffMs = Math.min(backoffMs * 2, 30000)
      }
    })()

    const beatS = Number((await $.env.get('EDP8_HEARTBEAT_S')) ?? '1800')
    if (beatS > 0) {
      let ticking = false
      $.clock.every(beatS * 1000, () => {
        if (ticking) return
        ticking = true
        chain = chain.then(() => $.prompt.submit({ text: HEARTBEAT_TEXT })).catch(() => undefined).finally(() => { ticking = false })
      })
    }
    return started
  })
}
