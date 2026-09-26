// The workbench layout the extension changes (t-93da8bf09d): the reader's full screen (Zen mode) and the Code tab's
// Reset layout. Zen hides the menu, the activity bar and the status bar, and silences notifications, so the way out
// is shown in the reader itself (FULL_SCREEN_HINT) and the leave is always an explicit exitZenMode: a stale flag
// (Zen left through Ctrl+K Z) can then never turn Zen back on by accident. Pure: `exec` runs a workbench command.

export const ZEN_TOGGLE = 'workbench.action.toggleZenMode';
export const ZEN_EXIT = 'workbench.action.exitZenMode';
export const RESET_VIEWS = 'workbench.action.resetViewLocations';

export const FULL_SCREEN_HINT = 'Full screen — Ctrl+K Z or the ⛶ button to exit';

/** The stamp the board writes under the extension's global storage (POST /v1/code/reset-layout). */
export const RESET_STAMP = 'reset-layout.json';

export class Layout {
  private on = false;
  private listeners = new Set<(on: boolean) => void>();

  constructor(private exec: (command: string) => Thenable<unknown> | Promise<unknown>) {}

  get fullScreen(): boolean { return this.on; }

  /** Called with the new full-screen state whenever it changes; returns the unsubscribe. */
  onChange(fn: (on: boolean) => void): () => void {
    this.listeners.add(fn);
    return () => { this.listeners.delete(fn); };
  }

  /** The reader's ⛶ button. It shows only out of Zen (the editor title's `!inZenMode`, the reader's own flag), so
   *  it enters; the way back is exitFullScreen, which never toggles. */
  async enterFullScreen(): Promise<void> {
    await this.exec(ZEN_TOGGLE);
    this.set(true);
  }

  async exitFullScreen(): Promise<void> {
    await this.exec(ZEN_EXIT);
    this.set(false);
  }

  /** Reset layout: out of Zen, and every view back where the workbench puts it by default. */
  async reset(): Promise<void> {
    await this.exec(ZEN_EXIT);
    await this.exec(RESET_VIEWS);
    this.set(false);
  }

  private set(on: boolean): void {
    if (on === this.on) return;
    this.on = on;
    for (const fn of this.listeners) fn(on);
  }
}

/** A Reset layout stamp to act on: written after this window started watching (`since`, epoch ms) and newer than the
 *  last one seen. A stamp left from an earlier reset never re-fires on a reload. */
export function freshStamp(mtimeMs: number, prevMtimeMs: number, since: number): boolean {
  return mtimeMs > 0 && mtimeMs > prevMtimeMs && mtimeMs >= since;
}
