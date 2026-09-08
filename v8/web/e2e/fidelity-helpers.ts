import pixelmatch from "pixelmatch";
import { PNG } from "pngjs";

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * Assert a measured geometry value against its expected design token, within `tol` px.
 * Throws with the measured-vs-expected message criterion c-7c51c6b69b requires, e.g.
 *   `sidebar width — measured 200, expected 216 (Δ-16.0 > 1px)`
 */
export function expectPx(actual: number, expected: number, label: string, tol = 1): void {
  const delta = actual - expected;
  if (Math.abs(delta) > tol) {
    throw new Error(
      `${label} — measured ${actual}, expected ${expected} (Δ${delta.toFixed(1)} > ${tol}px)`,
    );
  }
}

/** Read a PNG (RGBA) from a Buffer of encoded PNG bytes. */
export function readPng(buffer: Buffer): PNG {
  return PNG.sync.read(buffer);
}

/** Crop the RGBA region `rect` out of `src` into a fresh w*h*4 Buffer (row-major, stride src.width*4). */
function crop(src: PNG, rect: Rect): Buffer {
  const out = Buffer.alloc(rect.w * rect.h * 4);
  const srcStride = src.width * 4;
  const dstStride = rect.w * 4;
  for (let row = 0; row < rect.h; row++) {
    const srcStart = (rect.y + row) * srcStride + rect.x * 4;
    src.data.copy(out, row * dstStride, srcStart, srcStart + dstStride);
  }
  return out;
}

/**
 * Fraction of pixels that differ between `actual` and `reference` inside `rect`.
 * Both are cropped to the rect and compared with pixelmatch at per-pixel threshold 0.1.
 * Returns diffPixels / (w*h) — the band differing-pixel ratio the README gates at ≤ 0.05.
 */
export function bandDiffRatio(actual: PNG, reference: PNG, rect: Rect): number {
  const a = crop(actual, rect);
  const b = crop(reference, rect);
  const diff = pixelmatch(a, b, undefined, rect.w, rect.h, { threshold: 0.1 });
  return diff / (rect.w * rect.h);
}
