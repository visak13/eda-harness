// S8: the board/extension version prompt (core/version.ts decides; this shows it and runs the command on consent).
import * as vscode from 'vscode';
import { check, type Mismatch } from '../core/version';

export const RUN = 'Run in terminal';
export const COPY = 'Copy command';

export async function promptOnMismatch(release: string, boardUrl: string, log: (line: string) => void,
  f: typeof fetch = fetch): Promise<Mismatch | undefined> {
  const m = await check(release, boardUrl, f);
  if (!m) return undefined;
  log(`version mismatch: extension ${m.extension}, board ${m.board}; suggests: ${m.command}`);
  const pick = await vscode.window.showWarningMessage(m.message, { detail: m.command }, RUN, COPY);
  if (pick === RUN) {
    const t = vscode.window.createTerminal({ name: 'Heronry update' });
    t.show();
    t.sendText(m.command, false); // typed, not executed: the person presses Enter
  } else if (pick === COPY) {
    await vscode.env.clipboard.writeText(m.command);
  }
  return m;
}
