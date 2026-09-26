import { useState } from "react";
import { useNavigate } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, BoardApiError } from "../../api/client";
import { applyTailnet, createTeammate, finishSetup, getTailnet } from "../../api/admin";
import { codeRedeem, signIn } from "../../auth/identity";
import { PRODUCT_NAME } from "../../brand";
import { PageHeader } from "../../components/PageHeader";
import ui from "../../components/ui.module.css";
import styles from "./Admin.module.css";
import { AdminError, Done, Secret } from "./shared";
import { HarnessSelection } from "./SeatsModels";
import { ToolsStep } from "./SetupTools";

// /ui/setup (design §4.8 Onboarding, §4.11): the first-run wizard `heronry start` opens — admin sign-in,
// your tools (the prerequisites checklist with Install and harness sign-in, t-08612be1b0), harness detection (at least one of claude/codex; the Fable notice without codex), optional remote access,
// optional first teammate — ending on the board. POST /v1/admin/setup/done stops `start` opening it again.

const STEPS = ["Sign in", "Your tools", "Harnesses", "Remote access", "First teammate", "Done"] as const;

interface WhoAmI { participant: { id: string; handle: string; role: string; admin?: boolean }; admin?: boolean }

function SignInStep({ onDone }: { onDone: () => void }): React.JSX.Element {
  const qc = useQueryClient();
  const who = useQuery({ queryKey: ["whoami"], queryFn: () => api<WhoAmI>("/v1/whoami"), retry: false });
  const [handle, setHandle] = useState("");
  const [token, setToken] = useState("");
  const redeemed = codeRedeem();
  const admin = Boolean(who.data?.admin ?? who.data?.participant.admin);
  return (
    <section className={styles.card} data-testid="setup-signin">
      <h2 className={styles.cardTitle}>Sign in as the admin</h2>
      {redeemed && !redeemed.ok ? <p className={ui.banner} role="alert" data-testid="setup-code-error">{redeemed.message}</p> : null}
      {who.data ? (
        admin ? (
          <>
            <p className={styles.fieldDoc} data-testid="setup-signed-in">Signed in as <strong>{who.data.participant.handle}</strong>, an admin of this install.</p>
            <div className={styles.row}><button type="button" className={`${ui.button} ${ui.buttonPrimary}`} onClick={onDone} data-testid="setup-next">Next</button></div>
          </>
        ) : <p className={ui.banner} role="alert" data-testid="setup-not-admin">{who.data.participant.handle} is not an admin; sign in as the person `heronry init` created.</p>
      ) : (
        <p className={styles.fieldDoc}>Open the link `heronry start` printed (it signs you in once), or sign in with the first human's handle and token from the tokens file `heronry init` wrote.</p>
      )}
      {!admin ? (
        <form className={styles.row} onSubmit={(e) => { e.preventDefault(); signIn(handle.trim(), token.trim()); void qc.invalidateQueries({ queryKey: ["whoami"] }); }}>
          <input className={ui.input} placeholder="handle (e.g. owner)" value={handle} onChange={(e) => setHandle(e.target.value)} aria-label="Handle" data-testid="setup-handle" />
          <input className={ui.input} type="password" placeholder="token" value={token} onChange={(e) => setToken(e.target.value)} aria-label="Token" data-testid="setup-token" />
          <button type="submit" className={ui.button} disabled={!handle.trim() || !token.trim()} data-testid="setup-signin-submit">Sign in</button>
        </form>
      ) : null}
      {/* a 401 here just means "not signed in yet"; the sign-in form above is the answer */}
      {who.error && !(who.error instanceof BoardApiError && who.error.status === 401) ? <AdminError error={who.error} testid="setup-signin-error" /> : null}
    </section>
  );
}

function RemoteStep({ onDone }: { onDone: () => void }): React.JSX.Element {
  const q = useQuery({ queryKey: ["admin", "tailnet"], queryFn: getTailnet, retry: false });
  const apply = useMutation({ mutationFn: () => applyTailnet(false) });
  const t = q.data;
  return (
    <section className={styles.card} data-testid="setup-remote">
      <h2 className={styles.cardTitle}>Remote access (optional)</h2>
      <p className={styles.fieldDoc}>Teammates on other machines reach this board over your Tailscale tailnet. Skip this to keep the board on this machine only; Admin → Remote access does it later.</p>
      <AdminError error={q.error} testid="setup-remote-error" />
      {t ? <p className={styles.fieldDoc} data-testid="setup-remote-status">Tailscale: {t.tailscale ? `${t.tailscale.backend ?? "unknown"}${t.tailscale.dns ? ` (${t.tailscale.dns})` : ""}` : "not running here"} · {t.blockers} readiness blocker{t.blockers === 1 ? "" : "s"}{t.public_mode ? ` · public at ${t.public_url}` : ""}</p> : null}
      <div className={styles.row}>
        <button type="button" className={ui.button} disabled={!t || t.public_mode || apply.isPending} onClick={() => apply.mutate()} data-testid="setup-remote-apply">Apply public mode</button>
        <button type="button" className={`${ui.button} ${ui.buttonPrimary}`} onClick={onDone} data-testid="setup-next">{apply.isSuccess ? "Next" : "Skip"}</button>
      </div>
      <AdminError error={apply.error} testid="setup-remote-apply-error" />
      <Done text={apply.isSuccess ? `${apply.data.hint} (Admin → Services).` : null} />
    </section>
  );
}

function TeammateStep({ onDone }: { onDone: () => void }): React.JSX.Element {
  const [handle, setHandle] = useState("");
  const m = useMutation({ mutationFn: () => createTeammate({ handle: handle.trim() }) });
  return (
    <section className={styles.card} data-testid="setup-teammate">
      <h2 className={styles.cardTitle}>First teammate (optional)</h2>
      <form className={styles.row} onSubmit={(e) => { e.preventDefault(); if (handle.trim()) m.mutate(); }}>
        <input className={ui.input} placeholder="their handle" value={handle} onChange={(e) => setHandle(e.target.value)} aria-label="Teammate handle" data-testid="setup-teammate-handle" />
        <button type="submit" className={ui.button} disabled={!handle.trim() || m.isPending} data-testid="setup-teammate-invite">Invite</button>
        <button type="button" className={`${ui.button} ${ui.buttonPrimary}`} onClick={onDone} data-testid="setup-next">{m.isSuccess ? "Next" : "Skip"}</button>
      </form>
      <AdminError error={m.error} testid="setup-teammate-error" />
      {m.data ? <>
        <Secret label="Invite link" value={m.data.value.invite.link} testid="setup-invite-link" />
        <Secret label="VS Code sign-in" value={m.data.value.invite.vscode_link} testid="setup-invite-vscode" />
      </> : null}
    </section>
  );
}

export function SetupPage(): React.JSX.Element {
  const [step, setStep] = useState(0);
  const navigate = useNavigate();
  const finish = useMutation({ mutationFn: finishSetup, onSuccess: () => navigate("/epics") });
  const next = () => setStep((s) => Math.min(s + 1, STEPS.length - 1));
  return (
    <div className={styles.setupShell}>
      <main className={styles.setupInner} data-testid="setup-page">
        <PageHeader title={`Set up ${PRODUCT_NAME}`} subtitle="A few steps, then the board. Everything here can be changed later under Admin." />
        <ol className={styles.steps} aria-label="Setup steps">
          {STEPS.map((s, i) => <li key={s} className={i === step ? styles.stepActive : styles.step} aria-current={i === step ? "step" : undefined}>{i + 1}. {s}</li>)}
        </ol>
        {step === 0 ? <SignInStep onDone={next} /> : null}
        {step === 1 ? <ToolsStep onDone={next} /> : null}
        {step === 2 ? (
          <>
            <HarnessSelection onSaved={next} installedOnly />
            <p className={styles.fieldDoc}>Seats run on claude, codex or both; the choice is saved when you press Save harnesses, which moves you on.</p>
          </>
        ) : null}
        {step === 3 ? <RemoteStep onDone={next} /> : null}
        {step === 4 ? <TeammateStep onDone={next} /> : null}
        {step === 5 ? (
          <section className={styles.card} data-testid="setup-done">
            <h2 className={styles.cardTitle}>Ready</h2>
            <p className={styles.fieldDoc}>Start an epic from the Epics page. Admin in the menu runs services, settings, teammates and integrations.</p>
            <div className={styles.row}>
              <button type="button" className={`${ui.button} ${ui.buttonPrimary}`} disabled={finish.isPending} onClick={() => finish.mutate()} data-testid="setup-finish">Open the board</button>
            </div>
            <AdminError error={finish.error} testid="setup-finish-error" />
          </section>
        ) : null}
      </main>
    </div>
  );
}
