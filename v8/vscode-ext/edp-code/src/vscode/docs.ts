// Board docs as read-only editor documents (C15 s-e14d316891; design §14.2): `edp-doc:/<id>/v<N>.md` is
// served from `GET /v1/docs/<id>?version=N` with the viewer's token, so a doc opens in an editor tab with
// VS Code's own outline and search, and the version in the URI is the version read. The provider stays as
// it is for C16 (its reader and version diff read the same URIs); only `openDoc` is the swappable opener
// (architect m-3a4c731cd7).
import * as vscode from 'vscode';
import type { Board } from '../core/api';
import { DOC_SCHEME, docPath, parseDocPath } from '../core/docUri';

export class DocProvider implements vscode.TextDocumentContentProvider {
  constructor(private board: () => Board) {}

  async provideTextDocumentContent(uri: vscode.Uri): Promise<string> {
    const at = parseDocPath(uri.path);
    if (!at) throw new Error(`EDP: not a board doc: ${uri.path}`);
    const d = await this.board().doc(at.id, at.version);
    return d.body_md ?? '';
  }

  register(): vscode.Disposable {
    return vscode.workspace.registerTextDocumentContentProvider(DOC_SCHEME, this);
  }
}

export const docUri = (id: string, version: number) => vscode.Uri.from({ scheme: DOC_SCHEME, path: docPath(id, version) });

/** C16: the reader editor, once registered; the opener goes through it. */
let reader: { open(id: string, version: number, source?: string | null): Promise<void> } | null = null;
export const setReader = (r: typeof reader) => { reader = r; };

/** Open a doc version in an editor tab: the EDP reader (C16), or, before it is registered, VS Code's Markdown
 *  preview (the text itself when the preview is unavailable). `source`: the ticket it was opened from. */
export async function openDoc(id: string, version: number, source?: string | null): Promise<void> {
  const uri = docUri(id, version);
  // fetches now: a refusal surfaces here, not in a blank tab
  if (reader) { await vscode.workspace.openTextDocument(uri); await reader.open(id, version, source); return; }
  // fetches now: a refusal surfaces here, not in a blank preview (the .md path makes it markdown)
  const doc = await vscode.workspace.openTextDocument(uri);
  try { await vscode.commands.executeCommand('markdown.showPreview', uri); }
  catch { await vscode.window.showTextDocument(doc, { preview: true }); }
}
