import { useCallback, useLayoutEffect, useRef, useState } from "react";
import type { PersonRow } from "../api/types";

// Headless @autocomplete (design §13 / strategy_ll §11; parity with ui.py _JS). Triggers on
// `@partial` at the caret, lists matching handles from the ONE people list (/v1/me/people), and
// on accept replaces the partial token with `@handle `. Keyboard: ↑/↓ move the highlight,
// Enter/Tab accept, Esc dismiss. It never invents a recipient — it only inserts a handle the
// board's own list contains; who is actually woken is the board's decision (reported by the
// wake preview + resolution note), never computed here.

const TRIGGER = /@([\w.\-]*)$/; // the partial token immediately left of the caret

export interface MentionsMenu {
  open: boolean;
  items: PersonRow[];
  index: number;
}

export interface Mentions {
  menu: MentionsMenu;
  /** Recompute the menu from the textarea's current value + caret (call on input/click/keyup). */
  refresh: () => void;
  /** Keydown handler for the textarea; returns true when it consumed the event (menu nav/accept). */
  onKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => boolean;
  /** Accept a specific candidate (mouse click in the menu). */
  accept: (person: PersonRow) => void;
  close: () => void;
}

export function useMentions(
  people: PersonRow[],
  textareaRef: React.RefObject<HTMLTextAreaElement | null>,
  setText: (next: string) => void,
): Mentions {
  const [menu, setMenu] = useState<MentionsMenu>({ open: false, items: [], index: 0 });
  const caretToSet = useRef<number | null>(null);
  const lastQuery = useRef<string | null>(null);
  // Round 2 #14: Esc dismissed the menu on keydown and the keyup's refresh reopened it on the same
  // token. The dismissed token stays suppressed until the text or caret moves off it.
  const dismissed = useRef<string | null>(null);

  // After an accept rewrites the value, restore the caret to just past the inserted "@handle ".
  useLayoutEffect(() => {
    if (caretToSet.current !== null && textareaRef.current) {
      const pos = caretToSet.current;
      textareaRef.current.setSelectionRange(pos, pos);
      caretToSet.current = null;
    }
  });

  const close = useCallback(() => setMenu((m) => (m.open ? { ...m, open: false } : m)), []);

  const refresh = useCallback(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    const left = ta.value.slice(0, ta.selectionStart ?? ta.value.length);
    const m = TRIGGER.exec(left);
    if (!m) {
      lastQuery.current = null;
      setMenu((cur) => (cur.open ? { open: false, items: [], index: 0 } : cur));
      return;
    }
    const q = m[1].toLowerCase();
    const tokenKey = `${left.length}:${q}`;
    if (dismissed.current === tokenKey) return;
    dismissed.current = null;
    const items = people
      .filter((p) => p.handle.toLowerCase().includes(q) || p.label.toLowerCase().includes(q))
      .slice(0, 8);
    // The keyup after an ArrowDown re-runs this; the highlight must survive it while the typed
    // partial is unchanged — otherwise ↓ alternated between the first two rows (human report
    // m-a398600978, 2026-09-10). A new partial starts the highlight at the top again.
    const sameQuery = lastQuery.current === q;
    lastQuery.current = q;
    setMenu((cur) => ({
      open: items.length > 0,
      items,
      index: sameQuery && cur.open ? Math.min(cur.index, Math.max(items.length - 1, 0)) : 0,
    }));
  }, [people, textareaRef]);

  const accept = useCallback(
    (person: PersonRow) => {
      const ta = textareaRef.current;
      if (!ta) return;
      const caret = ta.selectionStart ?? ta.value.length;
      const left = ta.value.slice(0, caret);
      const m = TRIGGER.exec(left);
      if (!m) return;
      const start = caret - m[0].length; // strip the "@partial" we are replacing
      const insert = `@${person.handle} `;
      const next = ta.value.slice(0, start) + insert + ta.value.slice(caret);
      caretToSet.current = start + insert.length;
      setText(next);
      lastQuery.current = null;
      setMenu({ open: false, items: [], index: 0 });
    },
    [setText, textareaRef],
  );

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>): boolean => {
      if (!menu.open || menu.items.length === 0) return false;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setMenu((m) => ({ ...m, index: (m.index + 1) % m.items.length }));
        return true;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setMenu((m) => ({ ...m, index: (m.index - 1 + m.items.length) % m.items.length }));
        return true;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        accept(menu.items[menu.index]);
        return true;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        const ta = textareaRef.current;
        if (ta) {
          const left = ta.value.slice(0, ta.selectionStart ?? ta.value.length);
          const t = TRIGGER.exec(left);
          dismissed.current = t ? `${left.length}:${t[1].toLowerCase()}` : null;
        }
        close();
        return true;
      }
      return false;
    },
    [menu, accept, close, textareaRef],
  );

  return { menu, refresh, onKeyDown, accept, close };
}
