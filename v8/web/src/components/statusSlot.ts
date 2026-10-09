import { useSyncExternalStore } from "react";

// The composer's status slot (qa fail 8, architect m-b25e693093): the spot that says "nobody is woken" / "Will notify the
// architect". A short confirmation ("Requirement marked") takes the slot for a few seconds and the slot then restores itself:
// it moves nothing and covers nothing. A composer registers its slot element; when none is on screen (a page without a
// composer, or the collapsed bar) the caller falls back to a toast.

const FLASH_MS = 6000;
const slots = new Set<HTMLElement>();
const subs = new Set<() => void>();
let flashText: string | null = null;
let timer: ReturnType<typeof setTimeout> | undefined;
const emit = () => subs.forEach((f) => f());

/** Ref callback for the slot element. */
export function slotRef(el: HTMLElement | null, prev?: HTMLElement | null): void {
  if (prev) slots.delete(prev);
  if (el) slots.add(el);
}

/** True while some registered slot is visible. */
export const slotVisible = (): boolean => Array.from(slots).some((el) => el.isConnected && el.getClientRects().length > 0);

/** Show `text` in the slot for a few seconds, then restore it. Returns false (and shows nothing) when no slot is on screen. */
export function flashInSlot(text: string, ms = FLASH_MS): boolean {
  if (!slotVisible()) return false;
  clearTimeout(timer);
  flashText = text;
  emit();
  timer = setTimeout(() => { flashText = null; emit(); }, ms);
  return true;
}

const subscribe = (f: () => void) => { subs.add(f); return () => { subs.delete(f); }; };
export const useSlotFlash = (): string | null => useSyncExternalStore(subscribe, () => flashText, () => null);
