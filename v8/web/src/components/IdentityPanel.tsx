import { useState } from "react";
import { identity } from "../auth/identity";
import styles from "./IdentityPanel.module.css";

// Design §4.1 (Transition): when the board answers the identity probe (/v1/whoami) with 401 — a
// wrong X-Token against a board that has a tokens.json, or an unknown participant — the SPA does
// NOT silently fall back to displaying `as`. It renders this inline panel so the reader can re-enter
// a participant id and, when the board is credentialled, the matching token. Identity is read once
// at module load from ?as/?token (src/auth/identity.ts), so submitting re-seats it with a full
// navigation rather than a client route change. (second-opinion 2026-09-08, criterion c-5985a92696)
export function IdentityPanel({ hint }: { hint?: string }): React.JSX.Element {
  const [as, setAs] = useState(identity());
  const [token, setToken] = useState("");

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const url = new URL(window.location.href);
    url.searchParams.set("as", as.trim());
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
      <form className={styles.card} onSubmit={submit} aria-labelledby="identity-panel-title">
        <h1 id="identity-panel-title" className={styles.title}>
          Identity needed
        </h1>
        <p className={styles.body}>
          The board rejected your credentials for <span className={styles.who}>{identity()}</span>.
          Enter a participant id and, if this board requires one, the matching token to continue.
        </p>
        {hint ? (
          <p className={styles.hint} role="alert" data-testid="identity-hint">
            {hint}
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
    </main>
  );
}
