// S8 (s-6dcf78f803): the extension and the board it talks to ship from one Heronry release. The extension
// records that release (package.json `heronry.release`); at activation it reads the board's version from the
// unauthenticated GET /v1/health and, when major.minor differ, prompts with the one command that brings them
// together: an older board is updated (`heronry update`), an older extension installs the board's release
// VSIX. No `vscode` import: the host wiring lives in src/vscode/version.ts.

export const REPO = 'visak13/eda-harness';

export type Mismatch = {
  extension: string;
  board: string;
  /** which side is behind */
  behind: 'board' | 'extension';
  message: string;
  /** the shell command the prompt's action runs in a terminal */
  command: string;
};

function majorMinor(v: string): [number, number] | undefined {
  const m = /^v?(\d+)\.(\d+)/.exec(v.trim());
  return m ? [Number(m[1]), Number(m[2])] : undefined;
}

export function vsixUrl(release: string, repo = REPO): string {
  const v = release.replace(/^v/, '');
  return `https://github.com/${repo}/releases/download/v${v}/edp-code-${v}.vsix`;
}

/** Undefined when compatible (same major.minor) or either version is unreadable (never a false alarm). */
export function compare(extension: string, board: string, platform: string = process.platform): Mismatch | undefined {
  const e = majorMinor(extension), b = majorMinor(board);
  if (!e || !b || (e[0] === b[0] && e[1] === b[1])) return undefined;
  const boardBehind = b[0] < e[0] || (b[0] === e[0] && b[1] < e[1]);
  if (boardBehind) {
    return { extension, board, behind: 'board', command: 'heronry update',
      message: `The Heronry board is ${board}; this extension is for ${extension}. Update the board with \`heronry update\`.` };
  }
  const url = vsixUrl(board);
  const file = `edp-code-${board.replace(/^v/, '')}.vsix`;
  const command = platform === 'win32'
    ? `Invoke-WebRequest ${url} -OutFile $env:TEMP\\${file}; code --install-extension $env:TEMP\\${file}`
    : `curl -fsSL -o /tmp/${file} ${url} && code --install-extension /tmp/${file}`;
  return { extension, board, behind: 'extension', command,
    message: `The Heronry board is ${board}; this extension is for ${extension}. Install the extension from the board's release.` };
}

/** The board's version from GET /v1/health (no auth), or undefined when it cannot be read. */
export async function boardVersion(baseUrl: string, f: typeof fetch = fetch, timeoutMs = 5000): Promise<string | undefined> {
  try {
    const r = await f(`${baseUrl.replace(/\/+$/, '')}/v1/health`, { signal: AbortSignal.timeout(timeoutMs), redirect: 'manual' });
    if (!r.ok) return undefined;
    const body = await r.json() as { version?: unknown };
    return typeof body.version === 'string' ? body.version : undefined;
  } catch {
    return undefined;
  }
}

export async function check(extension: string, baseUrl: string, f: typeof fetch = fetch): Promise<Mismatch | undefined> {
  const board = await boardVersion(baseUrl, f);
  return board ? compare(extension, board) : undefined;
}
