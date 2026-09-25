import { test as base } from "@playwright/test";
import { startBoard, stopBoard } from "./board";

export { expect } from "@playwright/test";
export type { Locator, Page } from "@playwright/test";

/**
 * ONE BOARD PER SPEC FILE. Every spec seeds its own scenario into the board; on a single shared
 * board (the pre-acceptance globalSetup design) those seeds accumulate across files — the owner's
 * Sign-offs tab read 26, the gates list had 23 `gate-kind`s, the Decisions/Library plates drifted
 * 2–4 % from their baselines — so a spec's assertions depended on which files ran before it
 * (acceptance finding, 2026-09-08). `boardFile` is a worker-scoped OPTION: Playwright starts a
 * fresh worker whenever a worker option's value changes, so each file's `test.use({ boardFile })`
 * gets its own worker, its own board (the `board` fixture below) and its own temp DB, and the
 * board is torn down when that worker ends. The base URL reaches the specs through
 * process.env.EDP8_E2E_BASE (set by startBoard in this worker) — read it LAZILY, at test time.
 */
export const test = base.extend<{}, { boardFile: string; boardEnv: Record<string, string>; board: { base: string; epic: string } }>({
  boardFile: ["shared", { scope: "worker", option: true }],
  // Extra env for this file's board (applied last); a different value is a different worker + board.
  boardEnv: [{}, { scope: "worker", option: true }],
  board: [
    async ({ boardFile: _boardFile, boardEnv }, use) => {
      const seeded = await startBoard(boardEnv);
      await use(seeded);
      stopBoard();
    },
    { scope: "worker", auto: true },
  ],
  baseURL: async ({ board }, use) => {
    await use(board.base);
  },
});

/** The spawned board's base URL — valid only inside a test (after the worker's `board` fixture ran). */
export const BASE = (): string => process.env.EDP8_E2E_BASE!;
/** The epic startBoard seeds ("Spike epic"). */
export const EPIC = (): string => process.env.EDP8_E2E_EPIC!;
