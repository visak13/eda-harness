// Numbers the video states, read from the code they describe, so a caption cannot drift from it.
//   node scripts/code-facts.mjs          → writes src/code-facts.json
//   node scripts/code-facts.mjs --check  → exits 1 if src/code-facts.json no longer matches the code
// render-all.mjs and stills.mjs run it first; a constant that moved or was renamed fails the render.
import path from "node:path";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const edp8 = path.resolve(root, "../../src/edp8");

// [key, file under v8/src/edp8, python constant]
const FACTS = [
  ["contextBudgetBytes", "bundles.py", "_CONTEXT_BUDGET_B"], // chapter 4: context() default byte cap
];

const facts = {};
for (const [key, file, name] of FACTS) {
  const src = readFileSync(path.join(edp8, file), "utf8");
  const m = src.match(new RegExp(`^${name}\\s*=\\s*([0-9_]+)`, "m"));
  if (!m) throw new Error(`code-facts: ${name} not found in v8/src/edp8/${file}; update the video and this table`);
  facts[key] = Number(m[1].replaceAll("_", ""));
  facts[`${key}Source`] = `v8/src/edp8/${file} ${name}`;
}

// The runtime default is the settings registry's (settings.get); bundles.py holds the same number as its
// fallback. The video states one number, so the two must agree.
const registry = readFileSync(path.resolve(root, "../../../edp-contracts/src/edp_contracts/settings/keys_board.py"), "utf8");
const reg = registry.match(/declare\("board\.context_budget_b",\s*"EDP8_CONTEXT_BUDGET_B",\s*"int",\s*([0-9_]+)/);
if (!reg) throw new Error("code-facts: board.context_budget_b not declared in edp_contracts/settings/keys_board.py");
if (Number(reg[1].replaceAll("_", "")) !== facts.contextBudgetBytes)
  throw new Error(`code-facts: keys_board.py board.context_budget_b=${reg[1]} disagrees with bundles._CONTEXT_BUDGET_B=${facts.contextBudgetBytes}`);
facts.contextBudgetBytesSource += " = edp_contracts/settings/keys_board.py board.context_budget_b";

const out = path.join(root, "src/code-facts.json");
const text = JSON.stringify(facts, null, 2) + "\n";
if (process.argv.includes("--check")) {
  const now = readFileSync(out, "utf8");
  if (now !== text) { console.error(`code-facts: src/code-facts.json is stale; run node scripts/code-facts.mjs`); process.exit(1); }
  console.log("code-facts: up to date");
} else {
  writeFileSync(out, text);
  console.log(`code-facts: ${JSON.stringify(facts)}`);
}
