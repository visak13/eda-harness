// WCAG 2.2 relative-luminance + contrast-ratio, computed from the shipped `themes.ts`
// values (never eyeballed from the plates). Cite: W3C WCAG 2.2 Understanding 1.4.3
// (https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html).

function srgbToLinear(c: number): number {
  const s = c / 255;
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

/** Relative luminance 0.2126R + 0.7152G + 0.0722B over linearised sRGB channels. */
export function luminance(hex: string): number {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) throw new Error(`not a 6-digit hex color: ${JSON.stringify(hex)}`);
  const n = parseInt(m[1], 16);
  const r = (n >> 16) & 0xff;
  const g = (n >> 8) & 0xff;
  const b = n & 0xff;
  return 0.2126 * srgbToLinear(r) + 0.7152 * srgbToLinear(g) + 0.0722 * srgbToLinear(b);
}

/** Contrast ratio (L1+0.05)/(L2+0.05), L1 ≥ L2. Range 1..21. */
export function contrastRatio(a: string, b: string): number {
  const la = luminance(a);
  const lb = luminance(b);
  const [hi, lo] = la >= lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}
