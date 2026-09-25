// Where a Tag selection goes (design-10b21760d9 §4.1, C4 s-a34658f02f). Pure: the VS Code shell reads
// the two facts. The anchor is always captured first, whatever the route.
// - `palette`: the chat view was never resolved in this window, so the S5 chain runs unchanged.
// - `chip`: the chat view exists (a hidden view still counts: it re-renders on reveal) and a thread is
//   open, so the view is revealed and the chip goes into that thread's composer.
// - `pickThenChip`: the view exists but no thread is open; the thread picker opens first, and a
//   cancelled pick ends the command with nothing inserted and nothing sent.
export type TagRoute = 'palette' | 'chip' | 'pickThenChip';

export function tagRoute(s: { chatResolved: boolean; threadOpen: boolean }): TagRoute {
  if (!s.chatResolved) return 'palette';
  return s.threadOpen ? 'chip' : 'pickThenChip';
}
