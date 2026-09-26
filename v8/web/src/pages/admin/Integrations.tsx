import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getHarnesses, getIntegrations, putPlane, putSlack, testCodeServer, testPlane, testSlack, testVscode, updateHarness,
} from "../../api/admin";
import type { SettingValue } from "../../api/admin";
import { PRODUCT_NAME } from "../../brand";
import ui from "../../components/ui.module.css";
import styles from "./Admin.module.css";
import { AdminError, Done, Secret, SettingField, errorText, formValue, toPut } from "./shared";

// Admin → Integrations (design §4.8, §4.10): the seat harnesses, VS Code, Slack, Plane and code-server, each
// with its live status and a Test. slack_map.json and the Plane settings stay the backing stores.
// t-20f0718990 (owner m-3136ceca05 "integrations tab, also very unclear"): every card opens with the same
// four lines (what it lets the app do, what you need, where to get it, what changes once connected) and a
// status line: not set up · set up, not tested · connected (tested) · error with its reason. An action that
// needs an earlier step is disabled and the step is named next to it. Cards run essentials first (README.md).

const MASK = "********";

export type IntegrationState = { kind: "none" } | { kind: "untested" } | { kind: "ok"; detail?: string } | { kind: "error"; reason: string };

/** The status line every card shows. */
export function StatusLine({ state, testid }: { state: IntegrationState; testid: string }): React.JSX.Element {
  const text = state.kind === "none" ? "Not set up"
    : state.kind === "untested" ? "Set up, not tested yet: press Test"
    : state.kind === "ok" ? `Connected (tested)${state.detail ? `: ${state.detail}` : ""}`
    : `Error: ${state.reason}`;
  const tone = state.kind === "ok" ? ui.done : state.kind === "error" ? ui.blocked : state.kind === "untested" ? ui.active : "";
  return (
    <p className={styles.row} data-testid={testid} data-state={state.kind}>
      <span className={`${ui.chip} ${tone}`}><span className={ui.chipDot} aria-hidden="true" />{text}</span>
    </p>
  );
}

/** What it does · what you need · where to get it · what changes: the four plain lines at the top of a card. */
function About({ does, needs, where, changes, testid }: { does: string; needs: string; where: React.ReactNode; changes: string; testid: string }): React.JSX.Element {
  return (
    <dl className={styles.about} data-testid={testid}>
      <dt>What it does</dt><dd>{does}</dd>
      <dt>What you need</dt><dd>{needs}</dd>
      <dt>Where to get it</dt><dd>{where}</dd>
      <dt>Once connected</dt><dd>{changes}</dd>
    </dl>
  );
}

/** A disabled action's reason, visible next to it and tied to it for screen readers. */
function Why({ id, text }: { id: string; text: string | null }): React.JSX.Element | null {
  return text ? <span id={id} className={styles.fieldNote} data-testid={id}>{text}</span> : null;
}

/** State from "is it configured" plus the last Test in this visit. */
function stateOf(configured: boolean | undefined, test: { isSuccess: boolean; isError: boolean; error: unknown }, okDetail?: string, testFailed?: string | null): IntegrationState {
  if (test.isError) return { kind: "error", reason: errorText(test.error) };
  if (testFailed) return { kind: "error", reason: testFailed };
  if (test.isSuccess) return { kind: "ok", detail: okDetail };
  return configured ? { kind: "untested" } : { kind: "none" };
}

function HarnessesCard(): React.JSX.Element {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "harnesses"], queryFn: () => getHarnesses(true), retry: false });
  const [wait, setWait] = useState(false);
  const upd = useMutation({ mutationFn: (h: string) => updateHarness(h, wait), onSettled: () => void qc.invalidateQueries({ queryKey: ["admin", "harnesses"] }) });
  const rows = q.data?.harnesses ?? [];
  const selected = rows.filter((h) => h.selected);
  const missing = selected.filter((h) => !h.installed).map((h) => h.harness);
  const signedOut = selected.filter((h) => h.installed && h.signed_in === false).map((h) => h.harness);
  const ready = selected.filter((h) => h.installed && h.signed_in !== false);
  // GET probes every harness live (`--version`, sign-in), so a loaded view IS a test
  const state: IntegrationState = q.isError ? { kind: "error", reason: errorText(q.error) }
    : !q.data ? { kind: "untested" }
    : !ready.length ? (missing.length || signedOut.length
      ? { kind: "error", reason: [missing.length ? `${missing.join(", ")} not installed` : "", signedOut.length ? `${signedOut.join(", ")} not signed in` : ""].filter(Boolean).join("; ") }
      : { kind: "none" })
    : missing.length || signedOut.length
      ? { kind: "error", reason: `${ready.map((h) => h.harness).join(", ")} ready; ${[missing.length ? `${missing.join(", ")} not installed` : "", signedOut.length ? `${signedOut.join(", ")} not signed in` : ""].filter(Boolean).join("; ")}` }
      : { kind: "ok", detail: ready.map((h) => `${h.harness} ${h.version ?? ""}`.trim()).join(", ") };
  return (
    <section className={styles.card} data-testid="integration-harnesses">
      <div className={styles.cardHead}><h2 className={styles.cardTitle}>Seat harnesses</h2>
        <button type="button" className={ui.button} onClick={() => void q.refetch()} data-testid="harnesses-test">Test</button></div>
      <About testid="about-harnesses"
        does={`The programs that run ${PRODUCT_NAME}'s agents (seats): Claude Code, Codex and Pi.`}
        needs="At least one installed on this computer and signed in with its own account (Claude, ChatGPT, or a provider key for Pi). Pick which ones in Admin → Seats & models."
        where={<><a href="https://code.claude.com/docs/en/setup" target="_blank" rel="noreferrer">Claude Code</a> · <a href="https://github.com/openai/codex#installation" target="_blank" rel="noreferrer">Codex</a> · Pi: <code>npm install -g @earendil-works/pi-coding-agent</code></>}
        changes="Seats can start on that harness; its models show up in Seats & models." />
      <StatusLine state={state} testid="harnesses-status" />
      <p className={styles.fieldDoc}>The app never updates claude, codex or pi on its own. Update when idle runs the vendor's own command only while no seat of that harness is live.</p>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead><tr><th>Harness</th><th>Installed</th><th>Latest</th><th>Signed in</th><th>Live seats</th><th /></tr></thead>
          <tbody>
            {rows.map((h) => {
              const why = !h.installed ? "Not installed: install it first (links above)." : h.update?.state === "waiting" || h.update?.state === "running" ? `An update is ${h.update.state}.` : null;
              return (
                <tr key={h.harness} data-testid={`harness-${h.harness}`}>
                  <td><strong>{h.harness}</strong>{h.selected ? <div className={styles.usage}>selected</div> : <div className={styles.usage}>not selected</div>}{h.path ? <div className={ui.idMono}>{h.path}</div> : null}</td>
                  <td>{h.installed ? h.version ?? "yes" : "not installed"}</td>
                  <td>{h.latest ?? "—"}</td>
                  <td>{h.signed_in === null ? "—" : h.signed_in ? "yes" : "no: sign in with the program itself"}</td>
                  <td>{h.live_seats === null ? "unknown" : h.live_seats.length}</td>
                  <td>
                    <button type="button" className={`${ui.button} ${styles.small}`} disabled={Boolean(why) || upd.isPending} title={why ?? undefined}
                      aria-describedby={why ? `harness-${h.harness}-why` : undefined} onClick={() => upd.mutate(h.harness)} data-testid={`harness-${h.harness}-update`}>Update when idle</button>
                    <Why id={`harness-${h.harness}-why`} text={why} />
                    {h.update ? <div className={styles.usage}>{h.update.state}{h.update.after ? ` → ${h.update.after}` : ""}</div> : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <label className={styles.row}><input type="checkbox" checked={wait} onChange={(e) => setWait(e.target.checked)} data-testid="harness-wait" /> wait for live seats to finish instead of refusing</label>
      <AdminError error={upd.error} testid="harness-update-error" />
      <Done text={upd.data?.hint} testid="harness-update-done" />
    </section>
  );
}

function VscodeCard(): React.JSX.Element {
  const q = useQuery({ queryKey: ["admin", "integrations"], queryFn: getIntegrations, retry: false });
  const v = q.data?.vscode;
  const test = useMutation({ mutationFn: testVscode });
  const links = Object.entries(v?.signin_links ?? {});
  return (
    <section className={styles.card} data-testid="integration-vscode">
      <div className={styles.cardHead}><h2 className={styles.cardTitle}>VS Code</h2>
        <button type="button" className={ui.button} disabled={test.isPending} onClick={() => test.mutate()} data-testid="vscode-test">Test</button></div>
      <About testid="about-vscode"
        does="Work the board from VS Code: tickets, chat with seats and the diff of each seat's changes, beside your code."
        needs="VS Code on the teammate's computer, the EDP Code extension, and that teammate's sign-in link below."
        where={v ? <><a href="https://code.visualstudio.com/download" target="_blank" rel="noreferrer">VS Code</a> · the extension from the <a href={v.vsix_url} target="_blank" rel="noreferrer">latest release (.vsix)</a></> : "…"}
        changes="The teammate opens their link once and the extension talks to this board." />
      <StatusLine state={stateOf(Boolean(v), test, v ? `the board answers at ${test.data?.value.board_url ?? v.board_url}` : undefined)} testid="vscode-status" />
      {v ? (
        <>
          <Secret label="Board URL" value={v.board_url} testid="vscode-board-url" />
          {links.length ? links.map(([h, link]) => <Secret key={h} label={`Sign-in: ${h}`} value={link} testid={`vscode-signin-${h}`} />)
            : <p className={styles.fieldNote} data-testid="vscode-no-links">No sign-in links yet: invite a teammate in Admin → Teammates first.</p>}
        </>
      ) : null}
      <AdminError error={q.error} testid="vscode-error" />
      <AdminError error={test.error} testid="vscode-test-error" />
    </section>
  );
}

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
  const configured = Boolean(slack && (slack.webhook_set || slack.bot_token_set));
  const testWhy = slack && !configured && !who ? "Save a bot token or a webhook first." : null;
  return (
    <section className={styles.card} data-testid="integration-slack">
      <div className={styles.cardHead}><h2 className={styles.cardTitle}>Slack</h2></div>
      <About testid="about-slack"
        does="Pings people in Slack when the board needs them (a question, a sign-off, a blocked seat), with a link back."
        needs="A Slack workspace where you can add an app: an incoming webhook (one channel), a bot token (direct messages), or both."
        where={<><a href="https://api.slack.com/messaging/webhooks" target="_blank" rel="noreferrer">Incoming webhooks</a> · <a href="https://api.slack.com/apps" target="_blank" rel="noreferrer">create a Slack app (bot token xoxb-…)</a></>}
        changes="The bridge posts pings within a minute. Each person can also set their own Slack in Settings → Slack." />
      <StatusLine state={stateOf(configured, test, test.data ? `sent to ${test.data.value.to}` : undefined)} testid="slack-status" />
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
          <button type="button" className={ui.button} disabled={test.isPending || Boolean(testWhy)} aria-describedby={testWhy ? "slack-test-why" : undefined}
            onClick={() => test.mutate()} data-testid="slack-test">{test.isPending ? "Sending…" : "Test"}</button>
          <Why id="slack-test-why" text={testWhy} />
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
      <p className={styles.fieldDoc}>Backed by {slack?.path ?? "slack_map.json"}.</p>
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
  const testWhy = plane && !plane.configured ? "Fill in the Plane address, API key, workspace and project, then Save Plane." : null;
  const failed = test.isSuccess && !test.data.value.ok ? test.data.value.message : null;
  return (
    <section className={styles.card} data-testid="integration-plane">
      <div className={styles.cardHead}><h2 className={styles.cardTitle}>Plane</h2></div>
      <About testid="about-plane"
        does="Mirrors the board's tickets into a Plane project, so people who plan in Plane see the same work."
        needs="A Plane workspace (cloud or self-hosted), a project in it, and an API key."
        where={<><a href="https://plane.so" target="_blank" rel="noreferrer">plane.so</a> · API key: Plane → Profile settings → API tokens</>}
        changes="New and changed tickets appear in the Plane project; the board restarts to turn the mirror on." />
      <StatusLine state={stateOf(plane?.configured, test, test.data?.value.message, failed)} testid="plane-status" />
      {(plane?.settings ?? []).map((s) => (
        <SettingField key={s.key} s={s} value={draft[s.key] ?? formValue(s)} onChange={(v) => setDraft((d) => ({ ...d, [s.key]: v }))} />
      ))}
      <div className={styles.row}>
        <button type="button" className={`${ui.button} ${ui.buttonPrimary}`} disabled={!Object.keys(draft).length || save.isPending} onClick={() => save.mutate()} data-testid="plane-save">Save Plane</button>
        <button type="button" className={ui.button} disabled={test.isPending || Boolean(testWhy)} aria-describedby={testWhy ? "plane-test-why" : undefined}
          onClick={() => test.mutate()} data-testid="plane-test">Test</button>
        <Why id="plane-test-why" text={testWhy} />
      </div>
      <AdminError error={save.error} testid="plane-save-error" />
      <AdminError error={test.error} testid="plane-test-error" />
      <Done text={test.isSuccess ? test.data.value.message : save.isSuccess ? save.data.hint : null} testid="plane-done" />
    </section>
  );
}

function CodeServerCard(): React.JSX.Element {
  const q = useQuery({ queryKey: ["admin", "integrations"], queryFn: getIntegrations, retry: false });
  const c = q.data?.code_server;
  const test = useMutation({ mutationFn: testCodeServer });
  const testWhy = c && !c.running ? `Start it first on this computer: ${c.start_command ?? "its start script"}.` : null;
  return (
    <section className={styles.card} data-testid="integration-code-server">
      <div className={styles.cardHead}><h2 className={styles.cardTitle}>code-server</h2></div>
      <About testid="about-code-server"
        does="Puts a full VS Code in the browser under the Code tab, on the board's shared working tree."
        needs="code-server installed on this computer (it stays on 127.0.0.1; the board embeds it)."
        where={<a href="https://coder.com/docs/code-server/install" target="_blank" rel="noreferrer">code-server install guide</a>}
        changes="The Code tab opens the editor instead of explaining how to start it." />
      <StatusLine state={stateOf(c?.running, test, c ? `port ${c.port}` : undefined)} testid="code-server-status" />
      {c ? <p className={styles.fieldDoc}>Port {c.port}, loopback only (never exposed on the tailnet; the Code tab embeds it through the board).</p> : null}
      <div className={styles.row}>
        <button type="button" className={ui.button} disabled={test.isPending || Boolean(testWhy)} aria-describedby={testWhy ? "code-server-test-why" : undefined}
          onClick={() => test.mutate()} data-testid="code-server-test">Test</button>
        <Why id="code-server-test-why" text={testWhy} />
      </div>
      <AdminError error={test.error} testid="code-server-test-error" />
    </section>
  );
}

export function IntegrationsTab({ onRestartRequired }: { onRestartRequired: (services: string[]) => void }): React.JSX.Element {
  // reading order (README.md): what seats need first, then the everyday tools, then optional mirrors
  return (
    <div className={styles.panel} data-testid="admin-integrations">
      <HarnessesCard />
      <VscodeCard />
      <SlackCard onRestartRequired={onRestartRequired} />
      <PlaneCard onRestartRequired={onRestartRequired} />
      <CodeServerCard />
    </div>
  );
}
