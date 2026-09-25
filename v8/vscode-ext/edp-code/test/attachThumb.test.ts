// C12 thumbnails (s-85dd35a166): header dims without decode, fit/downscale, the architect's caps
// (m-1a33d88bc7: 8 MB encoded, 24 MP decoded), pass-through of small images, PNG/JPEG re-encode.
import { describe, expect, it } from 'vitest';
import jpeg from 'jpeg-js';
import { PNG } from 'pngjs';
import { downscale, fit, imageDims, PASS_THROUGH_MAX, THUMB_EDGE, THUMB_MAX_ENCODED, thumbnail } from '../src/core/thumb';

function png(w: number, h: number, fill = (x: number, y: number) => [x % 256, y % 256, 128, 255]): Uint8Array {
  const p = new PNG({ width: w, height: h });
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) p.data.set(fill(x, y), (y * w + x) * 4);
  return new Uint8Array(PNG.sync.write(p));
}
function jpg(w: number, h: number): Uint8Array {
  const data = new Uint8Array(w * h * 4);
  for (let i = 0; i < w * h; i++) data.set([200, 100, 50, 255], i * 4);
  return new Uint8Array(jpeg.encode({ data, width: w, height: h }, 90).data);
}
const decodeUri = (u: string) => Buffer.from(u.split(',')[1], 'base64');

describe('imageDims reads the header only', () => {
  it('png, jpeg', () => {
    expect(imageDims(png(33, 17), 'image/png')).toEqual({ w: 33, h: 17 });
    expect(imageDims(jpg(40, 30), 'image/jpeg')).toEqual({ w: 40, h: 30 });
  });
  it('gif and the three webp flavours', () => {
    const gif = new Uint8Array([0x47, 0x49, 0x46, 0x38, 0x39, 0x61, 0x2c, 0x01, 0xc8, 0x00, 0, 0]);
    expect(imageDims(gif, 'image/gif')).toEqual({ w: 300, h: 200 });
    const riff = (chunk: string, body: number[]) => new Uint8Array([...Buffer.from('RIFF'), 0, 0, 0, 0, ...Buffer.from('WEBP'), ...Buffer.from(chunk), 0, 0, 0, 0, ...body]);
    // VP8X: flags(4) then 24-bit (w-1), (h-1) at byte 24
    expect(imageDims(riff('VP8X', [0, 0, 0, 0, 0x1f, 0x03, 0x00, 0xdf, 0x01, 0x00]), 'image/webp')).toEqual({ w: 800, h: 480 });
    // VP8L: signature 0x2f at 20, then 14-bit w-1, 14-bit h-1
    const v = (99) | (49 << 14);
    expect(imageDims(riff('VP8L', [0x2f, v & 255, (v >> 8) & 255, (v >> 16) & 255, (v >>> 24) & 255, 0, 0, 0, 0, 0]), 'image/webp')).toEqual({ w: 100, h: 50 });
    // VP8 : frame tag(3) start code(3) then 16-bit w, h at 26/28
    expect(imageDims(riff('VP8 ', [0, 0, 0, 0x9d, 0x01, 0x2a, 64, 0, 32, 0]), 'image/webp')).toEqual({ w: 64, h: 32 });
  });
  it('a header that is not what the type says is null', () => {
    expect(imageDims(png(4, 4), 'image/jpeg')).toBeNull();
    expect(imageDims(new Uint8Array([1, 2, 3]), 'image/png')).toBeNull();
    expect(imageDims(png(4, 4), 'image/svg+xml')).toBeNull();
  });
});

describe('fit + downscale', () => {
  it('fits the long edge to 480, never upscales, keeps at least 1 px', () => {
    expect(fit({ w: 1920, h: 1080 })).toEqual({ w: 480, h: 270 });
    expect(fit({ w: 1080, h: 1920 })).toEqual({ w: 270, h: 480 });
    expect(fit({ w: 200, h: 100 })).toEqual({ w: 200, h: 100 });
    expect(fit({ w: 10000, h: 1 })).toEqual({ w: 480, h: 1 });
  });
  it('area-averages: a 2x2 checker of black/white becomes mid grey', () => {
    const src = new Uint8Array([0, 0, 0, 255, 255, 255, 255, 255, 255, 255, 255, 255, 0, 0, 0, 255]);
    expect([...downscale(src, 2, 2, 1, 1)]).toEqual([128, 128, 128, 255]);
  });
  it('a solid colour stays that colour', () => {
    const src = new Uint8Array(9 * 7 * 4);
    for (let i = 0; i < 63; i++) src.set([10, 20, 30, 255], i * 4);
    const out = downscale(src, 9, 7, 4, 3);
    for (let i = 0; i < 12; i++) expect([...out.subarray(i * 4, i * 4 + 4)]).toEqual([10, 20, 30, 255]);
  });
});

describe('thumbnail', () => {
  it('a 1920x1080 PNG screenshot becomes a 480x270 PNG data URI', () => {
    const t = thumbnail(png(1920, 1080), 'image/png');
    expect(t.ok).toBe(true);
    if (!t.ok) return;
    expect(t.dataUri.startsWith('data:image/png;base64,')).toBe(true);
    expect({ w: t.w, h: t.h }).toEqual({ w: THUMB_EDGE, h: 270 });
    expect(PNG.sync.read(decodeUri(t.dataUri))).toMatchObject({ width: 480, height: 270 });
  });
  it('a large JPEG becomes a JPEG thumbnail', () => {
    const t = thumbnail(jpg(1200, 800), 'image/jpeg');
    expect(t.ok && t.dataUri.startsWith('data:image/jpeg;base64,')).toBe(true);
    if (t.ok) expect(jpeg.decode(decodeUri(t.dataUri))).toMatchObject({ width: 480, height: 320 });
  });
  it('a small image within the edge is posted as-is (gif and webp included)', () => {
    const small = png(100, 60);
    const t = thumbnail(small, 'image/png');
    expect(t.ok && decodeUri(t.dataUri).equals(Buffer.from(small))).toBe(true);
    const gif = new Uint8Array([0x47, 0x49, 0x46, 0x38, 0x39, 0x61, 0x10, 0x00, 0x10, 0x00, 0, 0, 0]);
    expect(thumbnail(gif, 'image/gif')).toMatchObject({ ok: true, w: 16, h: 16 });
  });
  it('caps: over 8 MB encoded or over 24 MP is a file row, decided before any decode', () => {
    const big = new Uint8Array(THUMB_MAX_ENCODED + 1);
    big.set(png(10, 10));
    expect(thumbnail(big, 'image/png')).toEqual({ ok: false, reason: 'over the 8 MB thumbnail cap' });
    // a header claiming 6000x5000 (30 MP): refused from the header alone
    const hdr = png(1, 1);
    const dv = new DataView(hdr.buffer);
    dv.setUint32(16, 6000); dv.setUint32(20, 5000);
    expect(thumbnail(hdr, 'image/png')).toEqual({ ok: false, reason: 'over the 24 megapixel thumbnail cap' });
  });
  it('a large gif/webp has no decoder: a file row', () => {
    const gif = new Uint8Array(PASS_THROUGH_MAX + 10);
    gif.set([0x47, 0x49, 0x46, 0x38, 0x39, 0x61, 0x00, 0x04, 0x00, 0x03]);
    expect(thumbnail(gif, 'image/gif')).toMatchObject({ ok: false });
  });
  it('corrupt data is a reason, never a throw', () => {
    const bad = png(800, 600).slice(0, 200);
    const t = thumbnail(bad, 'image/png');
    expect(t.ok).toBe(false);
  });
});
