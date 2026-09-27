import { useQuery } from "@tanstack/react-query";

// t-b2f8859d30 (owner art-678346d6e2): a bundle built after the board started can call routes the running board
// does not have yet (S14's /v1/workflows shape on a pre-S14 board crashed /ui/design). The build stamps where it
// came from (vite.config.ts `define`); the board's /v1/health says when it started and at which rev.
//
// "Newer than the board" is judged by time first: the board's git_rev is read from .git on each call, so it names
// the checkout's HEAD, not the code the process loaded; only started_at dates that code. A bundle built after the
// board started may carry code the board lacks, unless both name the same rev and the build tree was clean.

export interface BuildStamp { rev: string; dirty: boolean; at: string }
export interface BoardHealth { git_rev?: string | null; started_at?: string | null }

declare const __EDP_BUILD__: BuildStamp | undefined;

/** This bundle's stamp; null in a dev server or a test run without the define. */
export function buildStamp(): BuildStamp | null {
  return typeof __EDP_BUILD__ !== "undefined" && __EDP_BUILD__ ? __EDP_BUILD__ : null;
}

export function needsBoardRestart(build: BuildStamp | null, board: BoardHealth | null | undefined): boolean {
  if (!build || !board?.started_at) return false;
  const built = Date.parse(build.at);
  const started = Date.parse(board.started_at);
  if (Number.isNaN(built) || Number.isNaN(started) || built <= started) return false;
  return build.dirty || !board.git_rev || board.git_rev !== build.rev;
}

/** /v1/health is outside the envelope and needs no token. */
export async function getBoardHealth(): Promise<BoardHealth> {
  const r = await fetch("/v1/health", { cache: "no-store" });
  if (!r.ok) throw new Error(`health ${r.status}`);
  return (await r.json()) as BoardHealth;
}

/** True while this bundle runs ahead of the board. Rechecked every minute, so the banner leaves after a restart. */
export function useBoardBehind(build: BuildStamp | null = buildStamp()): boolean {
  const q = useQuery({ queryKey: ["board-health"], queryFn: getBoardHealth, enabled: Boolean(build), refetchInterval: 60_000, retry: false });
  return needsBoardRestart(build, q.data);
}
