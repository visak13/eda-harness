// The thumbnail worker (C12, architect m-1a33d88bc7): pure-JS decoding never runs on the extension host's
// own thread. One job at a time: {id, bytes, type} in, {id, thumb} out. Built by esbuild to dist/thumbWorker.js.
import { parentPort } from 'node:worker_threads';
import { thumbnail } from './thumb';

parentPort?.on('message', (m: { id: number; bytes: Uint8Array; type: string }) => {
  let thumb;
  try { thumb = thumbnail(m.bytes, m.type); } catch (e) { thumb = { ok: false, reason: `decode failed (${(e as Error)?.name ?? 'error'})` }; }
  parentPort!.postMessage({ id: m.id, thumb });
});
