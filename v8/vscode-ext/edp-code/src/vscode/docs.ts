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

/** Open a doc version in an editor tab: VS Code's Markdown preview, or the text itself when the preview is
 *  unavailable. C16 replaces this opener with its reader editor. */
export async function openDoc(id: string, version: number): Promise<void> {
  const uri = docUri(id, version);
  // fetches now: a refusal surfaces here, not in a blank preview (the .md path makes it markdown)
  const doc = await vscode.workspace.openTextDocument(uri);
  try { await vscode.commands.executeCommand('markdown.showPreview', uri); }
  catch { await vscode.window.showTextDocument(doc, { preview: true }); }
}
