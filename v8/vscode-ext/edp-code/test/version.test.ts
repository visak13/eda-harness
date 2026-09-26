// S8 (c-eb38e8c949): the version-mismatch prompt against a stub board (a real HTTP server serving /v1/health),
// and the install command the prompt's action would run.
import { createServer, type Server } from 'node:http';
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

const ui = vi.hoisted(() => ({ warn: vi.fn(), sent: [] as string[], clip: vi.fn() }));
vi.mock('vscode', () => ({
  window: {
    showWarningMessage: ui.warn,
    createTerminal: () => ({ show: () => undefined, sendText: (t: string) => ui.sent.push(t) }),
  },
  env: { clipboard: { writeText: ui.clip } },
}));

import { compare, vsixUrl } from '../src/core/version';
import { COPY, RUN, promptOnMismatch } from '../src/vscode/version';

let server: Server;
let base = '';
let boardVersion = '0.9.0';

beforeAll(async () => {
  server = createServer((req, res) => {
    if (req.url === '/v1/health') {
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ ok: true, service: 'board', version: boardVersion }));
    } else { res.writeHead(404); res.end(); }
  });
  await new Promise<void>(r => server.listen(0, '127.0.0.1', r));
  const a = server.address();
  base = `http://127.0.0.1:${typeof a === 'object' && a ? a.port : 0}`;
});
afterAll(() => new Promise<void>(r => server.close(() => r())));
beforeEach(() => { ui.warn.mockReset(); ui.clip.mockReset(); ui.sent.length = 0; });

describe('version mismatch prompt (stub board)', () => {
  it('a newer board prompts to install the matching extension and runs its install command', async () => {
    boardVersion = '0.9.0';
    ui.warn.mockResolvedValueOnce(RUN);
    const log: string[] = [];
    const m = await promptOnMismatch('0.8.0', base, l => log.push(l));
    expect(m?.behind).toBe('extension');
    const [message, opts, ...actions] = ui.warn.mock.calls[0];
    console.log(`prompt: ${message}\ncommand: ${opts.detail}`);
    expect(message).toContain('board is 0.9.0; this extension is for 0.8.0');
    expect(actions).toEqual([RUN, COPY]);
    expect(opts.detail).toContain('code --install-extension');
    expect(opts.detail).toContain(vsixUrl('0.9.0'));
    expect(ui.sent).toEqual([opts.detail]);
    expect(log[0]).toMatch(/version mismatch: extension 0\.8\.0, board 0\.9\.0/);
  });

  it('an older board prompts `heronry update`, copied on request', async () => {
    boardVersion = '0.7.3';
    ui.warn.mockResolvedValueOnce(COPY);
    const m = await promptOnMismatch('0.8.0', base, () => undefined);
    console.log(`prompt: ${ui.warn.mock.calls[0][0]}\ncommand: ${m?.command}`);
    expect(m).toMatchObject({ behind: 'board', command: 'heronry update' });
    expect(ui.clip).toHaveBeenCalledWith('heronry update');
    expect(ui.sent).toEqual([]);
  });

  it('the same major.minor, or an unreachable board, shows nothing', async () => {
    boardVersion = '0.8.7';
    expect(await promptOnMismatch('0.8.0', base, () => undefined)).toBeUndefined();
    expect(await promptOnMismatch('0.8.0', 'http://127.0.0.1:9', () => undefined)).toBeUndefined();
    expect(ui.warn).not.toHaveBeenCalled();
  });
});

describe('compare', () => {
  it('builds a PowerShell command on Windows and a curl one elsewhere', () => {
    expect(compare('0.8.0', '1.0.0', 'win32')?.command).toMatch(/^Invoke-WebRequest .*edp-code-1\.0\.0\.vsix.*code --install-extension/);
    expect(compare('0.8.0', '1.0.0', 'linux')?.command).toMatch(/^curl -fsSL .* && code --install-extension \/tmp\/edp-code-1\.0\.0\.vsix$/);
    expect(compare('0.8.0', 'dev')).toBeUndefined();
  });
});
