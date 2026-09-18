import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getSettings, putSettings } from "../api/endpoints";
import type { UserSettings } from "../api/types";
import { BoardApiError } from "../api/client";
import { PageHeader } from "../components/PageHeader";
import { Tabs } from "../components/Tabs";
import { ThemePicker } from "../theme/ThemePicker";
import { AvatarPicker } from "../components/AvatarPicker";
import { copyProps } from "../copy/pages";
import ui from "../components/ui.module.css";
import styles from "./Settings.module.css";

// Settings (s-7f663c6322, owner m-9f6d7c82f3): a dedicated page launched from the account menu,
// with Profile / Notifications / Slack tabs persisted at GET/PUT /v1/me/settings. Slack is where a
// third-party human receives the board's pings: the bridge (slack_bridge.py) merges these settings
// over slack_map.json within a minute of a save. Sign-in with Slack / Google is documented here as
// NOT available: identity is still the ?as= handle + token, and OAuth needs owner-provisioned apps.

const TABS = [
  { key: "profile", label: "Profile" },
  { key: "notifications", label: "Notifications" },
  { key: "slack", label: "Slack" },
];

const EMPTY: UserSettings = {
  profile: { display_name: "", timezone: "" },
  notifications: { browser: false, quiet: null },
  slack: { enabled: false, slack_id: "", webhook_url: "", webhook_set: false, quiet: null },
};

function QuietHours({ value, onChange, id }: { value: [number, number] | null; onChange: (q: [number, number] | null) => void; id: string }): React.JSX.Element {
  const on = value !== null;
  return (
    <fieldset className={styles.fieldset}>
      <legend className={styles.legend}>Quiet hours</legend>
      <label className={styles.check}>
        <input type="checkbox" checked={on} onChange={(e) => onChange(e.target.checked ? [22, 7] : null)} data-testid={`${id}-quiet`} />
        Hold pings during quiet hours (delivered when they end)
      </label>
      {on ? (
        <div className={styles.row}>
          <label>From <input className={ui.input} type="number" min={0} max={23} value={value![0]} aria-label="Quiet from (hour)"
            onChange={(e) => onChange([Number(e.target.value), value![1]])} /></label>
          <label>to <input className={ui.input} type="number" min={0} max={23} value={value![1]} aria-label="Quiet to (hour)"
            onChange={(e) => onChange([value![0], Number(e.target.value)])} /></label>
          <span className={ui.empty}>local hours, 0–23; 22 → 7 wraps midnight</span>
        </div>
      ) : null}
    </fieldset>
  );
}

export function SettingsPage(): React.JSX.Element {
  const [params, setParams] = useSearchParams();
  const tab = TABS.some((t) => t.key === params.get("tab")) ? params.get("tab")! : "profile";
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["me", "settings"], queryFn: getSettings, retry: false });
  const [draft, setDraft] = useState<UserSettings>(EMPTY);
  const [dirty, setDirty] = useState(false);
  useEffect(() => { if (q.data && !dirty) setDraft({ ...EMPTY, ...q.data, slack: { ...EMPTY.slack, ...q.data.slack } }); }, [q.data, dirty]);
  const save = useMutation({
    mutationFn: () => putSettings(draft),
    onSuccess: ({ value }) => { setDirty(false); qc.setQueryData(["me", "settings"], value); setDraft({ ...EMPTY, ...value, slack: { ...EMPTY.slack, ...value.slack } }); },
  });
  const err = (q.error ?? save.error) as BoardApiError | Error | null;
  const forbidden = q.error instanceof BoardApiError && q.error.status === 403;
  const missing = q.error instanceof BoardApiError && q.error.status === 404;
  function patch(next: Partial<UserSettings>) { setDirty(true); setDraft((d) => ({ ...d, ...next })); }

  return (
    <div className={styles.page}>
      <PageHeader title="Settings" subtitle="Who you are on this board, and where its pings reach you." />
      <Tabs tabs={TABS} active={tab} onChange={(key) => setParams((old) => { const p = new URLSearchParams(old); p.set("tab", key); return p; }, { replace: true })} />
      {forbidden ? <p className={ui.banner} role="alert" data-testid="settings-forbidden">Settings belong to people. This identity is an agent seat, which has no Slack or profile to set.</p> : null}
      {missing ? <p className={ui.banner} role="alert" data-testid="settings-missing">This board predates the settings route; theme and avatar below still save. Restart the board on the current build to enable the rest.</p> : null}
      {err && !forbidden && !missing ? <p className={ui.banner} role="alert">{("hint" in err && err.hint) || err.message}</p> : null}

      <form className={styles.form} onSubmit={(e) => { e.preventDefault(); if (!forbidden && !missing) save.mutate(); }} data-testid="settings-form" aria-label={`${tab} settings`}>
        {tab === "profile" ? (
          <section className={styles.section} data-testid="settings-profile">
            <label className={styles.field}>
              <span>Display name</span>
              <input className={ui.input} value={draft.profile.display_name} maxLength={80} data-testid="settings-display-name"
                onChange={(e) => patch({ profile: { ...draft.profile, display_name: e.target.value } })} placeholder="How the board should address you" />
            </label>
            <label className={styles.field}>
              <span>Time zone</span>
              <input className={ui.input} value={draft.profile.timezone} maxLength={64} data-testid="settings-timezone"
                onChange={(e) => patch({ profile: { ...draft.profile, timezone: e.target.value } })} placeholder={Intl.DateTimeFormat().resolvedOptions().timeZone} />
            </label>
            <div className={styles.section}>
              <ThemePicker />
              <AvatarPicker />
            </div>
            <details className={ui.fold} data-testid="settings-signin">
              <summary>Sign in with Slack or Google</summary>
              <p className={ui.empty}>Not available yet. Your identity on this board is the <code>?as=</code> handle plus your token; linking a Slack or Google login needs an OAuth app the owner provisions for this host, and until then this page stays honest rather than showing a button that goes nowhere.</p>
            </details>
          </section>
        ) : null}

        {tab === "notifications" ? (
          <section className={styles.section} data-testid="settings-notifications">
            <label className={styles.check}>
              <input type="checkbox" checked={draft.notifications.browser} data-testid="settings-browser"
                onChange={(e) => patch({ notifications: { ...draft.notifications, browser: e.target.checked } })} />
              I use browser notifications on this board
            </label>
            <p className={ui.empty}>Browser alerts are enabled per browser from the rail (Notifications → Enable); this switch records your preference on the board so a new browser can prompt you.</p>
            <QuietHours id="notifications" value={draft.notifications.quiet} onChange={(quiet) => patch({ notifications: { ...draft.notifications, quiet } })} />
          </section>
        ) : null}

        {tab === "slack" ? (
          <section className={styles.section} data-testid="settings-slack">
            <label className={styles.check}>
              <input type="checkbox" checked={draft.slack.enabled} data-testid="settings-slack-enabled"
                onChange={(e) => patch({ slack: { ...draft.slack, enabled: e.target.checked } })} />
              Send my board pings to Slack
            </label>
            <p className={ui.empty}>Questions, steers and requests addressed to you are posted to Slack by the bridge with a deep link back to the conversation. Give it a member id (bot delivery) or an incoming webhook (channel or DM delivery), or both.</p>
            <label className={styles.field}>
              <span>Slack member id</span>
              <input className={ui.input} value={draft.slack.slack_id} maxLength={64} data-testid="settings-slack-id" placeholder="U0123456789"
                onChange={(e) => patch({ slack: { ...draft.slack, slack_id: e.target.value } })} />
            </label>
            <label className={styles.field}>
              <span>Incoming webhook URL</span>
              <input className={ui.input} value={draft.slack.webhook_url} maxLength={400} data-testid="settings-slack-webhook" type="url"
                placeholder="https://hooks.slack.com/services/…" onChange={(e) => patch({ slack: { ...draft.slack, webhook_url: e.target.value } })} />
              <span className={ui.empty}>{draft.slack.webhook_set ? "A webhook is stored; it is shown masked. Paste a new one to replace it." : "Stored on the board host only; never shown back in full."}</span>
            </label>
            <QuietHours id="slack" value={draft.slack.quiet} onChange={(quiet) => patch({ slack: { ...draft.slack, quiet } })} />
          </section>
        ) : null}

        <div className={styles.actions}>
          <button type="submit" className={`${ui.button} ${ui.buttonPrimary}`} disabled={save.isPending || !dirty || forbidden || missing} data-testid="settings-save" {...copyProps("settings", "save")}>
            {save.isPending ? "Saving…" : "Save"}
          </button>
          {save.isSuccess && !dirty ? <span role="status" className={ui.empty} data-testid="settings-saved">{save.data?.hint || "Saved."}</span> : null}
        </div>
      </form>
    </div>
  );
}
