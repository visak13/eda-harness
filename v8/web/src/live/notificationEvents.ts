// Fan-out from the existing single authenticated feed; never a second SSE subscription.
const listeners = new Set<() => void>();
export function attentionChanged(): void { for (const listener of listeners) listener(); }
export function onAttentionChanged(listener: () => void): () => void {
  listeners.add(listener); return () => { listeners.delete(listener); };
}
