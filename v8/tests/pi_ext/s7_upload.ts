// Exercise the actual bridge upload branch and local helper against an isolated board.
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
const calls: any[] = [];
globalThis.fetch = async (_url: any, options: any) => {
  const request = JSON.parse(options.body); calls.push(request);
  assert.notEqual(request.method, 'tools/call', 'upload must never forward a host path to MCP');
  const result = request.method === 'tools/list' ? { tools: [{ name: 'artifact_upload',
    inputSchema: { type: 'object', properties: { path: { type: 'string' }, note: { type: 'string' } }, required: ['path'] } }] } : {};
  return new Response(JSON.stringify({ jsonrpc: '2.0', id: request.id, result }), { headers: { 'content-type': 'application/json' } });
};
const tools = new Map<string, any>(), handlers = new Map<string, any[]>();
const pi: any = { registerTool: (t: any) => tools.set(t.name, t), registerCommand() {},
  on: (event: string, handler: any) => handlers.set(event, [...(handlers.get(event) ?? []), handler]) };
const mod = await import(pathToFileURL(resolve('.pi/extensions/edp8.ts')).href);
await mod.default(pi);
const tool = tools.get('artifact_upload');
const cwd = process.env.S7_WORKSPACE!;
async function call(params: any, signal?: AbortSignal) {
  return JSON.parse((await tool.execute('t', params, signal, undefined, { cwd })).content[0].text);
}
const out = await call({ path: '@proof.txt', note: 'Pi adapter proof', workspace_root: '..' });
assert.equal(out.ok, true, JSON.stringify(out));
assert.equal(out.value.created_by, 'eng');
assert.equal(out.value.staged, true);
assert.equal((await call({ path: '../outside.txt' })).error.code, 'upload_refused');
assert.equal((await call({ path: 'proof.txt' }, AbortSignal.abort())).error.code, 'cancelled');
assert.equal(calls.length, 2);
for (const fn of handlers.get('session_shutdown') ?? []) await fn({}, {});
console.log(JSON.stringify({ ok: true, artifact: out.value.id }));
