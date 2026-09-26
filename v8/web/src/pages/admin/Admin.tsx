import { useState } from "react";
import { useSearchParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { PageHeader } from "../../components/PageHeader";
import { Tabs } from "../../components/Tabs";
import { useAttention } from "../../api/attention";
import ui from "../../components/ui.module.css";
import styles from "./Admin.module.css";
import { AdminError, RestartStatus, useServiceAction } from "./shared";
import { ServicesTab } from "./Services";
import { SettingsTab } from "./SettingsTab";
import { TeammatesTab } from "./Teammates";
import { RemoteTab } from "./Remote";
import { IntegrationsTab } from "./Integrations";
import { SeatsModelsTab } from "./SeatsModels";

// Admin (S6 s-e6b4fa59d5; design-e963c656f5 §4.8): operate the install from the UI — Services, Settings,
// Teammates, Remote access, Integrations, Seats & models. Visible only to admins (the S5 `admin` flag on
// /v1/whoami); every call is an admin-token /v1/admin/* route, and every refusal is shown where it happened.

// Reading order (t-20f0718990, owner m-3136ceca05 "humans always read abcd"): the order a person works
// through the install, first run and essentials first, advanced last. README.md in this folder holds the
// rule and each tab's section order; a new tab takes its place by that rule, never at the end by default.
export const ADMIN_TABS = [
  { key: "services", label: "Services" },
  { key: "models", label: "Seats & models" },
  { key: "teammates", label: "Teammates" },
  { key: "remote", label: "Remote access" },
  { key: "integrations", label: "Integrations" },
  { key: "settings", label: "Settings" },
];

/** The one line at the top of Admin: what it is for, and where personal preferences live instead. */
export const ADMIN_SCOPE = "For the whole install, admins only: services, models, people, access, integrations and instance settings. Your own preferences are in Settings.";

interface WhoAmIAdmin { participant: { id: string; handle: string; role: string; type?: string; admin?: boolean }; admin?: boolean }

/** Whether the signed-in viewer is an admin (S5 flag on /v1/whoami). */
export function useIsAdmin(): { admin: boolean; loading: boolean } {
  const q = useQuery({ queryKey: ["whoami"], queryFn: () => api<WhoAmIAdmin>("/v1/whoami"), retry: false });
  return { admin: Boolean(q.data?.admin ?? q.data?.participant.admin), loading: q.isLoading };
}

/** "Settings changed: restart X to apply", with the restart itself one click away (design §4.8). */
function RestartBanner({ services, onClear }: { services: string[]; onClear: (svc: string) => void }): React.JSX.Element | null {
  const act = useServiceAction();
  if (!services.length && !act.phase) return null;
  return (
    <div className={ui.banner} role="status" data-testid="restart-banner">
      {services.length ? (
        <div className={styles.row}>
          <span>Settings changed: restart {services.join(", ")} to apply.</span>
          {services.map((svc) => (
            <button key={svc} type="button" className={`${ui.button} ${styles.small}`} disabled={act.pending}
              onClick={() => act.run({ svc, verb: "restart" }, { onSuccess: () => onClear(svc) })} data-testid={`restart-banner-${svc}`}>
              Restart {svc}
            </button>
          ))}
        </div>
      ) : null}
      <AdminError error={act.error} testid="restart-banner-error" />
      <RestartStatus phase={act.phase} />
    </div>
  );
}

export function AdminPage(): React.JSX.Element {
  const [params, setParams] = useSearchParams();
  const tab = ADMIN_TABS.some((t) => t.key === params.get("tab")) ? params.get("tab")! : "services";
  const { admin, loading } = useIsAdmin();
  const waiting = useAttention().counts.admin; // S20: access requests waiting on this admin sit behind Teammates
  const tabs = ADMIN_TABS.map((t) => (t.key === "teammates" ? { ...t, attention: waiting } : t));
  const [restart, setRestart] = useState<string[]>([]);
  const needRestart = (svcs: string[]) => setRestart((cur) => [...new Set([...cur, ...svcs.filter((s) => s && s !== "none")])]);
  if (loading) return <p className={ui.empty}>Loading…</p>;
  if (!admin) {
    return (
      <div className={styles.page} data-testid="admin-forbidden">
        <PageHeader title="Admin" />
        <p className={ui.banner} role="alert">Admin is for admins of this install. Ask an admin to make you one in Admin → Teammates.</p>
      </div>
    );
  }
  return (
    <div className={styles.page} data-testid="admin-page">
      <PageHeader title="Admin" subtitle={ADMIN_SCOPE} />
      <Tabs tabs={tabs} active={tab} onChange={(key) => setParams((old) => { const p = new URLSearchParams(old); p.set("tab", key); return p; }, { replace: true })} />
      <RestartBanner services={restart} onClear={(svc) => setRestart((cur) => cur.filter((s) => s !== svc))} />
      {tab === "services" ? <ServicesTab /> : null}
      {tab === "models" ? <SeatsModelsTab onRestartRequired={needRestart} /> : null}
      {tab === "teammates" ? <TeammatesTab /> : null}
      {tab === "remote" ? <RemoteTab onRestartRequired={needRestart} /> : null}
      {tab === "integrations" ? <IntegrationsTab onRestartRequired={needRestart} /> : null}
      {tab === "settings" ? <SettingsTab onRestartRequired={needRestart} /> : null}
    </div>
  );
}
