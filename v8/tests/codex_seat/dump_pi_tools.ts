/**
 * Reference dump for the codex seat's byte-parity test (s-10a2b1f9ec): loads .pi/extensions/edp8.ts
 * against a fake ExtensionAPI (no model, no Pi runtime, MCP bridge pointed at a dead port) and prints
 * ONE JSON object: the five parity tools' {name, description, parameters} as registered, plus the
 * result texts of a fixed seeded call script. tests/test_codex_seat.py runs the same script through
 * edp8.codex_seat.tools and asserts equality.
 * Run: node <pi-coding-agent>/node_modules/jiti/lib/jiti-cli.mjs tests/codex_seat/dump_pi_tools.ts
 */
import { pathToFileURL } from "node:url";
import { resolve, join } from "node:path";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
process.env.EDP8_LANE_DIR = mkdtempSync(join(tmpdir(), "edp8-lane-"));
process.env.EDP8_LANE_REPORT = "0";
process.env.EDP8_MCP_URL = "http://127.0.0.1:9";
process.env.EDP_PI_TASKS_DIR = mkdtempSync(join(tmpdir(), "edp8-tasks-"));

const tools = new Map<string, any>();
const fakePi = {
	registerTool: (t: any) => tools.set(t.name, t),
	registerCommand: () => {},
	on: () => {},
	sendUserMessage: async () => {},
	sendMessage: async () => {},
};
const mod = await import(pathToFileURL(resolve(process.cwd(), ".pi/extensions/edp8.ts")).href);
await mod.default(fakePi as any);
const ctx = { isIdle: () => true };
const call = async (name: string, params: any) => {
	const r = await tools.get(name).execute("toolu_ref", params, undefined, undefined, ctx);
	return { text: r.content.map((c: any) => c.text).join(""), isError: !!r.isError };
};
const names = ["Monitor", "TaskStop", "CronCreate", "CronList", "CronDelete"];
const specs = names.map((n) => {
	const t = tools.get(n);
	return { name: t.name, description: t.description, parameters: JSON.parse(JSON.stringify(t.parameters)) };
});
const script: [string, any][] = JSON.parse(process.env.EDP_DUMP_SCRIPT ?? "[]");
const results: any[] = [];
for (const [name, params] of script) results.push(await call(name, params));
console.log(JSON.stringify({ specs, results }));
process.exit(0);
