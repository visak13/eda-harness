import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";

// s-aa76c83998 (design-63db8a7d42 item H, owner): the "Needs you" view and the "Waiting on you" tag are retired.
// The words must not come back anywhere in the web source, tests included. The patterns are built from parts so this
// file does not trip itself.
const RETIRED = [["Needs", " you\b"], ["Waiting", " on you"]].map(([a, b]) => new RegExp(a + b));
const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");
const SELF = join(SRC, "test", "retiredLabels.test.ts");

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    return statSync(p).isDirectory() ? files(p) : [p];
  });
}

it('no file under web/src says "Needs you" or "Waiting on you"', () => {
  const hits = files(SRC)
    .filter((p) => p !== SELF && /\.(tsx?|css|json|md|html)$/.test(p))
    .flatMap((p) => readFileSync(p, "utf8").split("\n")
      .map((line, i) => (RETIRED.some((r) => r.test(line)) ? `${p.slice(SRC.length + 1)}:${i + 1}` : "")))
    .filter(Boolean);
  expect(hits).toEqual([]);
});
