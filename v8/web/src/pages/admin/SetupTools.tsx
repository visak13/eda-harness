import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getPrereqs, installPrereq, type PrereqRow } from "../../api/prereqs";
import ui from "../../components/ui.module.css";
import styles from "./Admin.module.css";
import { AdminError, CopyButton } from "./shared";

// /ui/setup step "Your tools" (t-08612be1b0): the checklist of the one prerequisites manifest. Each row is
// found (with its version), missing with an Install button that runs the same `heronry prereqs install` step
// the installer runs, or an optional feature that is off. A harness that is installed but not signed in shows
// the sign-in command, and the row flips to "signed in" when the board sees the login land (polled).

const NEED: Record<PrereqRow["need"], string> = {
  required: "required", harness: "a seat harness (claude or codex)", optional: "optional", default: "on by default",
};

function stateText(r: PrereqRow): string {
  if (r.job?.state === "running") return "Installing…";
  if (r.state === "ok") return r.version ? `Found ${r.version}` : "Found";
  if (r.state === "off") return `Off: turns on ${r.feature}`;
  if (r.state === "outdated") return `Too old: ${r.fix}`;
  return "Missing";
}

function Row({ r }: { r: PrereqRow }): React.JSX.Element {
  const qc = useQueryClient();
  const install = useMutation({
    mutationFn: () => installPrereq(r.name),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["admin", "prereqs"] }),
  });
  const running = r.job?.state === "running" || install.isPending;
  const canInstall = r.state !== "ok" && r.installable && !running;
  return (
    <tr data-testid={`prereq-${r.name}`} data-state={r.state}>
      <td><strong>{r.name}</strong><div className={styles.usage}>{r.purpose}</div></td>
      <td className={styles.usage}>{NEED[r.need]}</td>
      <td data-testid={`prereq-${r.name}-state`}>
        {stateText(r)}
        {r.state !== "ok" && r.state !== "off" ? <div className={styles.usage}>{r.fix}</div> : null}
        {r.job?.state === "failed" ? (
          <details className={styles.details} data-testid={`prereq-${r.name}-failed`}>
            <summary>The install failed (exit {String(r.job.exit)})</summary>
            <pre className={styles.small}>{r.job.output}</pre>
          </details>
        ) : null}
        {r.state === "ok" && r.login ? (
          r.signed_in ? <div className={styles.usage} data-testid={`prereq-${r.name}-signed-in`}>Signed in</div> : (
            <div data-testid={`prereq-${r.name}-login`}>
              <span className={styles.usage}>Sign in: run this in a terminal, then come back (this page notices).</span>
              <div className={styles.secret}><code className={styles.secretValue}>{r.login}</code><CopyButton text={r.login} testid={`prereq-${r.name}-login-copy`} /></div>
            </div>
          )
        ) : null}
      </td>
      <td>
        {canInstall ? (
          <button type="button" className={ui.button} onClick={() => install.mutate()} data-testid={`prereq-${r.name}-install`}>Install</button>
        ) : r.state !== "ok" && !r.installable ? (
          <a className={styles.linkButton} href={r.docs} target="_blank" rel="noreferrer">Download page</a>
        ) : null}
        <AdminError error={install.error} testid={`prereq-${r.name}-error`} />
      </td>
    </tr>
  );
}

export function ToolsStep({ onDone }: { onDone: () => void }): React.JSX.Element {
  const q = useQuery({
    queryKey: ["admin", "prereqs"],
    queryFn: getPrereqs,
    retry: false,
    // follow an install job or a pending sign-in without a reload
    refetchInterval: (query) => {
      const rows = query.state.data?.rows ?? [];
      return rows.some((r) => r.job?.state === "running" || (r.state === "ok" && r.login && r.signed_in === false)) ? 3000 : false;
    },
  });
  const v = q.data;
  const missing = (v?.rows ?? []).filter((r) => r.need === "required" && r.state !== "ok");
  return (
    <section className={styles.card} data-testid="setup-tools">
      <h2 className={styles.cardTitle}>Your tools</h2>
      <p className={styles.fieldDoc}>What Heronry uses on this machine. Install fills a gap with the same step the installer runs (<code>heronry prereqs install</code>); optional tools only turn a feature on.</p>
      <AdminError error={q.error} testid="setup-tools-error" />
      {v ? (
        <div className={styles.tableWrap}>
          <table className={styles.table} data-testid="setup-tools-table">
            <thead><tr><th>Tool</th><th>Needed</th><th>State</th><th /></tr></thead>
            <tbody>
              {v.rows.map((r) => <Row key={r.name} r={r} />)}
              {v.bundled.map((b) => <tr key={b.name}><td><strong>{b.name}</strong></td><td className={styles.usage}>bundled</td><td className={styles.usage}>{b.why}</td><td /></tr>)}
              {v.not_needed.map((b) => <tr key={b.name} data-testid={`prereq-${b.name}`}><td><strong>{b.name}</strong></td><td className={styles.usage}>not needed</td><td className={styles.usage}>{b.why}</td><td /></tr>)}
            </tbody>
          </table>
        </div>
      ) : null}
      {v && !v.harness_ok ? <p className={ui.banner} role="alert" data-testid="setup-tools-no-harness">No seat harness is installed yet: install claude or codex above; seats need one of them.</p> : null}
      {missing.length ? <p className={styles.fieldDoc} data-testid="setup-tools-missing">Still missing: {missing.map((r) => r.name).join(", ")}. You can go on and install them later from a terminal with <code>heronry prereqs install</code>.</p> : null}
      <div className={styles.row}>
        <button type="button" className={`${ui.button} ${ui.buttonPrimary}`} onClick={onDone} data-testid="setup-next">Next</button>
      </div>
    </section>
  );
}
