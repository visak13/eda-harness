import { useQuery } from "@tanstack/react-query";

// t-b2f8859d30 (owner art-678346d6e2): a bundle built after the board started can call routes the running board
// does not have yet (S14's /v1/workflows shape on a pre-S14 board crashed /ui/design). The build stamps where it
// came from (vite.config.ts `define`); the board's /v1/health says when it started and at which rev.
//
// "Newer than the board" is judged by time first: the board's git_rev is read from .git on each call, so it names
// the checkout's HEAD, not the code the process loaded; only started_at dates that code. A bundle built after the
// board started may carry code the board lacks, unless both name the same rev and the build tree was clean.

export interface BuildStamp { rev: string; dirty: boolean; at: string; version?: string }
export interface BoardHealth { git_rev?: string | null; started_at?: string | null; version?: string | null }

declare const __EDP_BUILD__: BuildStamp | undefined;

/** This bundle's stamp; null in a dev server or a test run without the define. */
export function buildStamp(): BuildStamp | null {
  return typeof __EDP_BUILD__ !== "undefined" && __EDP_BUILD__ ? __EDP_BUILD__ : null;
}

/** The build stamps 7 characters of the rev, the board up to 12: the same commit when one is a prefix of the other. */
export function sameRev(a: string, b: string): boolean {
  const x = a.trim().toLowerCase(), y = b.trim().toLowerCase();
  return x.length > 0 && y.length > 0 && (x.startsWith(y) || y.startsWith(x));
}

/** A git object name (hex), as opposed to a tag or branch name the board may report in git_rev ("v0.10.6"). */
const isHexRev = (rev: string): boolean => /^[0-9a-f]{7,40}$/i.test(rev.trim());

/** Whether semver `a` is newer than `b` (major.minor.patch; a pre-release suffix is ignored). Unparsable: never newer. */
export function semverNewer(a: string | null | undefined, b: string | null | undefined): boolean {
  const parse = (v: string | null | undefined): number[] | null => {
    const m = /^v?(\d+)\.(\d+)\.(\d+)/.exec((v ?? "").trim());
    return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : null;
  };
  const x = parse(a), y = parse(b);
  if (!x || !y) return false;
  for (let i = 0; i < 3; i++) if (x[i] !== y[i]) return x[i] > y[i];
  return false;
}

export function needsBoardRestart(build: BuildStamp | null, board: BoardHealth | null | undefined): boolean {
  if (!build || !board?.started_at) return false;
  if (!isHexRev(board.git_rev ?? "")) return false; // a tag or a branch name is not a commit: no rev to compare, stay quiet
  const built = Date.parse(build.at);
  const started = Date.parse(board.started_at);
  if (Number.isNaN(built) || Number.isNaN(started) || built <= started) return false;
  return build.dirty || !board.git_rev || !sameRev(board.git_rev, build.rev);
}

/** /v1/health is outside the envelope and needs no token. */
export async function getBoardHealth(): Promise<BoardHealth> {
  const r = await fetch("/v1/health", { cache: "no-store" });
  if (!r.ok) throw new Error(`health ${r.status}`);
  return (await r.json()) as BoardHealth;
}

// The board and the page can skew in two directions, judged by ONE check on ONE /v1/health query:
//   behind  — this bundle is newer than the board (needsBoardRestart above): the board needs a restart.
//   updated — the board's release is newer than this bundle's (boardNewerThanPage below): a page left open across an update.
export const UPDATE_CHECK_MS = 60_000;
let loadedVersion: string | null = null;

/** Test hook: forget the version this page loaded with. */
export function resetLoadedVersion(): void { loadedVersion = null; }

/** The board is newer than this page when its release (semver) is newer than the one this bundle shipped as, or newer than the
 *  one the page first saw from the board (it was updated while the tab stayed open). Judged by version only: git_rev may be a
 *  tag or a branch name, and a bundle and a board on the same release never disagree (qa report-689ceb50f0, fail 1). */
export function boardNewerThanPage(build: BuildStamp | null, board: BoardHealth | null | undefined, loaded: string | null): boolean {
  if (!board?.version) return false;
  return semverNewer(board.version, build?.version ?? loaded); // the page's own release; a bundle with no stamp falls back to what it first saw
}

export interface BoardSkew { behind: boolean; updated: boolean }

/** The one place the page asks whether it and the board agree. Checked on focus and every minute; a failed probe
 *  (board restarting) keeps the last answer instead of flapping, so a banner leaves only after a good answer. */
export function useBoardSkew(build: BuildStamp | null = buildStamp()): BoardSkew {
  const q = useQuery({
    queryKey: ["board-health"], queryFn: getBoardHealth, retry: false,
    refetchInterval: UPDATE_CHECK_MS, refetchOnWindowFocus: "always", staleTime: 0,
  });
  const v = q.data?.version ?? null;
  if (v && loadedVersion === null) loadedVersion = v;
  return { behind: needsBoardRestart(build, q.data), updated: boardNewerThanPage(build, q.data, loadedVersion) };
}
