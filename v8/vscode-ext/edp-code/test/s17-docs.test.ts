import { describe, expect, it, vi } from 'vitest';
import { boardClient, type Creds } from '../src/core/api';
import { sectionSizes } from '../src/core/reader';

// S17 (ruling m-639da0243d): GET /v1/docs/{id} returns the head by default; the reader shows the whole body and the
// version list, so both of its doc reads ask for all=true. The reader's outline carries each section's size.
const creds = async (): Promise<Creds> => ({ participant: 'owner', token: 'tok' });
const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });

describe('doc reads ask for the whole body', () => {
  it('latestDoc and doc(id, version) pass all=true', async () => {
    const f = vi.fn(async () => json({ ok: true, value: { id: 'note-1', body_md: 'x', version: 2, warning: 'w' } }));
    const c = boardClient('http://127.0.0.1:9400', creds, f as unknown as typeof fetch);
    expect((await c.latestDoc('note-1')).warning).toBe('w');
    await c.doc('note-1', 2);
    const urls = f.mock.calls.map(a => new URL(String((a as unknown[])[0])));
    expect(urls.map(u => u.searchParams.get('all'))).toEqual(['true', 'true']);
    expect(urls[1].searchParams.get('version')).toBe('2');
  });
});

describe('sectionSizes', () => {
  it('sizes each ATX section up to the next heading of the same or higher level, skipping fences', () => {
    const body = '# T\nintro\n## A\naaaa\n```\n# not a heading\n```\n### A1\nx\n## B\nb\n';
    const m = sectionSizes(body);
    expect(m.map(s => [s.h, s.level])).toEqual([['T', 1], ['A', 2], ['A1', 3], ['B', 2]]);
    expect(m[0].chars).toBe(body.length);
    expect(m[1].chars).toBe(body.indexOf('## B') - body.indexOf('## A'));
    expect(m[3].chars).toBe('## B\nb\n'.length);
  });
});
