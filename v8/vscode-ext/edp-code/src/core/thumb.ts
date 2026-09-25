// Host-side thumbnails for chat attachments (C12 s-85dd35a166; design §13 row C12, architect m-1a33d88bc7).
// The webview never fetches: the host reads an image artifact's bytes and posts a downscaled `data:` URI
// (CSP `img-src data:`). Pure JS decoders (pngjs, jpeg-js, bundled devDependencies) run in a worker thread,
// never on the extension host's own thread, and only under two caps; anything over them is a file row
// with an "open" action. No `vscode` import.
import jpeg from 'jpeg-js';
import { PNG } from 'pngjs';

/** The thumbnail's long edge, px. */
export const THUMB_EDGE = 480;
/** Architect caps (m-1a33d88bc7): at most 8 MB encoded and 24 megapixels decoded. */
export const THUMB_MAX_ENCODED = 8 * 1024 * 1024;
export const THUMB_MAX_PIXELS = 24_000_000;
/** An image already within THUMB_EDGE and this small is posted as-is (every inline type, gif/webp included). */
export const PASS_THROUGH_MAX = 512 * 1024;

export type Dims = { w: number; h: number };
export type Thumb = { ok: true; dataUri: string; w: number; h: number } | { ok: false; reason: string; transient?: true };

const u32 = (b: Uint8Array, o: number) => ((b[o] << 24) | (b[o + 1] << 16) | (b[o + 2] << 8) | b[o + 3]) >>> 0;
const u16be = (b: Uint8Array, o: number) => (b[o] << 8) | b[o + 1];
const u16le = (b: Uint8Array, o: number) => b[o] | (b[o + 1] << 8);
const u24le = (b: Uint8Array, o: number) => b[o] | (b[o + 1] << 8) | (b[o + 2] << 16);

/** Width and height from the header alone (no decode), or null when the header is not what the type says. */
export function imageDims(b: Uint8Array, contentType: string): Dims | null {
  switch (contentType) {
    case 'image/png':
      // signature, then IHDR: length(4) 'IHDR'(4) width(4) height(4)
      if (b.length < 24 || b[0] !== 0x89 || b[12] !== 0x49 || b[13] !== 0x48 || b[14] !== 0x44 || b[15] !== 0x52) return null;
      return { w: u32(b, 16), h: u32(b, 20) };
    case 'image/gif':
      if (b.length < 10 || b[0] !== 0x47 || b[1] !== 0x49 || b[2] !== 0x46) return null;
      return { w: u16le(b, 6), h: u16le(b, 8) };
    case 'image/webp': {
      if (b.length < 30 || String.fromCharCode(...b.subarray(8, 12)) !== 'WEBP') return null;
      const chunk = String.fromCharCode(...b.subarray(12, 16));
      if (chunk === 'VP8X') return { w: u24le(b, 24) + 1, h: u24le(b, 27) + 1 };
      if (chunk === 'VP8L') { const v = b[21] | (b[22] << 8) | (b[23] << 16) | (b[24] << 24); return { w: (v & 0x3fff) + 1, h: ((v >>> 14) & 0x3fff) + 1 }; }
      if (chunk === 'VP8 ') return { w: u16le(b, 26) & 0x3fff, h: u16le(b, 28) & 0x3fff };
      return null;
    }
    case 'image/jpeg': {
      if (b.length < 4 || b[0] !== 0xff || b[1] !== 0xd8) return null;
      let o = 2;
      while (o + 9 < b.length) {
        if (b[o] !== 0xff) { o++; continue; }
        const m = b[o + 1];
        if (m === 0xff) { o++; continue; }
        if (m === 0xd8 || m === 0x01 || (m >= 0xd0 && m <= 0xd7)) { o += 2; continue; }
        // SOF0..SOF15, except DHT (c4), JPG (c8) and DAC (cc)
        if (m >= 0xc0 && m <= 0xcf && m !== 0xc4 && m !== 0xc8 && m !== 0xcc) return { h: u16be(b, o + 5), w: u16be(b, o + 7) };
        o += 2 + u16be(b, o + 2);
      }
      return null;
    }
  }
  return null;
}

/** The size that fits `edge` on its long side, never upscaled, at least 1 px. */
export function fit(d: Dims, edge = THUMB_EDGE): Dims {
  const s = Math.min(1, edge / Math.max(d.w, d.h));
  return { w: Math.max(1, Math.round(d.w * s)), h: Math.max(1, Math.round(d.h * s)) };
}

/** Area-average (box) downscale of RGBA pixels: every source pixel counts once, so text in a screenshot
 *  stays legible instead of aliasing. O(source pixels). */
export function downscale(src: Uint8Array, sw: number, sh: number, dw: number, dh: number): Uint8Array {
  const out = new Uint8Array(dw * dh * 4);
  const acc = new Float64Array(dw * 4);
  const cnt = new Float64Array(dw);
  let dy = 0;
  let yEnd = Math.floor(((dy + 1) * sh) / dh);
  const xMap = new Uint32Array(sw);
  for (let x = 0; x < sw; x++) xMap[x] = Math.min(dw - 1, Math.floor((x * dw) / sw));
  const flush = () => {
    for (let x = 0; x < dw; x++) {
      const n = cnt[x] || 1;
      for (let c = 0; c < 4; c++) out[(dy * dw + x) * 4 + c] = Math.round(acc[x * 4 + c] / n);
    }
    acc.fill(0); cnt.fill(0);
  };
  for (let y = 0; y < sh; y++) {
    while (y >= yEnd && dy < dh - 1) { flush(); dy++; yEnd = Math.floor(((dy + 1) * sh) / dh); }
    const row = y * sw * 4;
    for (let x = 0; x < sw; x++) {
      const d = xMap[x], i = row + x * 4;
      acc[d * 4] += src[i]; acc[d * 4 + 1] += src[i + 1]; acc[d * 4 + 2] += src[i + 2]; acc[d * 4 + 3] += src[i + 3];
      cnt[d]++;
    }
  }
  flush();
  return out;
}

const dataUri = (type: string, b: Uint8Array) => `data:${type};base64,${Buffer.from(b.buffer, b.byteOffset, b.byteLength).toString('base64')}`;

/** A thumbnail for an inline-image artifact, or the reason it is shown as a file row instead. */
export function thumbnail(bytes: Uint8Array, contentType: string): Thumb {
  if (bytes.byteLength > THUMB_MAX_ENCODED) return { ok: false, reason: 'over the 8 MB thumbnail cap' };
  const d = imageDims(bytes, contentType);
  if (!d || !d.w || !d.h) return { ok: false, reason: 'unreadable image header' };
  if (d.w * d.h > THUMB_MAX_PIXELS) return { ok: false, reason: 'over the 24 megapixel thumbnail cap' };
  const t = fit(d);
  if (t.w === d.w && t.h === d.h && bytes.byteLength <= PASS_THROUGH_MAX) return { ok: true, dataUri: dataUri(contentType, bytes), ...d };
  try {
    if (contentType === 'image/png') {
      const img = PNG.sync.read(Buffer.from(bytes.buffer, bytes.byteOffset, bytes.byteLength));
      const png = new PNG({ width: t.w, height: t.h });
      png.data = Buffer.from(downscale(img.data, img.width, img.height, t.w, t.h).buffer);
      return { ok: true, dataUri: dataUri('image/png', PNG.sync.write(png, { deflateLevel: 6 })), ...t };
    }
    if (contentType === 'image/jpeg') {
      const img = jpeg.decode(bytes, { useTArray: true, formatAsRGBA: true, maxResolutionInMP: THUMB_MAX_PIXELS / 1e6, maxMemoryUsageInMB: 512 });
      const enc = jpeg.encode({ data: downscale(img.data, img.width, img.height, t.w, t.h), width: t.w, height: t.h }, 82);
      return { ok: true, dataUri: dataUri('image/jpeg', enc.data), ...t };
    }
  } catch (e) {
    return { ok: false, reason: `could not decode (${(e as Error)?.message?.slice(0, 80) ?? 'error'})` };
  }
  // gif/webp have no bundled decoder: small ones pass through above, larger ones are a file row
  return { ok: false, reason: 'no thumbnail for a large gif/webp' };
}
