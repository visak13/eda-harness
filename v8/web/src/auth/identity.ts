// SEAM (identity adapter). EventSource cannot set headers, so identity travels as
// request headers derived from the URL once, then held in sessionStorage (tab-scoped).
// `token` is stripped from the address bar via history.replaceState so it never lands
// in history, bookmarks, or a copied/shared deep link. Default `as=owner` mirrors the
// legacy UI (ui.py:235). This is the production module the whole SPA imports.
//
// S22 (t-f5d27a6f2e, owner m-94117833e0 "open in new tab … I am asked to login again"): sessionStorage
// is per TAB, and Chromium opens every target=_blank / Ctrl-click / pasted-address tab WITHOUT an
// opener, so the new tab starts with no token → /v1/whoami 401 → identity panel. Until 673803f the
// message links still carried ?token and re-seated the new tab; dropping it (correctly — the token
// must not live in URLs) exposed the gap. The carry is now a same-origin BroadcastChannel handshake:
// a tab holding a token answers "who is signed in here?", and a new tab without one asks before its
// first render (sessionReady, bounded). The token never enters a URL or persistent storage — closing
// every tab ends the session, as before.

const CHANNEL = "edp8.session";
const ASK_TIMEOUT_MS = 400;

function fromUrl(): { as: string | null; token: string | null } {
  try {
    const url = new URL(location.href);
    return { as: url.searchParams.get("as"), token: url.searchParams.get("token") };
  } catch {
    return { as: null, token: null };
  }
}

function initIdentity(): string {
  const fallback = () => {
    try {
      return sessionStorage.getItem("edp8.as") ?? "owner";
    } catch {
      return "owner";
    }
  };
  try {
    const url = new URL(location.href);
    const previous = fallback();
    const as = url.searchParams.get("as") ?? previous;
    if (as !== previous) {
      Object.keys(sessionStorage).filter((key) => key.startsWith("edp8.draft.")).forEach((key) => sessionStorage.removeItem(key));
    }
    const token = url.searchParams.get("token");
    if (token) {
      sessionStorage.setItem("edp8.token", token);
      url.searchParams.delete("token");
      history.replaceState({}, "", url); // token never survives in the bar
    }
    sessionStorage.setItem("edp8.as", as);
    return as;
  } catch {
    return fallback();
  }
}

// Read once at module load — the URL is authoritative only on first paint.
const URL_AS = fromUrl().as;
let AS = initIdentity();

// The token read at load (or received by the handshake) is also held in memory, so this tab keeps
// answering asks even if its storage is cleared or blocked.
let TOKEN: string | null = null;
function tok(): string | null {
  try {
    return sessionStorage.getItem("edp8.token") ?? TOKEN;
  } catch {
    return TOKEN;
  }
}
TOKEN = tok();

type SessionMsg = { type: "ask"; as: string | null } | { type: "session"; as: string; token: string };

function channel(): BroadcastChannel | null {
  try {
    return typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel(CHANNEL);
  } catch {
    return null;
  }
}

/** Answer other tabs of this origin asking for the session: only a tab that holds a token answers,
 *  and only for the identity asked (a tab opened with `?as=bob` never receives alice's token). */
let answering: BroadcastChannel | null = null;
function answerAsks(): void {
  const ch = channel();
  if (!ch) return;
  answering = ch;
  ch.onmessage = (e: MessageEvent<SessionMsg>) => {
    const m = e.data;
    if (m?.type !== "ask") return;
    const token = tok();
    if (!token || (m.as !== null && m.as !== AS)) return;
    ch.postMessage({ type: "session", as: AS, token } satisfies SessionMsg);
  };
}

/** A tab with no token asks the open tabs once; resolves when one answers or after the timeout. */
function askSession(): Promise<void> {
  if (tok()) return Promise.resolve();
  const ch = channel();
  if (!ch) return Promise.resolve();
  return new Promise<void>((resolve) => {
    const done = () => {
      clearTimeout(timer);
      ch.close();
      resolve();
    };
    const timer = setTimeout(done, ASK_TIMEOUT_MS);
    ch.onmessage = (e: MessageEvent<SessionMsg>) => {
      const m = e.data;
      if (m?.type !== "session" || !m.token || (URL_AS !== null && m.as !== URL_AS)) return;
      try {
        sessionStorage.setItem("edp8.token", m.token);
        sessionStorage.setItem("edp8.as", m.as);
      } catch {
        /* storage unavailable: header-only identity */
      }
      AS = m.as;
      TOKEN = m.token;
      done();
    };
    ch.postMessage({ type: "ask", as: URL_AS } satisfies SessionMsg);
  });
}

/** t-3e246b5e32 (e): an expert's link carries a one-time `?code=`, never the token (history, referrers and
 *  proxy logs keep query strings). The code leaves the address bar at once and is redeemed ONCE by POST
 *  for the expert's handle + token, which go to this tab's sessionStorage like any other session. A spent
 *  or expired code leaves the tab without a token (whoami then shows the identity panel). */
function redeemCode(): Promise<void> {
  let code: string | null = null;
  try {
    const url = new URL(location.href);
    code = url.searchParams.get("code");
    if (!code) return Promise.resolve();
    url.searchParams.delete("code");
    history.replaceState({}, "", url);
  } catch {
    return Promise.resolve();
  }
  return fetch("/v1/expert-session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  })
    .then((r) => r.json())
    .then((env: { ok?: boolean; value?: { as: string; token: string } }) => {
      if (!env?.ok || !env.value) return;
      try {
        sessionStorage.setItem("edp8.token", env.value.token);
        sessionStorage.setItem("edp8.as", env.value.as);
      } catch {
        /* storage unavailable: the in-memory token still serves this tab */
      }
      AS = env.value.as;
      TOKEN = env.value.token;
    })
    .catch(() => undefined);
}

/** Resolves once this tab's session is settled — an expert link's code redeemed first, then immediately
 *  when the tab holds a token, else after the same-origin handshake (≤ ASK_TIMEOUT_MS). main.tsx renders
 *  after it. */
export const sessionReady: Promise<void> = redeemCode().then(askSession).finally(answerAsks);

/** Stop answering session asks (tests load several module copies in one realm). */
export function stopAnswering(): void {
  answering?.close();
  answering = null;
}

/** The active participant id/handle (`as`). */
export const identity = (): string => AS;

/** Headers every board request carries; X-Token only when a token is held. */
export function authHeaders(): Record<string, string> {
  const t = tok();
  return { "X-Participant": AS, ...(t ? { "X-Token": t } : {}) };
}
