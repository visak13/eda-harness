import { expect, mock, test } from 'claude-code/testing'
import { isWake, lineSplitter } from './register'

const SEAT_ENV = {
  EDP8_PARTICIPANT: 'engineer.s-1',
  EDP8_FEED_PY: 'python',
  EDP8_BOARD_URL: 'http://127.0.0.1:9400',
  EDP_BROKER_URL: 'http://127.0.0.1:9300',
}

test('a line split across two pieces is held until its newline', () => {
  const split = lineSplitter()
  expect(split('{"event": {"seq"')).toEqual([])
  expect(split(': 1}}\n{"msg": {}}\n')).toEqual(['{"event": {"seq": 1}}', '{"msg": {}}'])
})

test('only events, messages, broker copies and heartbeats start a turn', () => {
  expect(isWake('{"event": {"seq": 1}}')).toBe(true)
  expect(isWake('{"msg": {"text": "hi"}}')).toBe(true)
  expect(isWake('{"broker_msg": {}}')).toBe(true)
  expect(isWake('{"heartbeat": {"reason": "liveness"}}')).toBe(true)
  expect(isWake('{"listening": {}}')).toBe(false)
  expect(isWake('{"feed": "lost"}')).toBe(false)
  expect(isWake('{"error": "board: x"}')).toBe(false)
  expect(isWake('not json')).toBe(false)
})

test('a burst of listener lines is one prompt, without the banner and outage lines', async ($, on) => {
  mock.env(on, SEAT_ENV)
  const clock = mock.clock(on)
  on('session.start', async (_$, e) => ({ cwd: e.cwd }) as never)
  on('ui.log', async () => ({ value: undefined }) as never)
  const prompts: string[] = []
  on('process.spawn', async function* () {
    yield { stream: 'stdout', text: '{"listening": {}}\n{"event": {"seq": 1}}\n{"feed": "lost"}\n{"msg": {"text": "hello"}}\n' }
    await new Promise(() => undefined)
  })
  on('prompt.submit', async (_$, e) => {
    prompts.push(e.text)
    return { text: e.text } as never
  })
  await $.session.start({ source: 'startup', cwd: '.' } as never)
  await new Promise((r) => setTimeout(r, 50))
  await clock.advance(2000)
  expect(prompts).toEqual(['{"event": {"seq": 1}}\n{"msg": {"text": "hello"}}'])
})

test('lines that arrive apart are separate prompts, in order', async ($, on) => {
  mock.env(on, SEAT_ENV)
  const clock = mock.clock(on)
  on('session.start', async (_$, e) => ({ cwd: e.cwd }) as never)
  on('ui.log', async () => ({ value: undefined }) as never)
  const prompts: string[] = []
  let release: () => void = () => undefined
  on('process.spawn', async function* () {
    yield { stream: 'stdout', text: '{"event": {"seq": 1}}\n' }
    await new Promise<void>((r) => { release = r })
    yield { stream: 'stdout', text: '{"event": {"seq": 2}}\n' }
    await new Promise(() => undefined)
  })
  on('prompt.submit', async (_$, e) => {
    prompts.push(e.text)
    return { text: e.text } as never
  })
  await $.session.start({ source: 'startup', cwd: '.' } as never)
  await new Promise((r) => setTimeout(r, 50))
  await clock.advance(2000)
  expect(prompts).toEqual(['{"event": {"seq": 1}}'])
  release()
  await new Promise((r) => setTimeout(r, 50))
  await clock.advance(2000)
  expect(prompts).toEqual(['{"event": {"seq": 1}}', '{"event": {"seq": 2}}'])
})

test('a session without a participant starts nothing', async ($, on) => {
  mock.env(on, { EDP8_FEED_PY: 'python', EDP8_BOARD_URL: 'http://127.0.0.1:9400' })
  on('session.start', async (_$, e) => ({ cwd: e.cwd }) as never)
  let spawned = 0
  on('process.spawn', async function* () {
    spawned++
  })
  await $.session.start({ source: 'startup', cwd: '.' } as never)
  await new Promise((r) => setTimeout(r, 50))
  expect(spawned).toBe(0)
})

test('an idle seat gets one heartbeat per 30 minutes and nothing else', async ($, on) => {
  mock.env(on, SEAT_ENV)
  const clock = mock.clock(on)
  on('session.start', async (_$, e) => ({ cwd: e.cwd }) as never)
  on('ui.log', async () => ({ value: undefined }) as never)
  on('process.spawn', async function* () {
    await new Promise(() => undefined)
  })
  const prompts: string[] = []
  on('prompt.submit', async (_$, e) => {
    prompts.push(e.text)
    return { text: e.text } as never
  })
  await $.session.start({ source: 'startup', cwd: '.' } as never)
  await clock.advance(29 * 60 * 1000)
  expect(prompts).toEqual([])
  await clock.advance(61 * 1000)
  expect(prompts.length).toBe(1)
  expect(prompts[0]).toContain('heartbeat: context_delta')
  await clock.advance(30 * 60 * 1000)
  expect(prompts.length).toBe(2)
})

test('a listener that dies at once with no output is given up on after three tries', async ($, on) => {
  mock.env(on, SEAT_ENV)
  const clock = mock.clock(on)
  on('session.start', async (_$, e) => ({ cwd: e.cwd }) as never)
  on('ui.log', async () => ({ value: undefined }) as never)
  const toasts: string[] = []
  const prompts: string[] = []
  on('prompt.submit', async (_$, e) => {
    prompts.push(e.text)
    return { text: e.text } as never
  })
  on('ui.toast', async (_$, e) => {
    toasts.push(e.text)
    return { value: undefined } as never
  })
  let spawned = 0
  on('process.spawn', async function* () {
    spawned++
    return { value: { code: 1, signal: null } } as never
  })
  await $.session.start({ source: 'startup', cwd: '.' } as never)
  await clock.advance(120 * 1000)
  expect(spawned).toBe(3)
  expect(toasts.length).toBe(1)
  expect(prompts.length).toBe(1)
  expect(prompts[0]).toContain("subscribe()")
  expect(prompts[0]).toContain("Monitor")
})

test('EDP_WAKE_MOD=0 keeps the mod from spawning a listener or ticking, whatever else is set', async ($, on) => {
  mock.env(on, { ...SEAT_ENV, EDP_WAKE_MOD: '0' })
  const clock = mock.clock(on)
  on('session.start', async (_$, e) => ({ cwd: e.cwd }) as never)
  on('ui.log', async () => ({ value: undefined }) as never)
  let spawned = 0
  on('process.spawn', async function* () {
    spawned++
    return { value: { code: 0, signal: null } } as never
  })
  const prompts: string[] = []
  on('prompt.submit', async (_$, e) => {
    prompts.push(e.text)
    return { text: e.text } as never
  })
  await $.session.start({ source: 'startup', cwd: '.' } as never)
  await clock.advance(3 * 60 * 60 * 1000)
  expect(spawned).toBe(0)
  expect(prompts).toEqual([])
})

// the seat identity is EDP8_PARTICIPANT or, when that is unset, EDP_HANDLE (register.ts accepts either)
test('EDP_HANDLE alone, with no EDP8_PARTICIPANT, names the seat the listener runs for', async ($, on) => {
  const { EDP8_PARTICIPANT: _unused, ...withoutParticipant } = SEAT_ENV
  mock.env(on, { ...withoutParticipant, EDP_HANDLE: 'engineer.s-2' })
  mock.clock(on)
  on('session.start', async (_$, e) => ({ cwd: e.cwd }) as never)
  on('ui.log', async () => ({ value: undefined }) as never)
  const argvs: string[][] = []
  on('process.spawn', async function* (_$, e) {
    argvs.push((e as { argv: string[] }).argv)
    await new Promise(() => undefined)
  })
  await $.session.start({ source: 'startup', cwd: '.' } as never)
  await new Promise((r) => setTimeout(r, 50))
  expect(argvs.length).toBe(1)
  expect(argvs[0].slice(argvs[0].indexOf('--participant'), argvs[0].indexOf('--participant') + 2)).toEqual(['--participant', 'engineer.s-2'])
})

test('EDP8_PARTICIPANT wins when both it and EDP_HANDLE are set', async ($, on) => {
  mock.env(on, { ...SEAT_ENV, EDP_HANDLE: 'engineer.s-other' })
  mock.clock(on)
  on('session.start', async (_$, e) => ({ cwd: e.cwd }) as never)
  on('ui.log', async () => ({ value: undefined }) as never)
  const argvs: string[][] = []
  on('process.spawn', async function* (_$, e) {
    argvs.push((e as { argv: string[] }).argv)
    await new Promise(() => undefined)
  })
  await $.session.start({ source: 'startup', cwd: '.' } as never)
  await new Promise((r) => setTimeout(r, 50))
  expect(argvs.length).toBe(1)
  expect(argvs[0]).toContain('engineer.s-1')
  expect(argvs[0]).not.toContain('engineer.s-other')
})
