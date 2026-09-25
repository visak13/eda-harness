// The composer's send chord (C14, owner m-db09472a68): the same as the board UI's Composer. Enter
// inserts a newline; Ctrl+Enter sends (Cmd+Enter on macOS). The # and @ pickers take Enter first while
// their list is open, so this is asked only after they pass a key through.
type Key = { key: string; ctrlKey: boolean; metaKey: boolean; shiftKey?: boolean; altKey?: boolean };

/** Ctrl+Enter or Cmd+Enter sends, as the board's Composer does (`(ctrlKey || metaKey) && Enter`). */
export const isSendKey = (e: Key): boolean => e.key === 'Enter' && (e.ctrlKey || e.metaKey);

/** The chord's name in hint text for this platform. */
export const sendChord = (platform: string): string => (/mac|iphone|ipad/i.test(platform) ? 'Cmd+Enter' : 'Ctrl+Enter');
