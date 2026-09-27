import { useEffect, useRef, useState } from "react";
import { askAccess, claimAccess, getAccessAvailability, type AccessAvailability } from "../api/access";
import { BoardApiError } from "../api/client";
import { signIn } from "../auth/identity";
import styles from "./IdentityPanel.module.css";

// t-882e4d2eeb (design-e963c656f5 §4.18): "Request access" on the sign-in page of a remote-enabled board.
// The person says who they are; the board answers with a one-time claim code that only this tab holds
// (sessionStorage, never a URL). The tab polls with it by POST. When an admin approves, the token arrives
// once and signs this tab in; a decline or a spent code says so. Off, with the board's reason, when Remote
// access is off.

const CLAIM_KEY = "edp8.access.claim";
const ROLE_LABEL: Record<string, string> = { owner: "Member" };

type Phase =
  | { kind: "closed" }
  | { kind: "form" }
  | { kind: "waiting"; code: string; pollS: number }
  | { kind: "done"; text: string };

function storedClaim(): string | null {
  try {
    return sessionStorage.getItem(CLAIM_KEY);
  } catch {
    return null;
  }
}

function keepClaim(code: string | null): void {
  try {
    if (code) sessionStorage.setItem(CLAIM_KEY, code);
    else sessionStorage.removeItem(CLAIM_KEY);
  } catch {
    /* storage unavailable: the claim lives in this component only */
  }
}

export function RequestAccess(): React.JSX.Element | null {
  const [avail, setAvail] = useState<AccessAvailability | null>(null);
  const [phase, setPhase] = useState<Phase>(() => {
    const code = storedClaim();
    return code ? { kind: "waiting", code, pollS: 5 } : { kind: "closed" };
  });
  const [name, setName] = useState("");
  const [role, setRole] = useState("owner");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    getAccessAvailability().then((a) => { if (alive.current) setAvail(a); }).catch(() => { if (alive.current) setAvail(null); });
    return () => { alive.current = false; };
  }, []);

  // Poll while waiting: pending → again after poll_s; approved → sign in once; denied / spent → say so.
  useEffect(() => {
    if (phase.kind !== "waiting") return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const check = () => {
      claimAccess(phase.code)
        .then(({ value }) => {
          if (!alive.current) return;
          if (value.status === "pending") {
            timer = setTimeout(check, Math.max(2, value.poll_s) * 1000);
            return;
          }
          keepClaim(null);
          if (value.status === "denied") {
            setPhase({ kind: "done", text: "An admin declined this request. Ask the person who runs this board." });
            return;
          }
          if (value.status === "expired") {
            setPhase({ kind: "done", text: "No admin answered this request in time, so it expired. You can ask again." });
            return;
          }
          signIn(value.handle, value.token);
          const url = new URL(window.location.href);
          url.searchParams.set("as", value.handle);
          window.location.assign(url.toString()); // full reload: the shell starts signed in
        })
        .catch((e: unknown) => {
          if (!alive.current) return;
          if (e instanceof BoardApiError && e.status === 429) {
            timer = setTimeout(check, 60_000);
            return;
          }
          keepClaim(null);
          setPhase({ kind: "done", text: e instanceof BoardApiError && e.status === 401
            ? "This request is no longer open (it was used, or it expired). You can ask again."
            : "The board did not answer. Reload the page to check again." });
        });
    };
    check();
    return () => { if (timer) clearTimeout(timer); };
  }, [phase]);

  if (phase.kind === "waiting") {
    return (
      <section className={styles.access} data-testid="access-waiting" aria-live="polite">
        <p className={styles.body}>Request sent. Keep this page open: it signs you in as soon as an admin approves.</p>
      </section>
    );
  }
  if (phase.kind === "done") {
    return (
      <section className={styles.access}>
        <p className={styles.hint} role="status" data-testid="access-done">{phase.text}</p>
      </section>
    );
  }
  if (!avail) return null;
  if (!avail.enabled) {
    return (
      <section className={styles.access}>
        <p className={styles.body} data-testid="access-off">
          No token? {avail.reason ?? "This board takes no access requests."}
        </p>
      </section>
    );
  }
  if (phase.kind === "closed") {
    return (
      <section className={styles.access}>
        <button type="button" className={styles.linkButton} onClick={() => setPhase({ kind: "form" })} data-testid="access-open">
          No token? Request access
        </button>
      </section>
    );
  }
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || busy) return;
    setBusy(true);
    setError(null);
    askAccess({ name: name.trim(), role_wanted: role, note: note.trim() })
      .then(({ value }) => {
        keepClaim(value.claim_code);
        setPhase({ kind: "waiting", code: value.claim_code, pollS: value.poll_s });
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "the board did not answer"))
      .finally(() => setBusy(false));
  };
  return (
    <form className={styles.access} onSubmit={submit} aria-labelledby="access-title" data-testid="access-form">
      <h2 id="access-title" className={styles.subtitle}>Request access</h2>
      <p className={styles.body}>An admin of this board sees your request and can approve it. You are signed in here once they do.</p>
      <label className={styles.label}>
        Your name
        <input className={styles.input} value={name} maxLength={60} onChange={(e) => setName(e.target.value)} data-testid="access-name" />
      </label>
      <label className={styles.label}>
        Role you need
        <select className={styles.input} value={role} onChange={(e) => setRole(e.target.value)} data-testid="access-role">
          {avail.roles.map((r) => <option key={r} value={r}>{ROLE_LABEL[r] ?? r}</option>)}
        </select>
      </label>
      <label className={styles.label}>
        Note <span className={styles.opt}>(optional: what you are here for)</span>
        <input className={styles.input} value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} data-testid="access-note" />
      </label>
      {error ? <p className={styles.hint} role="alert" data-testid="access-error">{error}</p> : null}
      <button className={styles.submit} type="submit" disabled={!name.trim() || busy} data-testid="access-submit">
        {busy ? "Sending…" : "Send request"}
      </button>
    </form>
  );
}
