import { useState } from "react";
import { Link } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createTeammate, getAgentTokens, getTailnet, getTeammates, mintTailscaleKey, reinviteTeammate, revokeAgentToken,
  revokeTeammate, rotateTeammate, setTeammateAdmin,
} from "../../api/admin";
import type { Invite, TailscaleKey } from "../../api/admin";
import ui from "../../components/ui.module.css";
import styles from "./Admin.module.css";
import { AdminError, Done, Secret } from "./shared";

// Admin → Teammates (design §4.8): invite (the one-time link + the VS Code sign-in link, with copy buttons),
// list with last-seen, revoke, rotate, admin flag, the Tailscale auth-key mint (R7 b) and the agent tokens.

function InviteLinks({ invite, who }: { invite: Invite; who: string }): React.JSX.Element {
  return (
    <div className={styles.card} data-testid="invite-result">
      <p className={styles.fieldDoc}>Send {who} this link. It works once, within 24 hours, and signs them in{invite.expires_at ? ` (expires ${invite.expires_at})` : ""}.</p>
      <Secret label="Invite link" value={invite.link} testid="invite-link" />
      <Secret label="VS Code sign-in" value={invite.vscode_link} testid="invite-vscode-link" />
    </div>
  );
}

function InviteForm(): React.JSX.Element {
  const qc = useQueryClient();
  const [handle, setHandle] = useState("");
  const [admin, setAdmin] = useState(false);
  const m = useMutation({
    mutationFn: () => createTeammate({ handle: handle.trim(), admin }),
    onSuccess: () => { setHandle(""); setAdmin(false); void qc.invalidateQueries({ queryKey: ["admin", "teammates"] }); },
  });
  return (
    <section className={styles.card} data-testid="invite">
      <h2 className={styles.cardTitle}>Invite a teammate</h2>
      <form className={styles.row} onSubmit={(e) => { e.preventDefault(); if (handle.trim()) m.mutate(); }}>
        <input className={ui.input} placeholder="handle, e.g. alex" value={handle} onChange={(e) => setHandle(e.target.value)}
          aria-label="Teammate handle" data-testid="invite-handle" />
        <label className={styles.row}><input type="checkbox" checked={admin} onChange={(e) => setAdmin(e.target.checked)} data-testid="invite-admin" /> admin</label>
        <button type="submit" className={`${ui.button} ${ui.buttonPrimary}`} disabled={!handle.trim() || m.isPending} data-testid="invite-submit">
          {m.isPending ? "Inviting…" : "Invite"}
        </button>
      </form>
      <AdminError error={m.error} testid="invite-error" />
      {m.data ? <InviteLinks invite={m.data.value.invite} who={m.data.value.teammate.handle} /> : null}
    </section>
  );
}

function TailscaleKeyPanel({ handles }: { handles: string[] }): React.JSX.Element {
  const tail = useQuery({ queryKey: ["admin", "tailnet"], queryFn: getTailnet, retry: false });
  const configured = Boolean(tail.data?.auth_keys.configured);
  const [who, setWho] = useState("");
  const [ephemeral, setEphemeral] = useState(true);
  const [hours, setHours] = useState("24");
  const [key, setKey] = useState<TailscaleKey | null>(null);
  const m = useMutation({
    mutationFn: () => mintTailscaleKey(who, { ephemeral, expiry_s: Math.max(1, Number(hours) || 24) * 3600 }),
    onSuccess: ({ value }) => setKey(value),
  });
  return (
    <section className={styles.card} data-testid="tailscale-keys">
      <h2 className={styles.cardTitle}>Tailscale auth key for a teammate's machine</h2>
      {!configured ? (
        <p className={ui.banner} data-testid="tailscale-keys-off">
          Off until a Tailscale API credential is set: configure the Tailscale API (OAuth client id and secret, scope auth_keys) in{" "}
          <Link to="/admin?tab=settings">Settings → Network</Link>.
        </p>
      ) : null}
      <form className={styles.row} onSubmit={(e) => { e.preventDefault(); if (who) m.mutate(); }}>
        <select className={ui.select} value={who} onChange={(e) => setWho(e.target.value)} disabled={!configured} aria-label="Teammate" data-testid="tailscale-key-who">
          <option value="">Teammate…</option>
          {handles.map((h) => <option key={h} value={h}>{h}</option>)}
        </select>
        <label className={styles.row}><input type="checkbox" checked={ephemeral} disabled={!configured} onChange={(e) => setEphemeral(e.target.checked)} /> ephemeral</label>
        <label className={styles.row}>expires in <input className={ui.input} type="number" min={1} max={2160} value={hours} disabled={!configured}
          onChange={(e) => setHours(e.target.value)} style={{ width: 80 }} aria-label="Expiry in hours" /> h</label>
        <button type="submit" className={ui.button} disabled={!configured || !who || m.isPending} data-testid="tailscale-key-mint">Mint key</button>
      </form>
      <AdminError error={m.error ?? tail.error} testid="tailscale-key-error" />
      {key ? <><Secret label={`Key for ${key.teammate}`} value={key.key} testid="tailscale-key" />
        <p className={styles.fieldDoc}>Shown once and never stored: they run <code>tailscale up --auth-key=…</code>. Tags: {key.tags.join(", ")}.</p></> : null}
    </section>
  );
}

function AgentTokens(): React.JSX.Element {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "agent-tokens"], queryFn: getAgentTokens, retry: false });
  const m = useMutation({ mutationFn: revokeAgentToken, onSuccess: () => void qc.invalidateQueries({ queryKey: ["admin", "agent-tokens"] }) });
  const rows = q.data ?? [];
  return (
    <section className={styles.card} data-testid="agent-tokens">
      <h2 className={styles.cardTitle}>Agent tokens</h2>
      <p className={styles.fieldDoc}>Minted automatically at spawn. Revoking one refuses that seat's calls at once; a respawn mints a new token.</p>
      <AdminError error={q.error} testid="agent-tokens-error" />
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead><tr><th>Seat</th><th>Role</th><th>Model</th><th>Last seen</th><th /></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.handle} data-testid={`agent-token-${r.handle}`}>
                <td className={ui.idMono}>{r.handle}</td><td>{r.role ?? "—"}</td><td>{r.model ?? "—"}</td><td>{r.last_seen ?? "—"}</td>
                <td>{r.revoked ? <span className={ui.chip}>revoked</span> : (
                  <button type="button" className={`${ui.button} ${styles.small}`} disabled={m.isPending}
                    onClick={() => m.mutate(r.handle)} data-testid={`agent-token-${r.handle}-revoke`}>Revoke</button>
                )}</td>
              </tr>
            ))}
            {!rows.length && !q.isLoading ? <tr><td colSpan={5} className={ui.empty}>No agent tokens.</td></tr> : null}
          </tbody>
        </table>
      </div>
      <AdminError error={m.error} testid="agent-token-revoke-error" />
      <Done text={m.data?.hint} testid="agent-token-revoked" />
    </section>
  );
}

export function TeammatesTab(): React.JSX.Element {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "teammates"], queryFn: getTeammates, retry: false });
  const refresh = () => void qc.invalidateQueries({ queryKey: ["admin", "teammates"] });
  const [shown, setShown] = useState<{ kind: "invite"; handle: string; invite: Invite } | { kind: "token"; handle: string; token: string } | null>(null);
  const revoke = useMutation({ mutationFn: revokeTeammate, onSuccess: () => { setShown(null); refresh(); } });
  const rotate = useMutation({ mutationFn: rotateTeammate, onSuccess: ({ value }) => { setShown({ kind: "token", handle: value.handle, token: value.token }); refresh(); } });
  const reinvite = useMutation({ mutationFn: reinviteTeammate, onSuccess: ({ value }, handle) => { setShown({ kind: "invite", handle, invite: value }); refresh(); } });
  const flag = useMutation({ mutationFn: ({ handle, admin }: { handle: string; admin: boolean }) => setTeammateAdmin(handle, admin), onSuccess: refresh });
  const rows = q.data ?? [];
  const actionError = revoke.error ?? rotate.error ?? reinvite.error ?? flag.error;
  const hint = revoke.data?.hint ?? null;
  return (
    <div className={styles.panel} data-testid="admin-teammates">
      <InviteForm />
      <section className={styles.card} data-testid="teammates">
        <h2 className={styles.cardTitle}>Teammates</h2>
        <AdminError error={q.error} testid="teammates-error" />
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead><tr><th>Handle</th><th>Role</th><th>Admin</th><th>Signed in</th><th>Last seen</th><th>Actions</th></tr></thead>
            <tbody>
              {rows.map((t) => (
                <tr key={t.handle} data-testid={`teammate-${t.handle}`}>
                  <td><strong>{t.handle}</strong>{t.init_human ? <div className={styles.usage}>init human</div> : null}</td>
                  <td>{t.role}</td>
                  <td><input type="checkbox" checked={t.admin} disabled={t.init_human || flag.isPending} aria-label={`${t.handle} is an admin`}
                    onChange={(e) => flag.mutate({ handle: t.handle, admin: e.target.checked })} data-testid={`teammate-${t.handle}-admin`} /></td>
                  <td>{t.has_token ? "yes" : t.invite_expires ? `invited (until ${t.invite_expires})` : "no"}</td>
                  <td>{t.last_seen ?? "—"}</td>
                  <td>
                    <div className={styles.actions}>
                      <button type="button" className={`${ui.button} ${styles.small}`} onClick={() => reinvite.mutate(t.handle)} data-testid={`teammate-${t.handle}-invite`}>New invite</button>
                      <button type="button" className={`${ui.button} ${styles.small}`} disabled={!t.has_token} onClick={() => rotate.mutate(t.handle)} data-testid={`teammate-${t.handle}-rotate`}>Rotate</button>
                      <button type="button" className={`${ui.button} ${styles.small}`} disabled={!t.has_token && !t.invite_expires} onClick={() => revoke.mutate(t.handle)} data-testid={`teammate-${t.handle}-revoke`}>Revoke</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <AdminError error={actionError} testid="teammate-action-error" />
        <Done text={hint} testid="teammate-action-done" />
        {shown?.kind === "invite" ? <InviteLinks invite={shown.invite} who={shown.handle} /> : null}
        {shown?.kind === "token" ? <><Secret label={`New token for ${shown.handle}`} value={shown.token} testid="rotated-token" />
          <p className={styles.fieldDoc}>Shown once: the old token is refused from now on.</p></> : null}
      </section>
      <TailscaleKeyPanel handles={rows.map((r) => r.handle)} />
      <AgentTokens />
    </div>
  );
}
