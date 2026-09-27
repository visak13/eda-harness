// t-b2f8859d30 (owner art-678346d6e2): the e2e suite builds the SPA into a PRIVATE dir and its board serves that dir
// (EDP8_WEB_DIST). It used to build into the shared src/edp8/webapp/dist, which the fleet board serves: a seat's e2e
// run shipped S14's bundle to the fleet before the fleet board had S14's routes, and /ui/design crashed.
// Only the deploy (edp.ps1 update, CI) writes the shared dist. Kept free of Playwright imports so vitest can test it.
import { createHash } from "node:crypto";
import os from "node:os";
import path from "node:path";

/** The shared dist the fleet board serves. The e2e harness never writes or serves it. */
export function sharedDist(repoDir: string): string {
  return path.join(repoDir, "src", "edp8", "webapp", "dist");
}

/** One private dist per checkout, under the OS temp dir; kept between runs so an up-to-date build is reused.
 *  EDP8_E2E_DIST overrides it (still never the shared dist). */
export function e2eDist(repoDir: string, env: NodeJS.ProcessEnv = process.env): string {
  const pinned = env.EDP8_E2E_DIST;
  const dir = pinned
    ? path.resolve(pinned)
    : path.join(os.tmpdir(), `edp8-e2e-dist-${createHash("sha256").update(path.resolve(repoDir).toLowerCase()).digest("hex").slice(0, 12)}`);
  const shared = path.resolve(sharedDist(repoDir));
  const rel = path.relative(shared, dir);
  if (!rel || (!rel.startsWith("..") && !path.isAbsolute(rel))) throw new Error(`e2e dist ${dir} is the shared dist; pick a private dir`);
  return dir;
}

/** The build env: EDP8_WEB_OUT sends vite's output to the private dir; the base is pinned to /ui/. */
export function e2eBuildEnv(repoDir: string, env: NodeJS.ProcessEnv = process.env): NodeJS.ProcessEnv {
  return { ...env, EDP8_WEB_BASE: "/ui/", EDP8_WEB_OUT: e2eDist(repoDir, env) };
}

/** What the spec board adds to its env so it serves the private build. */
export function e2eBoardDistEnv(repoDir: string, env: NodeJS.ProcessEnv = process.env): Record<string, string> {
  return { EDP8_WEB_DIST: e2eDist(repoDir, env) };
}
