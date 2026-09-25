// C21 s-987e1154ca: the reader's doc column and its extras fill the editor at any width (owner m-2b78c708eb:
// a 980px cap, and zen's centred layout, left bands empty in full screen); the outline keeps 160-240px, the 640px rule stays.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const css = readFileSync(resolve(import.meta.dirname, '../webview/reader.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');

/** Every innermost rule as [selector list, declarations]; rules inside @media are included (prelude dropped). */
function rules(src: string): Array<[string, string]> {
  const out: Array<[string, string]> = [];
  const re = /([^{}]+)\{([^{}]*)\}/g;
  for (let m; (m = re.exec(src)); ) out.push([m[1].trim(), m[2]]);
  return out;
}

/** True when one selector in the list targets the element itself (not a descendant such as `.rd-doc pre`). */
const targets = (selectors: string, cls: string) =>
  selectors.split(',').some((s) => (s.trim().split(/[\s>+~]+/).pop() ?? '').split(/(?=[.#:[])/).includes(`.${cls}`));

describe('reader.css widths', () => {
  it('no max-width on .rd-doc or .rd-extras, in any rule or media query', () => {
    const caps = rules(css).filter(([sel, body]) => (targets(sel, 'rd-doc') || targets(sel, 'rd-extras')) && /(^|[;\s])max-width\s*:/.test(body));
    expect(caps).toEqual([]);
    expect(css).not.toMatch(/980px/);
  });
  it('the doc column is the grid\'s 1fr track; the outline keeps 160-240px', () => {
    const layout = rules(css).find(([sel]) => sel === '.rd-layout')?.[1] ?? '';
    expect(layout).toMatch(/grid-template-columns:\s*minmax\(160px,\s*240px\)\s+minmax\(0,\s*1fr\)/);
    const main = rules(css).find(([sel]) => sel === '.rd-main')?.[1] ?? '';
    expect(main).not.toMatch(/max-width|width\s*:/);
  });
  it('the 640px narrow view still hides the outline', () => {
    expect(css).toMatch(/@media \(max-width: 640px\)\s*\{\s*\.rd-layout \{ grid-template-columns: minmax\(0, 1fr\); \}\s*\.rd-outline \{ display: none; \}/);
  });
  it('full screen (zen) is not centred: the editor, and so the reader, takes the whole window', () => {
    const pkg = JSON.parse(readFileSync(resolve(import.meta.dirname, '../package.json'), 'utf8'));
    expect(pkg.contributes.configurationDefaults['zenMode.centerLayout']).toBe(false);
  });
  it('the check catches a cap (self-test)', () => {
    const capped = rules('.rd-doc { max-width: 980px; } .rd-doc pre { max-width: 10px; } .rd-extras, .x { max-width: 60ch; }');
    expect(capped.filter(([sel, body]) => (targets(sel, 'rd-doc') || targets(sel, 'rd-extras')) && /max-width/.test(body)).map(([s]) => s))
      .toEqual(['.rd-doc', '.rd-extras, .x']);
  });
});
