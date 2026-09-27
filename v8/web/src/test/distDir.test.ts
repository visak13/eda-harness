// t-b2f8859d30: the e2e harness builds into a private dir and its board serves that dir, never the shared dist the
// fleet board serves (web/e2e/distDir.ts). The board side (EDP8_WEB_DIST honoured by create_app) is pinned by
// tests/test_webapp_serve.py::test_board_serves_the_private_dist_named_by_edp8_web_dist.
import path from "node:path";
import { describe, expect, it } from "vitest";
import { e2eBoardDistEnv, e2eBuildEnv, e2eDist, sharedDist } from "../../e2e/distDir";

const REPO = path.resolve("/work/eda-base3/v8");

describe("e2e private dist", () => {
  it("is outside the shared dist, and the build and the board both use it", () => {
    const dir = e2eDist(REPO, {});
    const rel = path.relative(sharedDist(REPO), dir);
    expect(rel.startsWith("..") || path.isAbsolute(rel)).toBe(true);
    const build = e2eBuildEnv(REPO, { EDP8_WEB_OUT: "../src/edp8/webapp/dist", EDP8_WEB_BASE: "/app/" });
    expect(build.EDP8_WEB_OUT).toBe(dir); // a shell's stray EDP8_WEB_OUT can't point the build at the shared dist
    expect(build.EDP8_WEB_BASE).toBe("/ui/");
    expect(e2eBoardDistEnv(REPO, {})).toEqual({ EDP8_WEB_DIST: dir });
  });

  it("is stable per checkout and differs between checkouts", () => {
    expect(e2eDist(REPO, {})).toBe(e2eDist(REPO, {}));
    expect(e2eDist(REPO, {})).not.toBe(e2eDist(path.resolve("/work/clone/v8"), {}));
  });

  it("refuses an override that names the shared dist or a dir inside it", () => {
    expect(() => e2eDist(REPO, { EDP8_E2E_DIST: sharedDist(REPO) })).toThrow(/shared dist/);
    expect(() => e2eDist(REPO, { EDP8_E2E_DIST: path.join(sharedDist(REPO), "x") })).toThrow(/shared dist/);
    expect(e2eDist(REPO, { EDP8_E2E_DIST: path.resolve("/tmp/mine") })).toBe(path.resolve("/tmp/mine"));
  });
});
