// Runs thumbnails in a worker thread (C12, architect m-1a33d88bc7: don't block the extension host). Jobs are
// serialised (one decode in memory at a time); a job that runs past the timeout kills the worker, and the
// next job starts a fresh one. Disposed with the extension.
import { Worker } from 'node:worker_threads';
import * as path from 'node:path';
import type { Thumb } from '../core/thumb';

const JOB_TIMEOUT_MS = 20_000;

export class ThumbWorker {
  private worker?: Worker;
  private seq = 0;
  private chain: Promise<unknown> = Promise.resolve();
  private waiting = new Map<number, (t: Thumb) => void>();

  constructor(private extensionPath: string, private log: (line: string) => void) {}

  private start(): Worker {
    if (this.worker) return this.worker;
    const w = new Worker(path.join(this.extensionPath, 'dist', 'thumbWorker.js'));
    w.on('message', (m: { id: number; thumb: Thumb }) => { this.waiting.get(m.id)?.(m.thumb); this.waiting.delete(m.id); });
    const fail = (why: string) => {
      if (this.worker === w) this.worker = undefined;
      for (const [, r] of this.waiting) r({ ok: false, reason: why });
      this.waiting.clear();
    };
    w.on('error', e => { this.log(`thumbs: worker error (${e.name})`); fail('thumbnail worker failed'); });
    w.on('exit', () => fail('thumbnail worker stopped'));
    w.unref();
    return (this.worker = w);
  }

  /** The thumbnail, or why there is none; never throws. */
  thumb(bytes: Uint8Array, type: string): Promise<Thumb> {
    const job = this.chain.then(() => new Promise<Thumb>(resolve => {
      let w: Worker;
      try { w = this.start(); } catch (e) { resolve({ ok: false, reason: `no thumbnail worker (${(e as Error)?.name ?? 'error'})` }); return; }
      const id = ++this.seq;
      const timer = setTimeout(() => {
        if (!this.waiting.has(id)) return;
        this.log('thumbs: job timed out; restarting the worker');
        this.waiting.delete(id);
        resolve({ ok: false, reason: 'thumbnail timed out' });
        void w.terminate();
      }, JOB_TIMEOUT_MS);
      this.waiting.set(id, t => { clearTimeout(timer); resolve(t); });
      w.postMessage({ id, bytes, type });
    }));
    this.chain = job.catch(() => {});
    return job;
  }

  dispose(): void {
    const w = this.worker;
    this.worker = undefined;
    void w?.terminate();
  }
}
