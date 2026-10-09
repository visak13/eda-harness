// The desktop shell (pywebview + WebView2, edp8.desktop): what the page may ask of it. pywebview injects
// `window.pywebview` before any page script runs, so detection is synchronous; its `api` (the Python `Bridge`)
// fills in a moment later and announces itself with the `pywebviewready` event.

export interface DesktopApi {
  ping(): Promise<{ shell: string; platform: string; toast: boolean }>;
  notify(title: string, body?: string): Promise<{ ok: boolean; reason?: string }>;
  open_external(url: string): Promise<boolean>;
}

declare global {
  interface Window { pywebview?: { api?: Partial<DesktopApi> } | null }
}

export function isDesktopShell(): boolean {
  return typeof window !== "undefined" && typeof window.pywebview === "object" && window.pywebview !== null;
}

function bridge(): DesktopApi | null {
  const api = window.pywebview?.api;
  return api && typeof api.notify === "function" && typeof api.open_external === "function" ? (api as DesktopApi) : null;
}

/** The bridge once it is ready (null outside the desktop shell, or when it never comes up). */
export function desktopApi(timeoutMs = 4000): Promise<DesktopApi | null> {
  if (!isDesktopShell()) return Promise.resolve(null);
  const now = bridge();
  if (now) return Promise.resolve(now);
  return new Promise((resolve) => {
    const finish = () => { window.removeEventListener("pywebviewready", finish); clearTimeout(timer); resolve(bridge()); };
    const timer = setTimeout(finish, timeoutMs);
    window.addEventListener("pywebviewready", finish);
  });
}

/** A native desktop toast through the shell's tray. False when there is no shell, no tray or the shell dropped it. */
export async function desktopNotify(title: string, body = ""): Promise<boolean> {
  const api = await desktopApi();
  if (!api) return false;
  try { return (await api.notify(title, body)).ok === true; } catch { return false; }
}

/** An absolute http(s) URL on another origin than this page (what `target=_blank` and the shell treat as external). */
export function isExternalHref(href: string, base: string = window.location.href): boolean {
  try {
    const url = new URL(href, base);
    return (url.protocol === "http:" || url.protocol === "https:") && url.origin !== new URL(base).origin;
  } catch { return false; }
}

/** Hand an external link to the system browser through the shell. False when the shell cannot (the caller lets the
 *  click through; the shell's navigation guard then sends it to the browser). */
export async function openExternal(href: string): Promise<boolean> {
  const api = await desktopApi();
  if (!api) return false;
  try { return (await api.open_external(href)) === true; } catch { return false; }
}
