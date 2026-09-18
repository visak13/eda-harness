// SEAM (identity adapter). EventSource cannot set headers, so identity travels as
// request headers derived from the URL once, then held in sessionStorage (tab-scoped).
// `token` is stripped from the address bar via history.replaceState so it never lands
// in history, bookmarks, or a copied/shared deep link. Default `as=owner` mirrors the
// legacy UI (ui.py:235). This is the production module the whole SPA imports.

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
const AS = initIdentity();

function tok(): string | null {
  try {
    return sessionStorage.getItem("edp8.token");
  } catch {
    return null;
  }
}

/** The active participant id/handle (`as`). */
export const identity = (): string => AS;

/** Headers every board request carries; X-Token only when a token is held. */
export function authHeaders(): Record<string, string> {
  const t = tok();
  return { "X-Participant": AS, ...(t ? { "X-Token": t } : {}) };
}
