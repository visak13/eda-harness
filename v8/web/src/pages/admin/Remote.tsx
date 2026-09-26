import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { applyTailnet, getTailnet, removeTailnet } from "../../api/admin";
import ui from "../../components/ui.module.css";
import styles from "./Admin.module.css";
import { AdminError, Done } from "./shared";

// Admin → Remote access (design §4.8, R7 a): tailnet status, `tailscale serve` state, apply/remove public
// mode and the resulting public URL (the one teammate invites then carry).

export function RemoteTab({ onRestartRequired }: { onRestartRequired: (services: string[]) => void }): React.JSX.Element {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "tailnet"], queryFn: getTailnet, retry: false });
  const [force, setForce] = useState(false);
  const after = () => { onRestartRequired(["board", "mcp"]); void qc.invalidateQueries({ queryKey: ["admin", "tailnet"] }); };
  const apply = useMutation({ mutationFn: () => applyTailnet(force), onSuccess: after });
  const remove = useMutation({ mutationFn: removeTailnet, onSuccess: after });
  const t = q.data;
  return (
    <div className={styles.panel} data-testid="admin-remote">
      <section className={styles.card}>
        <div className={styles.cardHead}>
          <h2 className={styles.cardTitle}>Remote access over Tailscale</h2>
          <button type="button" className={ui.button} onClick={() => void q.refetch()} data-testid="remote-refresh">Check again</button>
        </div>
        <AdminError error={q.error} testid="remote-error" />
        {t ? (
          <>
            <div className={ui.metaRow}><span>Tailscale</span><span data-testid="remote-backend">{t.tailscale ? `${t.tailscale.backend ?? "unknown"}${t.tailscale.dns ? ` · ${t.tailscale.dns}` : ""}` : "not installed or not running"}</span></div>
            <div className={ui.metaRow}><span>Mode</span><span data-testid="remote-mode">{t.public_mode ? "public (tailnet)" : "trusted (loopback only)"}</span></div>
            <div className={ui.metaRow}><span>Public URL</span><span data-testid="remote-public-url">{t.public_url ? <a href={t.public_url}>{t.public_url}</a> : "none"}</span></div>
            <div className={ui.metaRow}><span>Tailnet URL</span><span>{t.tailnet_url ?? "—"}</span></div>
            <div className={ui.metaRow}><span>tailscale serve</span><span>{t.serve_proxies.length ? t.serve_proxies.map((p) => `${p.from} → ${p.to}`).join(", ") : "nothing served"}</span></div>
            <h3 className={ui.sectionLabel}>Readiness ({t.blockers} blocker{t.blockers === 1 ? "" : "s"})</h3>
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead><tr><th>Level</th><th>Check</th><th>Detail</th></tr></thead>
                <tbody>
                  {t.rows.map((r, i) => (
                    <tr key={i}><td><span className={ui.chip}>{r.level}</span></td><td>{String(r.check ?? r.name ?? "")}</td>
                      <td>{String(r.detail ?? r.message ?? "")}{r.fix ? <div className={styles.usage}>{String(r.fix)}</div> : null}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className={styles.row}>
              <button type="button" className={`${ui.button} ${ui.buttonPrimary}`} disabled={apply.isPending || t.public_mode} onClick={() => apply.mutate()} data-testid="remote-apply">
                {apply.isPending ? "Applying…" : "Apply public mode"}
              </button>
              <label className={styles.row}><input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} data-testid="remote-force" /> despite readiness blockers</label>
              <button type="button" className={ui.button} disabled={remove.isPending || !t.public_mode} onClick={() => remove.mutate()} data-testid="remote-remove">
                {remove.isPending ? "Removing…" : "Remove"}
              </button>
            </div>
            <p className={styles.fieldDoc}>Apply serves the board on your tailnet over https and requires a token for every request; restart the board and MCP from Services afterwards. Teammate invites then carry the tailnet URL.</p>
          </>
        ) : null}
        <AdminError error={apply.error ?? remove.error} testid="remote-action-error" />
        <Done text={apply.data?.hint ?? remove.data?.hint} testid="remote-action-done" />
      </section>
    </div>
  );
}
