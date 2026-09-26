import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { codeRedeem } from "../../auth/identity";
import { PRODUCT_NAME } from "../../brand";
import { PageHeader } from "../../components/PageHeader";
import ui from "../../components/ui.module.css";
import styles from "./Admin.module.css";
import { errorText } from "./shared";

// /ui/join?code= (design §4.8): the teammate's landing page. identity.ts redeemed the one-time code at
// POST /v1/join before first paint (the code has already left the address bar); this page says what happened.

interface WhoAmI { participant: { id: string; handle: string; role: string } }

export function JoinPage(): React.JSX.Element {
  const redeemed = codeRedeem();
  const who = useQuery({ queryKey: ["whoami"], queryFn: () => api<WhoAmI>("/v1/whoami"), retry: false });
  const handle = who.data?.participant.handle;
  return (
    <div className={styles.setupShell}>
      <main className={styles.setupInner} data-testid="join-page">
        <PageHeader title={`Join ${PRODUCT_NAME}`} />
        {redeemed && !redeemed.ok ? (
          <p className={ui.banner} role="alert" data-testid="join-error">{redeemed.message}</p>
        ) : null}
        {!redeemed && !handle && !who.isLoading ? (
          <p className={ui.banner} role="alert" data-testid="join-nocode">This page signs you in from an invite link. Open the link your admin sent you, or ask them for a new one.</p>
        ) : null}
        {who.error && redeemed?.ok ? <p className={ui.banner} role="alert">{errorText(who.error)}</p> : null}
        {handle ? (
          <section className={styles.card} data-testid="join-ok">
            <h2 className={styles.cardTitle}>You are signed in as {handle}</h2>
            <p className={styles.fieldDoc}>This browser tab holds your session; closing every board tab signs you out. The invite link no longer works, so keep this tab or ask an admin for a new link.</p>
            <div className={styles.row}>
              <Link className={`${ui.button} ${ui.buttonPrimary}`} to="/me" data-testid="join-open-board">Open the board</Link>
              <Link className={ui.button} to="/settings">Your settings</Link>
            </div>
            <p className={styles.fieldDoc}>Using VS Code? The same invite also had a VS Code sign-in link; ask your admin for one if you did not get it.</p>
          </section>
        ) : null}
      </main>
    </div>
  );
}
