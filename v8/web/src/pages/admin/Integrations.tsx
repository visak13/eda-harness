import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getHarnesses, getIntegrations, putPlane, putSlack, testCodeServer, testPlane, testSlack, testVscode, updateHarness,
} from "../../api/admin";
import type { SettingValue } from "../../api/admin";
import ui from "../../components/ui.module.css";
import styles from "./Admin.module.css";
import { AdminError, Done, Secret, SettingField, formValue, toPut } from "./shared";

// Admin → Integrations (design §4.8, §4.10): Slack, VS Code, code-server, Plane and the seat harnesses, each
// with its live status and a Test. slack_map.json and the Plane settings stay the backing stores.

const MASK = "********";

function SlackCard({ onRestartRequired }: { onRestartRequired: (s: string[]) => void }): React.JSX.Element {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "integrations"], queryFn: getIntegrations, retry: false });
  const slack = q.data?.slack;
  const [bot, setBot] = useState("");
  const [webhook, setWebhook] = useState("");
  const [boardUrl, setBoardUrl] = useState("");
  const [who, setWho] = useState("");
  useEffect(() => { setBoardUrl(String(slack?.config.board_url ?? "")); }, [slack?.config.board_url]);
  const save = useMutation({
    mutationFn: () => {
      const values: Record<string, unknown> = {};
      if (bot) values.bot_token = bot;
      if (webhook) values.webhook_url = webhook;
      if (boardUrl !== String(slack?.config.board_url ?? "")) values.board_url = boardUrl || null;
      return putSlack(values);
    },
    onSuccess: () => { setBot(""); setWebhook(""); onRestartRequired(["bridge"]); void qc.invalidateQueries({ queryKey: ["admin", "integrations"] }); },
  });
  const test = useMutation({ mutationFn: () => testSlack(who || undefined) });
  const people = Object.entries(slack?.people_effective ?? {});
  return (
    <section className={styles.card} data-testid="integration-slack">
      <div className={styles.cardHead}>
        <h2 className={styles.cardTitle}>Slack</h2>
        <span className={ui.chip} data-testid="slack-status">{slack ? (slack.webhook_set || slack.bot_token_set ? "configured" : "not configured") : "…"}</span>
      </div>
      <AdminError error={q.error} testid="slack-error" />
      <form className={styles.panel} onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        <label className={styles.capCell}>Bot token
          <input className={ui.input} type="password" autoComplete="new-password" value={bot} onChange={(e) => setBot(e.target.value)}
            placeholder={slack?.bot_token_set ? `set ${MASK}: type to replace` : "xoxb-… (optional)"} data-testid="slack-bot-token" />
        </label>
        <label className={styles.capCell}>Default webhook
          <input className={ui.input} type="url" value={webhook} onChange={(e) => setWebhook(e.target.value)}
            placeholder={slack?.webhook_set ? `${String(slack.config.webhook_url ?? "")}: paste a new one to replace` : "https://hooks.slack.com/services/…"} data-testid="slack-webhook" />
        </label>
        <label className={styles.capCell}>Board URL in messages
          <input className={ui.input} value={boardUrl} onChange={(e) => setBoardUrl(e.target.value)} data-testid="slack-board-url" />
        </label>
        <div className={styles.row}>
          <button type="submit" className={`${ui.button} ${ui.buttonPrimary}`} disabled={save.isPending} data-testid="slack-save">{save.isPending ? "Saving…" : "Save Slack"}</button>
          <select className={ui.select} value={who} onChange={(e) => setWho(e.target.value)} aria-label="Test destination" data-testid="slack-test-who">
            <option value="">default webhook</option>
            {people.map(([h]) => <option key={h} value={h}>{h}</option>)}
          </select>
          <button type="button" className={ui.button} disabled={test.isPending} onClick={() => test.mutate()} data-testid="slack-test">{test.isPending ? "Sending…" : "Test"}</button>
        </div>
      </form>
      <AdminError error={save.error} testid="slack-save-error" />
      <AdminError error={test.error} testid="slack-test-error" />
      <Done text={save.isSuccess ? save.data.hint : null} testid="slack-saved" />
      <Done text={test.isSuccess ? `Test ping sent to ${test.data.value.to}.` : null} testid="slack-test-done" />
      {people.length ? (
        <details className={ui.fold}><summary>People the bridge pings ({people.length})</summary>
          <ul>{people.map(([h, p]) => <li key={h}><strong>{h}</strong> · {String(p.slack_id ?? p.webhook_url ?? "")} <span className={styles.usage}>({p.source})</span></li>)}</ul>
        </details>
      ) : null}
      <p className={styles.fieldDoc}>Backed by {slack?.path ?? "slack_map.json"}; each person can also set their own Slack in Settings → Slack.</p>
    </section>
  );
}

function VscodeCard(): React.JSX.Element {
  const q = useQuery({ queryKey: ["admin", "integrations"], queryFn: getIntegrations, retry: false });
  const v = q.data?.vscode;
  const test = useMutation({ mutationFn: testVscode });
  return (
    <section className={styles.card} data-testid="integration-vscode">
      <div className={styles.cardHead}><h2 className={styles.cardTitle}>VS Code</h2>
        <button type="button" className={ui.button} disabled={test.isPending} onClick={() => test.mutate()} data-testid="vscode-test">Test</button></div>
      {v ? (
        <>
          <p className={styles.fieldDoc}>Install the EDP Code extension ({v.extension_id}) from the <a href={v.vsix_url} target="_blank" rel="noreferrer">latest release (.vsix)</a>, then sign in with the teammate's link.</p>
          <Secret label="Board URL" value={v.board_url} testid="vscode-board-url" />
          {Object.entries(v.signin_links).map(([h, link]) => <Secret key={h} label={`Sign-in: ${h}`} value={link} testid={`vscode-signin-${h}`} />)}
        </>
      ) : null}
      <AdminError error={test.error} testid="vscode-test-error" />
      <Done text={test.isSuccess ? `The board answers at ${test.data.value.board_url}.` : null} testid="vscode-test-done" />
    </section>
  );
}

function CodeServerCard(): React.JSX.Element {
  const q = useQuery({ queryKey: ["admin", "integrations"], queryFn: getIntegrations, retry: false });
  const c = q.data?.code_server;
  const test = useMutation({ mutationFn: testCodeServer });
  return (
    <section className={styles.card} data-testid="integration-code-server">
      <div className={styles.cardHead}><h2 className={styles.cardTitle}>code-server</h2>
        <span className={ui.chip}>{c ? (c.running ? "running" : "not running") : "…"}</span>
        <button type="button" className={ui.button} disabled={test.isPending} onClick={() => test.mutate()} data-testid="code-server-test">Test</button></div>
      {c ? <p className={styles.fieldDoc}>Port {c.port}, loopback only (never exposed on the tailnet; the Code tab embeds it through the board). {c.running ? "" : `Start it on the host with ${c.start_command ?? "its start script"}.`}</p> : null}
      <AdminError error={test.error} testid="code-server-test-error" />
      <Done text={test.isSuccess ? "code-server answers." : null} testid="code-server-test-done" />
    </section>
  );
}

function PlaneCard({ onRestartRequired }: { onRestartRequired: (s: string[]) => void }): React.JSX.Element {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "integrations"], queryFn: getIntegrations, retry: false });
  const plane = q.data?.plane;
  const [draft, setDraft] = useState<Record<string, string | boolean>>({});
  const save = useMutation({
    mutationFn: () => {
      const values: Record<string, SettingValue> = {};
      for (const s of plane?.settings ?? []) {
        if (!(s.key in draft)) continue;
        if (s.secret && draft[s.key] === "") continue;
        values[s.key] = toPut(s, draft[s.key]);
      }
      return putPlane(values);
    },
    onSuccess: ({ value }) => { setDraft({}); onRestartRequired(value.restart_required); void qc.invalidateQueries({ queryKey: ["admin"] }); },
  });
  const test = useMutation({ mutationFn: testPlane });
  return (
    <section className={styles.card} data-testid="integration-plane">
      <div className={styles.cardHead}><h2 className={styles.cardTitle}>Plane</h2>
        <span className={ui.chip}>{plane ? (plane.configured ? "configured" : "not configured") : "…"}</span></div>
      {(plane?.settings ?? []).map((s) => (
        <SettingField key={s.key} s={s} value={draft[s.key] ?? formValue(s)} onChange={(v) => setDraft((d) => ({ ...d, [s.key]: v }))} />
      ))}
      <div className={styles.row}>
        <button type="button" className={`${ui.button} ${ui.buttonPrimary}`} disabled={!Object.keys(draft).length || save.isPending} onClick={() => save.mutate()} data-testid="plane-save">Save Plane</button>
        <button type="button" className={ui.button} disabled={test.isPending} onClick={() => test.mutate()} data-testid="plane-test">Test</button>
      </div>
      <AdminError error={save.error} testid="plane-save-error" />
      <AdminError error={test.error} testid="plane-test-error" />
      <Done text={test.isSuccess ? test.data.value.message : save.isSuccess ? save.data.hint : null} testid="plane-done" />
    </section>
  );
}

function HarnessesCard(): React.JSX.Element {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "harnesses"], queryFn: () => getHarnesses(true), retry: false });
  const [wait, setWait] = useState(false);
  const upd = useMutation({ mutationFn: (h: string) => updateHarness(h, wait), onSettled: () => void qc.invalidateQueries({ queryKey: ["admin", "harnesses"] }) });
  const rows = q.data?.harnesses ?? [];
  return (
    <section className={styles.card} data-testid="integration-harnesses">
      <div className={styles.cardHead}><h2 className={styles.cardTitle}>Seat harnesses</h2>
        <button type="button" className={ui.button} onClick={() => void q.refetch()} data-testid="harnesses-test">Test</button></div>
      <p className={styles.fieldDoc}>The app never updates claude, codex or pi on its own. Update when idle runs the vendor's own command only while no seat of that harness is live.</p>
      <AdminError error={q.error} testid="harnesses-error" />
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead><tr><th>Harness</th><th>Installed</th><th>Latest</th><th>Signed in</th><th>Live seats</th><th /></tr></thead>
          <tbody>
            {rows.map((h) => (
              <tr key={h.harness} data-testid={`harness-${h.harness}`}>
                <td><strong>{h.harness}</strong>{h.selected ? <div className={styles.usage}>selected</div> : null}{h.path ? <div className={ui.idMono}>{h.path}</div> : null}</td>
                <td>{h.installed ? h.version ?? "yes" : "not installed"}</td>
                <td>{h.latest ?? "—"}</td>
                <td>{h.signed_in === null ? "—" : h.signed_in ? "yes" : "no"}</td>
                <td>{h.live_seats === null ? "unknown" : h.live_seats.length}</td>
                <td>
                  <button type="button" className={`${ui.button} ${styles.small}`} disabled={!h.installed || upd.isPending || h.update?.state === "waiting" || h.update?.state === "running"}
                    onClick={() => upd.mutate(h.harness)} data-testid={`harness-${h.harness}-update`}>Update when idle</button>
                  {h.update ? <div className={styles.usage}>{h.update.state}{h.update.after ? ` → ${h.update.after}` : ""}</div> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <label className={styles.row}><input type="checkbox" checked={wait} onChange={(e) => setWait(e.target.checked)} data-testid="harness-wait" /> wait for live seats to finish instead of refusing</label>
      <AdminError error={upd.error} testid="harness-update-error" />
      <Done text={upd.data?.hint} testid="harness-update-done" />
    </section>
  );
}

export function IntegrationsTab({ onRestartRequired }: { onRestartRequired: (services: string[]) => void }): React.JSX.Element {
  return (
    <div className={styles.panel} data-testid="admin-integrations">
      <SlackCard onRestartRequired={onRestartRequired} />
      <VscodeCard />
      <CodeServerCard />
      <PlaneCard onRestartRequired={onRestartRequired} />
      <HarnessesCard />
    </div>
  );
}
