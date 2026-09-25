// EDP: Tag selection on board… (design §4 item 1; strategyll-ab18531441 §1, §3).
// anchor (captured FIRST) -> route (C4, design-10b21760d9 §4.1):
// - chat view resolved in this window -> reveal it, code chip in the open thread's composer;
// - otherwise the S5 palette chain: person -> ticket -> note -> kind -> POST /v1/messages.
import * as vscode from 'vscode';
import { buildAnchor, type Anchor, type Sel } from '../core/anchor';
import type { Board, MessageKind } from '../core/api';
import { boardTicketUrl } from '../core/boardLinks';
import { render } from '../core/render';
import { liveSeats, people, ticketChoices } from '../core/seats';
import { tagRoute } from '../core/tagRoute';
import { credsOrSignIn } from './auth';
import { pick, separator } from './pickers';
import { gitApi, headAndDirty } from './repo';

type Item = vscode.QuickPickItem & { id?: string };
const KINDS: MessageKind[] = ['question', 'steer', 'finding', 'note'];

/** The chat side of the route (ChatController): no view resolved in this window = the palette chain. */
export interface TagTarget {
  readonly chatResolved: boolean;
  readonly threadOpen: boolean;
  /** reveal the view and put the chip in the open thread's composer; `pickFirst` opens the thread picker first */
  insertChip(anchor: Anchor, truncated: boolean, pickFirst: boolean): Promise<void>;
}

export async function tagSelection(ctx: vscode.ExtensionContext, board: () => Board, boardUrl: () => string, chat?: TagTarget): Promise<void> {
  const captured = await captureAnchor();
  if (!captured) return;
  const route = tagRoute({ chatResolved: !!chat?.chatResolved, threadOpen: !!chat?.threadOpen });
  if (chat && route !== 'palette') return chat.insertChip(captured.anchor, captured.truncated, route === 'pickThenChip');
  return paletteChain(ctx, board, boardUrl, captured.anchor, captured.truncated);
}

/** The anchor, taken from the active editor before any picker or view takes focus. */
async function captureAnchor(): Promise<{ anchor: Anchor; truncated: boolean } | undefined> {
  const editor = vscode.window.activeTextEditor;
  if (!editor) { void vscode.window.showInformationMessage('EDP: open a file and select lines to tag.'); return; }
  const doc = editor.document;
  if (doc.uri.scheme !== 'file') { void vscode.window.showWarningMessage('EDP: only files on disk can be tagged.'); return; }

  // 1. capture the anchor before any picker takes focus
  const a = await anchorFor(doc, editor.selection);
  if ('error' in a) { void vscode.window.showWarningMessage(`EDP: ${a.error}`); return; }
  return a;
}

/** The S5 anchor of a range of a file on disk (the Tag selection, and C20's code quote from a comment box). */
export async function anchorFor(doc: vscode.TextDocument, sel: vscode.Range): Promise<{ anchor: Anchor; truncated: boolean } | { error: string }> {
  const s: Sel = { startLine: sel.start.line, startChar: sel.start.character, endLine: sel.end.line, endChar: sel.end.character, isEmpty: sel.isEmpty };
  const lines = Array.from({ length: doc.lineCount }, (_, n) => doc.lineAt(n).text);
  // dirty is judged on these captured lines (and isDirty at capture), not on the buffer after the git awaits
  const snap = { lines, isDirty: doc.isDirty };
  const git = await headAndDirty(await gitApi(), doc, snap);
  const repoRoot = git.repoRoot ?? vscode.workspace.getWorkspaceFolder(doc.uri)?.uri.fsPath;
  if (!repoRoot) return { error: 'this file is outside every git repo and workspace folder; it cannot be tagged.' };
  try {
    return buildAnchor({ repoRoot, fsPath: doc.uri.fsPath, lines, sel: s, commit: git.commit, dirty: git.dirty });
  } catch (e) {
    return { error: (e as Error).message };
  }
}

/** The S5 palette chain, unchanged: person -> ticket -> note -> kind -> send. */
async function paletteChain(ctx: vscode.ExtensionContext, board: () => Board, boardUrl: () => string, anchor: Anchor, truncated: boolean): Promise<void> {
  if (!(await credsOrSignIn(ctx, board))) return;
  const client = board();

  // 2. person: humans (marked) and live agent seats
  let seats: ReturnType<typeof liveSeats> = [];
  const person = await pick<Item>(`EDP: tag ${anchor.path}:L${anchor.line_start}-${anchor.line_end} to…`, async () => {
    const [ps, ss] = await Promise.all([client.participants(), client.sessions()]);
    seats = liveSeats(ss, ps);
    return people(ps, seats).map(p => ({
      label: `${p.type === 'human' ? '$(person)' : '$(hubot)'} ${p.handle}`, description: p.role,
      detail: p.type === 'human' ? 'human' : `agent seat · live${seatTicket(seats, p.id)}`, id: p.id,
    }));
  }, 'Person: humans and live agent seats');
  if (!person?.id) return;
  const personId = person.id;

  // 3. ticket: theirs first, then any open ticket
  const ticket = await pick<Item>(`EDP: ticket for ${person.label.replace(/^\$\([^)]*\)\s*/, '')}`, async () => {
    const { theirs, others } = ticketChoices(await client.tickets(), personId, seats);
    const item = (t: { id: string; title: string; status: string; kind: string }): Item => ({ label: t.id, description: t.title, detail: `${t.kind} · ${t.status}`, id: t.id });
    return [
      ...(theirs.length ? [separator('Their open tickets') as Item, ...theirs.map(item)] : []),
      separator('Any open ticket') as Item, ...others.map(item),
    ];
  }, 'Ticket: the thread the message lands on');
  if (!ticket?.id) return;

  // 4. note, then kind
  const note = await vscode.window.showInputBox({
    title: `EDP: note to ${person.label.replace(/^\$\([^)]*\)\s*/, '')} on ${ticket.id}`, ignoreFocusOut: true,
    placeHolder: 'What should they look at? (only the primary selection is anchored)',
    validateInput: v => (v.trim() ? undefined : 'A note is required'),
  });
  if (!note?.trim()) return;
  const kind = await vscode.window.showQuickPick(KINDS, { title: 'EDP: message kind', placeHolder: 'question', ignoreFocusOut: true });
  if (!kind) return;

  // 5. send
  try {
    const m = await client.sendMessage({ ticket_id: ticket.id, to: personId, kind: kind as MessageKind, text: render(anchor, note, truncated), code_context: anchor });
    const open = await vscode.window.showInformationMessage(`EDP: tagged ${person.label.replace(/^\$\([^)]*\)\s*/, '')} on ${ticket.id} (${m.id})`, 'Open ticket');
    if (open) void vscode.env.openExternal(vscode.Uri.parse(boardTicketUrl(boardUrl(), ticket.id)));
  } catch (e) {
    void vscode.window.showErrorMessage(`EDP: ${(e as Error).message}`);
  }
}

function seatTicket(seats: ReturnType<typeof liveSeats>, id: string): string {
  const t = seats.find(s => s.participant_id === id)?.ticket_id;
  return t ? ` on ${t}` : '';
}
