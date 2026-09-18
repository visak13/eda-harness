// Tab-local draft persistence. Never localStorage, never automatic cross-tab transfer.
export interface StoredDraft {
  text: string; artifacts: string[]; mode?: "comment" | "request_changes";
  kind?: string; to?: string | null; toPicked?: boolean;
  selection?: { start: number; end: number; scroll: number };
  pendingAction?: { signature: string; key: string };
}
export function readDraft(key: string): StoredDraft | undefined {
  try {
    const raw = sessionStorage.getItem(`edp8.draft.${key}`);
    if (!raw) return undefined;
    const value = JSON.parse(raw) as StoredDraft;
    return typeof value.text === "string" && Array.isArray(value.artifacts) && value.artifacts.every((x) => typeof x === "string") ? value : undefined;
  } catch { return undefined; }
}
export function writeDraft(key: string, draft: StoredDraft): void {
  try {
    if (!draft.text && !draft.artifacts.length && !draft.pendingAction) sessionStorage.removeItem(`edp8.draft.${key}`);
    else sessionStorage.setItem(`edp8.draft.${key}`, JSON.stringify(draft));
  } catch { /* Memory remains authoritative when tab storage is denied/full. */ }
}
