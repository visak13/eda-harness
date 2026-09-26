import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { applyTailnet, getTailnet, getTailnetGuide, removeTailnet } from "../../api/admin";
import type { TailnetView } from "../../api/admin";
import { Markdown } from "../../components/Markdown";
import ui from "../../components/ui.module.css";
import styles from "./Admin.module.css";
import { AdminError, CopyButton, Done } from "./shared";
import purposeSvg from "../../../../assets/guides/remote-access-1-purpose.svg";
import installSvg from "../../../../assets/guides/remote-access-2-install.svg";
import signinSvg from "../../../../assets/guides/remote-access-3-signin.svg";
import readySvg from "../../../../assets/guides/remote-access-4-ready.svg";
import serveSvg from "../../../../assets/guides/remote-access-5-serve.svg";
import restartSvg from "../../../../assets/guides/remote-access-6-restart.svg";

// Admin → Remote access (design §4.8, R7 a; t-20f0718990, owner m-3136ceca05 "nothing clear on that tab. no
// mention about the tailscale setup"): a numbered, guided Tailscale setup. Each step says what to do, shows
// its diagram (assets/guides/remote-access-*.svg) and a done / not done chip computed from the live
// GET /v1/admin/tailnet (the board runs `tailscale status` / `tailscale serve status`); Check again re-reads
// it. guides/remote-access.md is the same walk as a written guide, opened from the header.

const TAILSCALE_DL = [
  { os: "Windows", href: "https://tailscale.com/download/windows" },
  { os: "macOS", href: "https://tailscale.com/download/mac" },
  { os: "Linux", href: "https://tailscale.com/download/linux" },
];

type StepState = "done" | "todo" | "info";

/** Each step's state from the live facts; exported for the tests. */
export function remoteSteps(t: TailnetView | undefined): Record<"installed" | "signedIn" | "ready" | "served" | "restarted", boolean> {
  const installed = Boolean(t?.tailscale);
  const signedIn = installed && t?.tailscale?.backend === "Running" && Boolean(t?.tailscale?.dns);
  const served = Boolean(t?.public_mode && t.serve_proxies.length);
  return {
    installed,
    signedIn,
    // public mode on means apply already passed its own readiness check
    ready: Boolean(t && (t.blockers === 0 || served)),
    served,
    restarted: Boolean(t && served && t.running_public === true),
  };
}

function Step({ n, title, state, img, alt, children, testid }: {
  n: number; title: string; state: StepState; img: string; alt: string; children: React.ReactNode; testid: string;
}): React.JSX.Element {
  const word = state === "done" ? "Done" : state === "todo" ? "Not done yet" : "Read first";
  return (
    <li className={`${styles.card} ${styles.guideStep}`} data-testid={testid} data-state={state}>
      <div className={styles.guideBody}>
        <div className={styles.cardHead}>
          <h3 className={styles.cardTitle}><span className={styles.guideNum} aria-hidden="true">{n}</span>{title}</h3>
          <span className={`${ui.chip} ${state === "done" ? ui.done : state === "todo" ? ui.active : ""}`} data-testid={`${testid}-state`}>
            <span className={ui.chipDot} aria-hidden="true" />{word}
          </span>
        </div>
        {children}
      </div>
      <img className={styles.guideImg} src={img} alt={alt} width={320} height={150} />
    </li>
  );
}

function GuideFold(): React.JSX.Element {
  const [open, setOpen] = useState(false);
  const g = useQuery({ queryKey: ["admin", "tailnet", "guide"], queryFn: getTailnetGuide, retry: false, enabled: open });
  return (
    <details className={ui.fold} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)} data-testid="remote-guide">
      <summary>Read the written guide (guides/remote-access.md)</summary>
      {g.data ? <Markdown html={g.data.html} /> : g.isError ? <AdminError error={g.error} testid="remote-guide-error" /> : open ? <p className={ui.empty}>Loading…</p> : null}
    </details>
  );
}

export function RemoteTab({ onRestartRequired }: { onRestartRequired: (services: string[]) => void }): React.JSX.Element {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "tailnet"], queryFn: getTailnet, retry: false });
  const [force, setForce] = useState(false);
  const after = () => { onRestartRequired(["board", "mcp"]); void qc.invalidateQueries({ queryKey: ["admin", "tailnet"] }); };
  const apply = useMutation({ mutationFn: () => applyTailnet(force), onSuccess: after });
  const remove = useMutation({ mutationFn: removeTailnet, onSuccess: after });
  const t = q.data;
  const s = remoteSteps(t);
  const blockers = (t?.rows ?? []).filter((r) => r.level === "BLOCKER");
  const st = (b: boolean): StepState => (b ? "done" : "todo");
  const applyBlocked = !s.signedIn ? "Finish step 3 first: sign in to Tailscale on this computer." : null;
  return (
    <div className={styles.panel} data-testid="admin-remote">
      <section className={styles.card}>
        <div className={styles.cardHead}>
          <h2 className={styles.cardTitle}>Remote access over Tailscale</h2>
          <button type="button" className={ui.button} onClick={() => void q.refetch()} disabled={q.isFetching} data-testid="remote-refresh">
            {q.isFetching ? "Checking…" : "Check again"}
          </button>
        </div>
        <p className={styles.fieldDoc} data-testid="remote-progress">
          {t ? `${[s.installed, s.signedIn, s.ready, s.served, s.restarted].filter(Boolean).length} of 5 steps done. ` : ""}
          Follow the steps in order; each one checks itself when you press Check again.
        </p>
        <GuideFold />
        <AdminError error={q.error} testid="remote-error" />
      </section>

      <ol className={styles.guide} data-testid="remote-steps">
        <Step n={1} title="What Remote access is for" state="info" img={purposeSvg} testid="remote-step-purpose"
          alt="Your phone, a laptop and a teammate reach this board over your private tailnet">
          <p className={styles.fieldDoc}>Out of the box only this computer can open the board. Remote access lets your own phone or laptop, and teammates you invite, reach it too.</p>
          <p className={styles.fieldDoc}>It uses Tailscale, a free private network between your devices (a "tailnet"). The board is never put on the open internet: only devices signed in to your tailnet can reach it, and each request still needs a Heronry token.</p>
        </Step>

        <Step n={2} title="Install Tailscale on this computer" state={st(s.installed)} img={installSvg} testid="remote-step-install"
          alt="Download Tailscale for Windows, macOS or Linux and install it on this computer">
          <p className={styles.fieldDoc}>Install it on the computer that runs the board:</p>
          <div className={styles.row}>
            {TAILSCALE_DL.map((d) => <a key={d.os} className={ui.button} href={d.href} target="_blank" rel="noreferrer" data-testid={`remote-download-${d.os}`}>{d.os}</a>)}
          </div>
          <p className={styles.usage} data-testid="remote-backend">
            {t?.tailscale ? `Detected: tailscale status answers (${t.tailscale.backend ?? "unknown state"}).` : "Not detected: tailscale is not installed, or its service is not running."}
          </p>
        </Step>

        <Step n={3} title="Sign in" state={st(s.signedIn)} img={signinSvg} testid="remote-step-signin"
          alt="Sign in to Tailscale; this page then reads tailscale status and shows Running">
          <p className={styles.fieldDoc}>Open the Tailscale app and log in, or run <code>tailscale up</code> in a terminal. Sign in the same way on each device that should reach the board.</p>
          <p className={styles.usage} data-testid="remote-signin">
            {s.signedIn ? `Signed in as ${t?.tailscale?.dns}.` : !s.installed ? "Waiting for step 2." : `Tailscale says ${t?.tailscale?.backend ?? "nothing"}; it must say Running.`}
          </p>
        </Step>

        <Step n={4} title="Check readiness" state={st(s.ready)} img={readySvg} testid="remote-step-ready"
          alt="Readiness checklist: admin token, loopback bind, tokens; every blocker cleared">
          <p className={styles.fieldDoc}>The board must be safe to share: a real admin token, listening on this computer only, and tokens for people and agents. Turning on public mode (step 5) fixes the ones marked "apply does".</p>
          {t ? (
            <p className={styles.usage} data-testid="remote-blockers">{t.blockers ? `${t.blockers} blocker${t.blockers === 1 ? "" : "s"} left:` : "No blockers."}</p>
          ) : null}
          {blockers.length ? (
            <ul className={styles.fieldDoc} data-testid="remote-blocker-list">
              {blockers.map((r, i) => <li key={i}><strong>{r.area}</strong>: {r.text}{r.fix ? <div className={styles.usage}>Fix: {r.fix}</div> : null}</li>)}
            </ul>
          ) : null}
          {t?.blockers ? (
            <label className={styles.row}><input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} data-testid="remote-force" /> turn on public mode despite these blockers</label>
          ) : null}
          {t ? (
            <details className={ui.fold} data-testid="remote-readiness">
              <summary>Every check ({t.rows.length})</summary>
              <div className={styles.tableWrap}>
                <table className={styles.table}>
                  <thead><tr><th>Level</th><th>Check</th><th>Detail</th></tr></thead>
                  <tbody>
                    {t.rows.map((r, i) => (
                      <tr key={i}><td><span className={ui.chip}>{r.level}</span></td><td>{r.area ?? ""}</td>
                        <td>{r.text ?? ""}{r.fix ? <div className={styles.usage}>{r.fix}</div> : null}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          ) : null}
        </Step>

        <Step n={5} title="Serve the board on your tailnet" state={st(s.served)} img={serveSvg} testid="remote-step-serve"
          alt="tailscale serve publishes https://your-machine.ts.net on the tailnet and forwards to the board on 127.0.0.1">
          <p className={styles.fieldDoc}>Public mode runs <code>tailscale serve</code> so <code>{t?.tailnet_url ?? "https://<this machine>.ts.net"}</code> reaches this board, and requires a token for every request. Teammate invites then carry that address.</p>
          {t ? (
            <div className={styles.row} data-testid="remote-switch">
              <span>Public mode: <strong data-testid="remote-mode">{t.public_mode ? "on (tailnet)" : "off (this computer only)"}</strong></span>
              {t.public_mode ? (
                <button type="button" className={ui.button} disabled={remove.isPending} onClick={() => remove.mutate()} data-testid="remote-remove">
                  {remove.isPending ? "Turning off…" : "Turn off"}
                </button>
              ) : (
                <button type="button" className={`${ui.button} ${ui.buttonPrimary}`} disabled={apply.isPending || Boolean(applyBlocked)}
                  onClick={() => apply.mutate()} data-testid="remote-apply" aria-describedby={applyBlocked ? "remote-apply-why" : undefined}>
                  {apply.isPending ? "Turning on…" : "Turn on"}
                </button>
              )}
              {applyBlocked && !t.public_mode ? <span id="remote-apply-why" className={styles.fieldNote} data-testid="remote-apply-why">{applyBlocked}</span> : null}
            </div>
          ) : null}
          {t ? (
            <div className={styles.row} data-testid="remote-public-url">
              <span>Address:</span>
              {t.public_url ? <><a href={t.public_url}>{t.public_url}</a><CopyButton text={t.public_url} testid="remote-public-url-copy" /></> : <span className={styles.usage}>none yet</span>}
            </div>
          ) : null}
          {t ? (
            <p className={styles.usage} data-testid="remote-serve">
              tailscale serve: {t.serve_proxies.length ? t.serve_proxies.map((p) => `${p.from} → ${p.to}`).join(", ") : "nothing served"}
            </p>
          ) : null}
          <AdminError error={apply.error ?? remove.error} testid="remote-action-error" />
          <Done text={apply.data?.hint ?? remove.data?.hint} testid="remote-action-done" />
        </Step>

        <Step n={6} title="Restart the board and MCP" state={st(s.restarted)} img={restartSvg} testid="remote-step-restart"
          alt="Restart the board and MCP from Services so they start in public mode">
          <p className={styles.fieldDoc}>The board and the MCP server read the address when they start. Use the Restart buttons in the banner above, or Admin → Services.</p>
          <p className={styles.usage} data-testid="remote-restart">
            {!s.served ? "Waiting for step 5." : t?.running_public === true ? "The board is running in public mode." : t?.running_public === false ? "The board still runs in this-computer-only mode: restart it." : "Restart the board, then press Check again."}
          </p>
        </Step>
      </ol>
    </div>
  );
}
