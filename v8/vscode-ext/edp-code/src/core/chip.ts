// The composer's code chip (C4 s-a34658f02f). The host holds the anchor; the view gets a display-only
// ChipView and names the chip by id when it sends. Pure: no `vscode` import.
import { randomBytes } from 'node:crypto';
import type { Anchor } from './anchor';
import type { ChipView } from './chatProtocol';
import { at } from './render';

export const PREVIEW_LINES = 6;

export type Chip = { id: string; anchor: Anchor; truncated: boolean };

export function newChip(anchor: Anchor, truncated: boolean): Chip {
  return { id: `k-${randomBytes(6).toString('hex')}`, anchor, truncated };
}

export function chipView(c: Chip): ChipView {
  const lines = c.anchor.snippet.split('\n');
  return {
    id: c.id, label: at(c.anchor), lines: lines.length, truncated: c.truncated,
    preview: lines.slice(0, PREVIEW_LINES).join('\n') + (lines.length > PREVIEW_LINES ? `\n… ${lines.length - PREVIEW_LINES} more lines` : ''),
  };
}

/** Whether a send names the chip the host holds for that thread. No chip id = a plain send (the user
 *  removed the chip, or never had one); an id the host does not hold (replaced by a newer tag, or
 *  dropped) is refused, so a message never goes out with lines the user did not see. */
export function chipForSend(held: Chip | undefined, chipId: string | undefined): { chip: Chip | null } | { error: string } {
  if (!chipId) return { chip: null };
  if (!held || held.id !== chipId) return { error: 'Not sent: the tagged lines changed; check the chip and send again.' };
  return { chip: held };
}
