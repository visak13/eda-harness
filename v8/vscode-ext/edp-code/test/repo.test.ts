import { describe, expect, it, vi } from 'vitest';
import type { API, Repository } from '../src/vscode/git.d';
import type * as vscode from 'vscode';
import { headAndDirty } from '../src/vscode/repo';

const sha = 'a'.repeat(40);
function fixture() {
  const repo = {
    rootUri: { fsPath: 'C:/repo' }, status: vi.fn(async () => {}),
    state: { HEAD: { commit: sha }, workingTreeChanges: [], indexChanges: [], untrackedChanges: [], mergeChanges: [] },
    show: vi.fn(async () => 'content\n'),
  };
  const api = { getRepository: () => repo as unknown as Repository } as unknown as API;
  const lines = ['content', ''];
  const doc = { uri: { fsPath: 'C:/repo/file.txt' }, isDirty: false, getText: () => lines.join('\r\n'),
    lineCount: lines.length, lineAt: (n: number) => ({ text: lines[n] }) } as unknown as vscode.TextDocument;
  return { repo, api, doc };
}
describe('selected file provenance', () => {
  it('keeps detached HEAD and proves that a clean selected file exists and matches it', async () => {
    const { repo, api, doc } = fixture();
    expect(await headAndDirty(api, doc)).toMatchObject({ commit: sha, dirty: false });
    expect(repo.show).toHaveBeenCalledWith(sha, doc.uri.fsPath);
  });
  it('marks ignored/untracked paths absent from HEAD dirty even when every status list is empty', async () => {
    const { repo, api, doc } = fixture();
    repo.show.mockRejectedValueOnce(new Error('not in HEAD'));
    expect(await headAndDirty(api, doc)).toMatchObject({ commit: sha, dirty: true });
  });
  it('does not trust a clean status list when the selected file differs from the captured revision', async () => {
    const { repo, api, doc } = fixture();
    repo.show.mockResolvedValueOnce('different content\n');
    expect(await headAndDirty(api, doc)).toMatchObject({ dirty: true });
  });
  it('judges the lines captured for the anchor, not the buffer after the git awaits (s-17c13096e5)', async () => {
    const { repo, api, doc } = fixture();
    // status clean, but the captured text is not what HEAD holds: never reported clean
    expect(await headAndDirty(api, doc, { lines: ['stale', ''], isDirty: false })).toMatchObject({ dirty: true });
    // captured equal to HEAD: clean even if the buffer turns dirty while git answers
    repo.show.mockImplementationOnce(async () => { (doc as unknown as { isDirty: boolean }).isDirty = true; return 'content\n'; });
    expect(await headAndDirty(api, doc, { lines: ['content', ''], isDirty: false })).toMatchObject({ dirty: false });
  });
});
