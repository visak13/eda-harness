// S7 bridge characterization: synthetic transport, no model or shared service.
import assert from 'node:assert/strict';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
process.env.EDP_PI_TASKS_DIR = mkdtempSync(join(tmpdir(), 's7-pi-'));
process.env.EDP8_LANE_DIR = process.env.EDP_PI_TASKS_DIR;
const calls: any[] = [];
globalThis.fetch = async (_url: any, options: any) => {
  const request = JSON.parse(options.body); calls.push(request);
  const result = request.method === 'tools/list' ? { tools: [
    { name: 'echo_contract', description: 'echo', inputSchema: { type: 'object', properties: {} } },
  ] } : request.method === 'tools/call' ? { content: [{ type: 'text', text: 'unchanged envelope' }], structuredContent: { ok: true } } : {};
  return new Response(JSON.stringify({ jsonrpc: '2.0', id: request.id, result }), { headers: { 'content-type': 'application/json' } });
};
const tools = new Map<string, any>();
const handlers = new Map<string, any[]>();
const pi: any = { registerTool: (t: any) => tools.set(t.name, t), registerCommand() {},
  on: (event: string, handler: any) => handlers.set(event, [...(handlers.get(event) ?? []), handler]) };
const mod = await import(pathToFileURL(resolve('.pi/extensions/edp8.ts')).href);
await mod.default(pi);
const out = await tools.get('echo_contract').execute('t', { dynamic: 'unchanged' });
assert.equal(out.content[0].text, 'unchanged envelope');
assert.deepEqual(calls.at(-1).params, { name: 'echo_contract', arguments: { dynamic: 'unchanged' } });
assert.equal(tools.has('artifact_upload'), false); // no invented capability on an old remote schema
for (const fn of handlers.get('session_shutdown') ?? []) await fn({}, {});
console.log('S7 legacy MCP bridge characterization passed');
