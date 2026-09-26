import { useState } from "react";
import { Link } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createTeammate, getAgentTokens, getTailnet, getTeammates, mintTailscaleKey, reinviteTeammate, revokeAgentToken,
  revokeTeammate, rotateTeammate, setTeammateAdmin,
} from "../../api/admin";
import type { Invite, TailscaleKey } from "../../api/admin";
import { approveAccess, denyAccess, getAccessRequests, removeTeammate, type AccessRequestRow, type TeammateRow } from "../../api/access";
import ui from "../../components/ui.module.css";
import styles from "./Admin.module.css";
import { AdminError, Done, Secret } from "./shared";
import own from "./Teammates.module.css";

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

/** t-5dd0cc18ea (owner m-b9c54cb63b): how a colleague joins, in three steps, and what they cannot bring. */
function HowInviting({ remoteOn }: { remoteOn: boolean }): React.JSX.Element {
  return (
    <section className={styles.card} data-testid="how-inviting">
      <h2 className={styles.cardTitle}>How inviting works</h2>
      <ol className={styles.steps} data-testid="how-inviting-steps">
        <li><strong>Add their name</strong> below. You get a one-time link that signs them in; it works once, within 24 hours.</li>
        <li><strong>Connect their machine</strong> to your tailnet: pick them under "Tailscale auth key" and press Mint key, then send them the key.</li>
        <li><strong>Send them the link.</strong> It opens this board over your tailnet, so Remote access must be on{remoteOn ? " (it is)" : ""}.</li>
      </ol>
      <p className={styles.fieldDoc} data-testid="how-inviting-agents">
        Agent teammates are seats this board starts on this computer. A colleague works with the same agents; they can't bring their own.
      </p>
      {!remoteOn ? (
        <p className={ui.banner} data-testid="how-inviting-remote-off">
          Remote access is off, so an invite link would not reach anyone. Turn it on in <Link to="/admin?tab=remote">Remote access</Link> first.
        </p>
      ) : null}
    </section>
  );
}

function InviteForm({ remoteOn }: { remoteOn: boolean }): React.JSX.Element {
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
        <button type="submit" className={`${ui.button} ${ui.buttonPrimary}`} disabled={!remoteOn || !handle.trim() || m.isPending} data-testid="invite-submit"
          title={remoteOn ? undefined : "Turn on Remote access first: the invite link only works over your tailnet."} aria-describedby={remoteOn ? undefined : "invite-off-reason"}>
          {m.isPending ? "Inviting…" : "Invite"}
        </button>
      </form>
      {!remoteOn ? <p className={styles.fieldNote} id="invite-off-reason" data-testid="invite-off-reason">Invite is off while Remote access is off: the link only works over your tailnet.</p> : null}
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
      <p className={styles.fieldDoc}>Mint a key so a colleague's machine joins your tailnet and can reach this board.</p>
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

/** t-882e4d2eeb: access requests from the sign-in page. Each pending row carries DOM id = the request id, so
 *  the attention trail (S20) can highlight and scroll to it. Approve creates the teammate through the invite
 *  path and their waiting browser signs itself in; nothing is sent to them by hand. */
function AccessRequests({ remoteOn }: { remoteOn: boolean }): React.JSX.Element {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "access-requests"], queryFn: getAccessRequests, retry: false });
  const [handles, setHandles] = useState<Record<string, string>>({});
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["admin", "access-requests"] });
    void qc.invalidateQueries({ queryKey: ["admin", "teammates"] });
  };
  const approve = useMutation({ mutationFn: (r: AccessRequestRow) => approveAccess(r.id, handles[r.id]?.trim() ? { handle: handles[r.id].trim() } : {}), onSuccess: refresh });
  const deny = useMutation({ mutationFn: (r: AccessRequestRow) => denyAccess(r.id), onSuccess: refresh });
  const rows = q.data ?? [];
  const pending = rows.filter((r) => r.status === "pending");
  const decided = rows.filter((r) => r.status !== "pending");
  return (
    <section className={styles.card} data-testid="access-requests">
      <h2 className={styles.cardTitle}>Requests{pending.length ? ` (${pending.length})` : ""}</h2>
      <p className={styles.fieldDoc}>
        People without a token can ask for access from the sign-in page{remoteOn ? "" : " once Remote access is on"}.
        Approve signs them in on their own page; their token is never shown here or sent in a message.
      </p>
      <AdminError error={q.error} testid="access-requests-error" />
      {!pending.length && !q.isLoading ? <p className={ui.empty} data-testid="access-requests-empty">No open requests.</p> : null}
      {pending.map((r) => (
        <div key={r.id} id={r.id} className={own.request} data-testid={`access-request-${r.id}`}>
          <div>
            <strong>{r.name}</strong> asks for access as <strong>{r.role_wanted === "owner" ? "member" : r.role_wanted}</strong>
            <div className={styles.usage}>{r.created_at}</div>
            {r.note ? <p className={styles.fieldDoc}>{r.note}</p> : null}
          </div>
          <div className={styles.actions}>
            <input className={ui.input} placeholder="handle (optional)" value={handles[r.id] ?? ""} aria-label={`Handle for ${r.name}`}
              onChange={(e) => setHandles((h) => ({ ...h, [r.id]: e.target.value }))} data-testid={`access-request-${r.id}-handle`} />
            <button type="button" className={`${ui.button} ${ui.buttonPrimary} ${styles.small}`} disabled={approve.isPending || deny.isPending}
              onClick={() => approve.mutate(r)} data-testid={`access-request-${r.id}-approve`}>Approve</button>
            <button type="button" className={`${ui.button} ${styles.small}`} disabled={approve.isPending || deny.isPending}
              onClick={() => deny.mutate(r)} data-testid={`access-request-${r.id}-deny`}>Deny</button>
          </div>
        </div>
      ))}
      <AdminError error={approve.error ?? deny.error} testid="access-request-action-error" />
      {decided.length ? (
        <details className={own.decided}>
          <summary>Decided recently ({decided.length})</summary>
          <ul>
            {decided.map((r) => (
              <li key={r.id} data-testid={`access-decided-${r.id}`}>
                {r.name}: {r.status === "denied" ? "declined" : r.status === "claimed" ? `signed in as ${r.handle}` : `approved as ${r.handle}, waiting for their page`}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );
}

/** Remove = revoke + retire, behind a confirm step (t-882e4d2eeb). */
function RemoveButton({ handle, onDone }: { handle: string; onDone: (hint: string) => void }): React.JSX.Element {
  const [confirming, setConfirming] = useState(false);
  const m = useMutation({ mutationFn: () => removeTeammate(handle), onSuccess: ({ hint }) => { setConfirming(false); onDone(hint); } });
  if (!confirming) {
    return (
      <button type="button" className={`${ui.button} ${styles.small}`} onClick={() => setConfirming(true)} data-testid={`teammate-${handle}-remove`}>Remove</button>
    );
  }
  return (
    <span className={own.confirm} role="group" aria-label={`Remove ${handle}?`} data-testid={`teammate-${handle}-remove-confirm`}>
      <span>Remove {handle}? Their token stops working and they leave every people list.</span>
      <button type="button" className={`${ui.button} ${ui.buttonPrimary} ${styles.small}`} disabled={m.isPending}
        onClick={() => m.mutate()} data-testid={`teammate-${handle}-remove-yes`}>Remove</button>
      <button type="button" className={`${ui.button} ${styles.small}`} onClick={() => setConfirming(false)}
        data-testid={`teammate-${handle}-remove-no`}>Cancel</button>
      {m.error ? <AdminError error={m.error} testid={`teammate-${handle}-remove-error`} /> : null}
    </span>
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
  const tail = useQuery({ queryKey: ["admin", "tailnet"], queryFn: getTailnet, retry: false });
  const remoteOn = Boolean(tail.data?.public_mode);
  const [showRemoved, setShowRemoved] = useState(false);
  const [removedHint, setRemovedHint] = useState<string | null>(null);
  const all = (q.data ?? []) as TeammateRow[];
  const removed = all.filter((t) => t.retired);
  const rows = showRemoved ? all : all.filter((t) => !t.retired);
  const actionError = revoke.error ?? rotate.error ?? reinvite.error ?? flag.error;
  const hint = removedHint ?? revoke.data?.hint ?? null;
  return (
    <div className={styles.panel} data-testid="admin-teammates">
      <HowInviting remoteOn={remoteOn} />
      <InviteForm remoteOn={remoteOn} />
      <AccessRequests remoteOn={remoteOn} />
      <section className={styles.card} data-testid="teammates">
        <h2 className={styles.cardTitle}>Teammates</h2>
        <AdminError error={q.error} testid="teammates-error" />
        {removed.length ? (
          <label className={styles.row}>
            <input type="checkbox" checked={showRemoved} onChange={(e) => setShowRemoved(e.target.checked)} data-testid="teammates-show-removed" />
            Show removed ({removed.length})
          </label>
        ) : null}
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead><tr><th>Handle</th><th>Role</th><th>Admin</th><th>Signed in</th><th>Last seen</th><th>Actions</th></tr></thead>
            <tbody>
              {rows.map((t) => (
                <tr key={t.handle} data-testid={`teammate-${t.handle}`} className={t.retired ? own.removed : undefined}>
                  <td><strong>{t.handle}</strong>{t.init_human ? <div className={styles.usage}>init human</div> : null}
                    {t.retired ? <div className={styles.usage}><span className={ui.chip}>removed</span></div>
                      : !t.has_token && !t.invite_expires ? <div className={styles.usage}>no token: hidden from people lists</div> : null}</td>
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
                      {!t.init_human && !t.retired ? <RemoveButton handle={t.handle} onDone={(h) => { setShown(null); setRemovedHint(h); refresh(); }} /> : null}
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
      <TailscaleKeyPanel handles={all.filter((r) => !r.retired).map((r) => r.handle)} />
      <AgentTokens />
    </div>
  );
}
