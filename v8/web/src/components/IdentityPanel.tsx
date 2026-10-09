import { useState } from "react";
import { hasToken, identity } from "../auth/identity";
import { RequestAccess } from "./RequestAccess";
import styles from "./IdentityPanel.module.css";

// Design §4.1 (Transition): when the board answers the identity probe (/v1/whoami) with 401 — a
// wrong X-Token against a board that has a tokens.json, or an unknown participant — the SPA does
// NOT silently fall back to displaying `as`. It renders this inline panel so the reader can re-enter
// a participant id and, when the board is credentialled, the matching token. Identity is read once
// at module load from ?as/?token (src/auth/identity.ts), so submitting re-seats it with a full
// navigation rather than a client route change. (second-opinion 2026-09-08, criterion c-5985a92696)
//
// t-882e4d2eeb: this is also where Sign out lands (identity() is then empty, so it says "signed out" and
// shows no board error), and where a person without a token can Request access on a remote-enabled board.
// qa 0.10.8: the card used to pre-fill Participant with the default identity, "owner": on a public board that showed the
// owner's handle to strangers. It starts empty. Only a value this browser itself used before (its own localStorage), or the
// participant whose token the board just refused, is offered back.
const LAST_KEY = "edp8.last-participant";
function lastParticipant(): string {
  try {
    return localStorage.getItem(LAST_KEY) ?? "";
  } catch {
    return "";
  }
}

// architect m-67dc851e4f: an untouched card shows no error. One shows only after a sign-in attempt this tab made (or with a token the board refused).
const TRIED_KEY = "edp8.sign-in-tried";
function tried(): boolean {
  try {
    return sessionStorage.getItem(TRIED_KEY) === "1";
  } catch {
    return false;
  }
}

export function IdentityPanel(): React.JSX.Element {
  const signedOut = identity() === "";
  const [as, setAs] = useState(hasToken() ? identity() : lastParticipant());
  const [token, setToken] = useState("");
  const failed = !signedOut && (hasToken() || tried());

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const url = new URL(window.location.href);
    url.searchParams.set("as", as.trim());
    try {
      sessionStorage.setItem(TRIED_KEY, "1");
    } catch {
      /* storage unavailable: no error line after the reload */
    }
    try {
      if (as.trim()) localStorage.setItem(LAST_KEY, as.trim());
    } catch {
      /* storage unavailable: nothing is remembered */
    }
    url.searchParams.delete("token");
    // The token goes to sessionStorage directly — never into a document URL, where it would land in
    // the request line and the server access log (adversary finding #1, 2026-09-10). identity.ts
    // reads sessionStorage on the reload.
    try {
      if (token.trim()) sessionStorage.setItem("edp8.token", token.trim());
    } catch {
      /* storage unavailable: header-only identity */
    }
    window.location.assign(url.toString()); // full reload → identity.ts re-reads ?as + stored token
  };

  return (
    <main className={styles.wrap} data-testid="identity-panel">
      <div className={styles.stack}>
      <form className={styles.card} onSubmit={submit} aria-labelledby="identity-panel-title">
        <h1 id="identity-panel-title" className={styles.title}>
          {signedOut ? "Signed out" : "Identity needed"}
        </h1>
        {signedOut ? (
          <p className={styles.body} data-testid="signed-out">
            You are signed out of this board. Enter your participant id and token to sign in again.
          </p>
        ) : (
          <p className={styles.body}>
            {/* a failed sign-in says so once, in the alert below; the sentence here only asks again */}
            {failed ? <>Try again with a participant id and, if this board requires one, the matching token.</> : <>Sign in to use this board. Enter a participant id and, if this board requires one, the matching token to continue.</>}
          </p>
        )}
        {failed ? (
          <p className={styles.hint} role="alert" data-testid="identity-hint">
            That participant and token don't match.
          </p>
        ) : null}
        <label className={styles.label}>
          Participant
          <input
            className={styles.input}
            value={as}
            onChange={(e) => setAs(e.target.value)}
            autoFocus
            data-testid="identity-as"
          />
        </label>
        <label className={styles.label}>
          Token <span className={styles.opt}>(only if this board requires one)</span>
          <input
            className={styles.input}
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            data-testid="identity-token"
          />
        </label>
        <button className={styles.submit} type="submit" data-testid="identity-continue">
          Continue
        </button>
      </form>
      <RequestAccess />
      </div>
    </main>
  );
}
