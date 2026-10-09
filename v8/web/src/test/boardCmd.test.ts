// S9 guard G1: a relative EDP8_BOARD_CMD resolves against v8/ (the board's cwd), and a missing one names where it looked.
import path from "node:path";
import { describe, expect, it } from "vitest";
import { resolveBoardCmd } from "../../e2e/boardCmd";

const REPO = path.resolve("/work/eda-base3/v8");

describe("resolveBoardCmd", () => {
  it("defaults to uv run edp8-board", () => {
    expect(resolveBoardCmd(undefined, REPO)).toEqual(["uv", "run", "edp8-board"]);
  });

  it("leaves a bare launcher on PATH alone", () => {
    expect(resolveBoardCmd("edp8-board", REPO, () => false)).toEqual(["edp8-board"]);
  });

  it("makes a relative path absolute against v8/, keeping the args", () => {
    const want = path.resolve(REPO, ".venv/Scripts/edp8-board.exe");
    expect(resolveBoardCmd(".venv/Scripts/edp8-board.exe --x 1", REPO, (p) => p === want)).toEqual([want, "--x", "1"]);
  });

  it("treats a backslash path (the PowerShell form) as a path, not a bare launcher", () => {
    const bsl = String.fromCharCode(92);
    const want = path.resolve(REPO, ".venv/Scripts/edp8-board.exe");
    expect(resolveBoardCmd([".venv", "Scripts", "edp8-board.exe"].join(bsl), REPO, (p) => p === want)).toEqual([want]);
    expect(() => resolveBoardCmd([".venv", "Scripts", "nope.exe"].join(bsl), REPO, () => false)).toThrow(/not found/);
  });

  it("quotes a resolved path that contains spaces (shell:true splits on them)", () => {
    const spaced = path.resolve("/work/my repo/v8");
    const want = path.resolve(spaced, ".venv/Scripts/edp8-board.exe");
    expect(resolveBoardCmd(".venv/Scripts/edp8-board.exe --x", spaced, (p) => p === want)).toEqual([`"${want}"`, "--x"]);
  });

  it("accepts a launcher found with .exe added", () => {
    const base = path.resolve(REPO, ".venv/Scripts/edp8-board");
    expect(resolveBoardCmd(".venv/Scripts/edp8-board", REPO, (p) => p === `${base}.exe`)[0]).toBe(base);
  });

  it("throws naming the resolved path when it is missing", () => {
    expect(() => resolveBoardCmd("../.venv/Scripts/edp8-board", REPO, () => false)).toThrow(
      /EDP8_BOARD_CMD "\.\.\/\.venv\/Scripts\/edp8-board" not found \(resolved to .+\); pass an absolute venv path/,
    );
  });

  it("does not touch an absolute path", () => {
    const abs = path.resolve("/opt/venv/bin/edp8-board");
    expect(resolveBoardCmd(abs, REPO, () => false)).toEqual([abs]);
  });
});
