// qa 0.10.8 round 3: on a fresh code-server profile Heronry Chat sat behind the secondary side bar's "..." (Additional Views),
// so a new user could not see it. The view is revealed ONCE per profile, on the first start after it is installed. The view
// stays in the secondary side bar (where the owner put it, away from Explorer); revealing is more reliable than moving the
// container to the activity bar, because it opens the side bar and selects the view whatever the profile's layout, and a
// user who closes it is never reopened on (the flag is stored). Pure: `store` is the extension's globalState.
export const FIRST_REVEAL_KEY = 'edp.chat.firstRevealed.v1';

export interface Flag { get<T>(key: string): T | undefined; update(key: string, value: unknown): Thenable<void> | Promise<void> }

/** Reveal the chat view the first time only; returns whether it did. A failed reveal is retried next start. */
export async function revealOnFirstStart(store: Flag, reveal: () => Promise<void>): Promise<boolean> {
  if (store.get<boolean>(FIRST_REVEAL_KEY)) return false;
  try { await reveal(); } catch { return false; }
  await store.update(FIRST_REVEAL_KEY, true);
  return true;
}
