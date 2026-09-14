/**
 * Loads .pi/extensions/edp8.ts against a FAKE ExtensionAPI and drives the five tools directly —
 * no model, no Pi runtime. Proves: result texts (parity §3), envelopes (§4), batching / truncation /
 * rate-limit / terminal envelopes (§5), mid-turn attach vs standalone delivery, cron idle-only +
 * deferred fire, CronList/CronDelete texts. Run: node <pi>/node_modules/jiti/lib/jiti-cli.mjs tests/pi_ext/fake_pi_harness.ts
 * Prints one JSON line per check: {"check":..., "ok":..., ...}. Exit 1 if any check fails.
 */
import { pathToFileURL } from "node:url";
import { resolve, join } from "node:path";
import { existsSync, readFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { spawn, execFileSync } from "node:child_process";
process.env.EDP8_LANE_DIR = mkdtempSync(join(tmpdir(), "edp8-lane-"));
process.env.EDP8_LANE_REPORT = "0";
process.env.EDP8_LANE_WAIT_S = "20";

type Handler = (e: any, ctx: any) => Promise<any>;
const tools = new Map<string, any>();
const handlers = new Map<string, Handler[]>();
const userMessages: { content: string; opts: any; t: number }[] = [];
let idle = true;
const ctx = { isIdle: () => idle, ui: { notify: (m: string) => console.error("notify:", m) } };
const fakePi = {
	registerTool: (t: any) => tools.set(t.name, t),
	registerCommand: () => {},
	on: (ev: string, h: Handler) => handlers.set(ev, [...(handlers.get(ev) ?? []), h]),
	sendUserMessage: async (content: string, opts: any) => {
		userMessages.push({ content, opts, t: Date.now() });
	},
	sendMessage: async () => {},
};
async function emit(ev: string, e: any) {
	let r: any;
	for (const h of handlers.get(ev) ?? []) r = (await h(e, ctx)) ?? r;
	return r;
}
const checks: any[] = [];
function check(name: string, ok: boolean, extra: any = {}) {
	checks.push({ check: name, ok, ...extra });
	console.log(JSON.stringify({ check: name, ok, ...extra }));
}
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

const extPath = resolve(process.cwd(), ".pi/extensions/edp8.ts");
const mod = await import(pathToFileURL(extPath).href);
await mod.default(fakePi as any);
await emit("session_start", { type: "session_start", reason: "startup" });

check("tools registered", ["Monitor", "TaskStop", "CronCreate", "CronList", "CronDelete"].every((n) => tools.has(n)), { count: tools.size });
check("mcp bridge registered whoami", tools.has("whoami"), { bridged: tools.size - 5 });

// ---- Monitor result text + exit envelope (idle → standalone user message)
const call = (name: string, params: any, id = "toolu_test") => tools.get(name).execute(id, params, undefined, undefined, ctx);
const r1 = await call("Monitor", { command: "echo one; sleep 1; echo two; echo three; exit 3", description: "parity-probe exit-code envelope", persistent: false, timeout_ms: 60000 });
const t1 = r1.content[0].text as string;
const id1 = /task (\w{9})/.exec(t1)?.[1];
check("Monitor result text", /^Monitor started \(task \w{9}, timeout 60000ms\)\. You will be notified on each event\. Keep working — do not poll or sleep\. Events may arrive while you are waiting for the user — an event is not their reply\.$/.test(t1), { text: t1 });
await sleep(2500);
const evs = userMessages.map((m) => m.content);
check("standalone envelope 'one'", evs.some((c) => c.includes(`<task-notification>\n<task-id>${id1}</task-id>\n<summary>Monitor event: "parity-probe exit-code envelope"</summary>\n<event>one</event>\n</task-notification>`)));
check("batched 'two\\nthree'", evs.some((c) => c.includes("<event>two\nthree</event>")));
check("system-reminder wrapper", evs.every((c) => c.startsWith("<system-reminder>\n[SYSTEM NOTIFICATION - NOT USER INPUT]\n") && c.endsWith("</system-reminder>")));
check("failed envelope exit 3", evs.some((c) => c.includes(`<tool-use-id>toolu_test</tool-use-id>`) && c.includes("<status>failed</status>") && c.includes(`<summary>Monitor "parity-probe exit-code envelope" script failed (exit 3)</summary>`)), { last: evs[evs.length - 1] });

// ---- mid-turn attach: busy → pending → appended to next tool_result; rest flushed at agent_settled
userMessages.length = 0;
idle = false;
await call("Monitor", { command: "echo A; sleep 0.5; echo B", description: "attach probe", persistent: false, timeout_ms: 30000 });
// the Monitor result itself is held MONITOR_START_GRACE_MS (§5); the next tool result lands before B (t≈520 ms)
await sleep(100);
const tr = await emit("tool_result", { type: "tool_result", toolName: "bash", toolCallId: "tc1", input: {}, content: [{ type: "text", text: "ls output" }], isError: false });
check("attach to next tool_result", !!tr && tr.content[0].text.startsWith("ls output\n\n<system-reminder>") && tr.content[0].text.includes("<event>A</event>"), { head: tr?.content?.[0]?.text?.slice(0, 120) });
check("nothing standalone while busy", userMessages.length === 0);
await sleep(1500);
idle = true;
await emit("agent_settled", { type: "agent_settled" });
check("settled flushes pending standalone as ONE turn", userMessages.length === 1 && userMessages[0].content.includes("<event>B</event>") && userMessages[0].content.includes("<status>completed</status>") && userMessages[0].content.includes("</system-reminder>\n<system-reminder>"), { n: userMessages.length, msgs: userMessages.map((m) => m.content.slice(0, 60)) });

// ---- truncation + rate limit + timeout + TaskStop
userMessages.length = 0;
await call("Monitor", { command: "head -c 700 /dev/zero | tr '\\0' 'x'; echo", description: "trunc", persistent: false, timeout_ms: 30000 });
await sleep(1200);
check("500-char truncation", userMessages.some((m) => /<event>x{500}\.\.\.\(truncated\)<\/event>/.test(m.content)));
userMessages.length = 0;
await call("Monitor", { command: "for i in $(seq 1 60); do echo burst $i; sleep 0.05; done", description: "rate", persistent: false, timeout_ms: 30000 });
await sleep(5000);
check("rate-limit suppression text", userMessages.some((m) => /\[\d+ events suppressed — output rate too high\. Consider using TaskStop to restart this monitor with a more selective filter\.\]/.test(m.content)), { notifications: userMessages.length });
userMessages.length = 0;
const rt = await call("Monitor", { command: "echo start; sleep 30", description: "timeout", persistent: false, timeout_ms: 1500 });
await sleep(3000);
check("timeout envelope", userMessages.some((m) => m.content.includes("<event>[Monitor timed out — re-arm if needed.]</event>")), { n: userMessages.length });
userMessages.length = 0;
const rs = await call("Monitor", { command: "echo armed; sleep 600", description: "stop", persistent: true, timeout_ms: 1000 });
const ids = /task (\w{9})/.exec(rs.content[0].text)?.[1];
await sleep(600);
const st = await call("TaskStop", { task_id: ids });
check("TaskStop result", st.content[0].text === JSON.stringify({ message: `Successfully stopped task: ${ids} (echo armed; sleep 600)`, task_id: ids, task_type: "local_bash", command: "echo armed; sleep 600" }), { text: st.content[0].text });
await sleep(1000);
check("TaskStop leaves no terminal notification", !userMessages.some((m) => m.content.includes("<status>")), { n: userMessages.length });

// ---- Cron
const cr = await call("CronCreate", { cron: "*/30 * * * *", prompt: "edp8 heartbeat: call context() and act only if something is new; if nothing, end the turn silently" });
const jid = /job (\w{8})/.exec(cr.content[0].text)?.[1];
check("CronCreate recurring text", cr.content[0].text === `Scheduled recurring job ${jid} (Every 30 minutes). Session-only (not written to disk, dies when Claude exits). Auto-expires after 7 days. Use CronDelete to cancel sooner.`);
const cl = await call("CronList", {});
check("CronList text", cl.content[0].text === `${jid} — Every 30 minutes (recurring) [session-only]: edp8 heartbeat: call context() and act only if something is new; if nothing, en…`, { text: cl.content[0].text });
const co = await call("CronCreate", { cron: "0 21 14 9 *", prompt: "one", recurring: false });
check("CronCreate one-shot text", /^Scheduled one-shot task \w{8} \(0 21 14 9 \*\)\. Session-only \(not written to disk, dies when Claude exits\)\. It will fire once then auto-delete\.$/.test(co.content[0].text), { jitter: co.details.jitterS });
const cd = await call("CronDelete", { id: jid });
check("CronDelete text", cd.content[0].text === `Cancelled job ${jid}.`);
// idle-only + deferred: a job due next minute while busy fires only at settle
userMessages.length = 0;
const now = new Date(Date.now() + 61000);
const due = await call("CronCreate", { cron: `${now.getMinutes()} ${now.getHours()} * * *`, prompt: "DUE-PROBE", recurring: false });
idle = false;
const waitMs = due.details.nextFire - Date.now() + 1500;
await sleep(Math.max(waitMs, 0));
check("cron due while busy: not fired", !userMessages.some((m) => m.content === "DUE-PROBE"), { waited_ms: waitMs });
idle = true;
await emit("agent_settled", { type: "agent_settled" });
await sleep(200);
check("cron deferred fire at settle, bare prompt", userMessages.some((m) => m.content === "DUE-PROBE"), { msgs: userMessages.map((m) => m.content.slice(0, 40)) });
// parity §5 (measured 15:57:31Z): several jobs due while busy → ONE user turn, prompts joined by "\n", creation order
userMessages.length = 0;
const n2 = new Date(Date.now() + 61000);
const dA = await call("CronCreate", { cron: `${n2.getMinutes()} ${n2.getHours()} * * *`, prompt: "COAL-A", recurring: false });
const dB = await call("CronCreate", { cron: `${n2.getMinutes()} ${n2.getHours()} * * *`, prompt: "COAL-B", recurring: false });
idle = false;
await sleep(Math.max(Math.max(dA.details.nextFire, dB.details.nextFire) - Date.now() + 1500, 0));
idle = true;
await emit("agent_settled", { type: "agent_settled" });
await sleep(200);
check("coalesced deferred fires: one turn, joined prompts", userMessages.length === 1 && userMessages[0].content === "COAL-A\nCOAL-B", { msgs: userMessages.map((m) => m.content) });
check("one-shots auto-deleted after coalesced fire", !(await call("CronList", {})).content[0].text.includes("COAL-"));


// ---- S8 admission lane: shared with v8/src/edp8/admission.py (cross-language contention)
const LANE = process.env.EDP8_LANE_DIR!;
const LANE_PY = LANE.split(String.fromCharCode(92)).join(String.fromCharCode(92, 92));
const PY = process.platform === "win32" ? resolve(process.cwd(), ".venv/Scripts/python.exe") : resolve(process.cwd(), ".venv/bin/python");
const pyLane = (code: string, timeoutMs = 15000) => execFileSync(PY, ["-c", code], { env: { ...process.env, PYTHONPATH: resolve(process.cwd(), "src") }, timeout: timeoutMs }).toString().trim();
await emit("before_provider_request", { type: "before_provider_request", payload: {} });
check("lane held during provider request", existsSync(join(LANE, "lane.lock", "holder.json")) && JSON.parse(readFileSync(join(LANE, "lane.lock", "holder.json"), "utf8")).holder.startsWith("seat:"));
check("python consult() cannot enter while the seat holds the lane", pyLane(`from edp8.admission import Lane;print(Lane(r'${LANE_PY}').acquire('consult:test',max_wait_s=0.6))`) === "None");
await emit("after_provider_response", { type: "after_provider_response", status: 200, headers: {} });
check("lane released after provider response", !existsSync(join(LANE, "lane.lock")));
// python holds → the seat's request waits for the release
const holder = spawn(PY, ["-c", `import time;from edp8.admission import Lane;l=Lane(r'${LANE_PY}');x=l.acquire('consult:hold',max_wait_s=5);print('got',flush=True);time.sleep(1.5);x.release();print('rel',time.time(),flush=True)`], { env: { ...process.env, PYTHONPATH: resolve(process.cwd(), "src") } });
let holderOut = "";
holder.stdout.on("data", (d) => (holderOut += d.toString()));
await sleep(900);
const t0 = Date.now();
await emit("before_provider_request", { type: "before_provider_request", payload: {} });
const waited = Date.now() - t0;
check("seat waits behind a python consult holder", waited >= 400 && existsSync(join(LANE, "lane.lock")), { waited_ms: waited, holder: holderOut.trim().split("\n")[0] });
await emit("after_provider_response", { type: "after_provider_response", status: 429, headers: { "retry-after": "7" } });
const q = JSON.parse(readFileSync(join(LANE, "quota.json"), "utf8"));
check("429 writes quota.json in consult.py's format", typeof q.blocked_until === "string" && Date.parse(q.blocked_until) - Date.now() > 3000 && Date.parse(q.blocked_until) - Date.now() <= 8000 && q.evidence.includes("HTTP 429"), q);
check("python consult() sees the seat's quota block", pyLane(`import os;os.environ['EDP8_SOL_LOG_DIR']=r'${LANE_PY}';from edp8 import consult;print(bool(consult.quota_block()))`) === "True");
check("lane released after 429", !existsSync(join(LANE, "lane.lock")));

const bad = checks.filter((c) => !c.ok);
console.log(JSON.stringify({ summary: `${checks.length - bad.length}/${checks.length} ok`, failed: bad.map((b) => b.check) }));
await emit("session_shutdown", {});
process.exit(bad.length ? 1 : 0);
