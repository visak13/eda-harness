/** Seat-local upload interception. No remote filesystem path ever reaches MCP. */
import { spawn } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HOME = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const PYTHON = resolve(HOME, process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python');
const failure = (code: string, message: string) => ({ ok: false, error: { code, message },
  hint: 'Use a regular workspace file up to 25 MB; the local helper must be installed. No proxy fallback.' });

export async function localArtifactUpload(params: Record<string, unknown>, cwd: string, signal?: AbortSignal): Promise<any> {
  if (!cwd || typeof params.path !== 'string' || (params.note !== undefined && typeof params.note !== 'string'))
    return failure('schema', 'artifact_upload requires path and optional note strings plus a trusted workspace');
  const input = JSON.stringify({ path: params.path.replace(/^@/, ''), note: params.note ?? '' });
  if (Buffer.byteLength(input) > 32768) return failure('schema', 'upload arguments exceed 32 KB');
  if (signal?.aborted) return failure('cancelled', 'upload cancelled');
  return new Promise((done) => {
    let output = '';
    let settled = false;
    const child = spawn(PYTHON, ['-m', 'edp8.local_upload'], {
      cwd: HOME, shell: false, windowsHide: true,
      env: { ...process.env, EDP8_UPLOAD_ROOT: cwd }, stdio: ['pipe', 'pipe', 'ignore'],
    });
    const finish = (value: any) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener('abort', abort);
      done(value);
    };
    const abort = () => { child.kill(); finish(failure('cancelled', 'upload cancelled; attachment may need reconciliation')); };
    const timer = setTimeout(() => { child.kill(); finish(failure('timeout', 'upload timed out; attachment may need reconciliation')); }, 65000);
    signal?.addEventListener('abort', abort, { once: true });
    child.on('error', () => finish(failure('unavailable', 'local upload helper could not start')));
    child.stdin.on('error', () => finish(failure('unavailable', 'local upload helper input failed')));
    child.stdout.on('data', (chunk) => {
      output += chunk.toString('utf8');
      if (Buffer.byteLength(output) > 49152) { child.kill(); finish(failure('output_limit', 'upload receipt exceeded 48 KB')); }
    });
    child.on('close', (code) => {
      if (code !== 0) return finish(failure('unavailable', 'local upload helper failed'));
      try {
        const value = JSON.parse(output);
        if (typeof value?.ok !== 'boolean') throw new Error();
        finish(value);
      } catch { finish(failure('protocol', 'local upload helper returned an invalid receipt')); }
    });
    child.stdin.end(input);
  });
}

// Pi auto-discovers .ts files here; helper intentionally registers no tools by itself.
export default function () {}
