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
  const doc = { uri: { fsPath: 'C:/repo/file.txt' }, isDirty: false, getText: () => 'content\r\n' } as vscode.TextDocument;
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
});
