import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getUsage, type UsageWindow } from "../api/usage";
import { BoardApiError } from "../api/client";
import { AnchoredPanel } from "./AnchoredPanel";
import { IdentityPanel } from "./IdentityPanel";
import { Icon } from "./Icon";
import styles from "./UsageWidget.module.css";

const statusLabel = { available: "Available", stale: "May be stale", unavailable: "Unavailable",
  auth_required: "Authentication required", error: "Source error" };

export function usageTime(value: string | number | null): string {
  if (value === null) return "Unknown";
  const date = new Date(typeof value === "number" ? value * 1000 : value);
  if (!Number.isFinite(date.getTime())) return "Unknown";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "long" }).format(date);
}

function Bucket({ window: w, now }: { window: UsageWindow; now: number }): React.JSX.Element {
  const label = w.key === "fable" ? "Fable" : w.window_minutes === 300 ? "5 hours"
    : w.window_minutes === 10080 ? "Weekly" : `${w.window_minutes ?? "Unknown"} minutes`;
  const expired = w.resets_at !== null && w.resets_at * 1000 <= now;
  const used = !expired && (w.status === "available" || w.status === "stale") ? w.used_percent : null;
  return <li className={styles.bucket}>
    <div className={styles.row}><strong>{label}</strong><span>{used !== null ? `${used}% used` : "—"}</span></div>
    {used !== null ? <div className={styles.meter} role="meter" aria-label={`${label} used`}
      aria-valuemin={0} aria-valuemax={100} aria-valuenow={used}>
      <span style={{ width: `${used}%` }} />
    </div> : null}
    <div>{expired ? "Reset elapsed; awaiting source update" : statusLabel[w.status]}</div>
    {!expired ? <div className={styles.meta}>{w.reason}</div> : null}
    <div className={styles.meta}>Reset: {usageTime(w.resets_at)}</div>
    {w.observed_at !== null ? <div className={styles.meta}>Observed: {usageTime(w.observed_at)}</div> : null}
  </li>;
}

/** Isolated query and nonmodal portal: no route, composer mutation or global refresh. */
export function UsageWidget({ actor }: { actor: string }): React.JSX.Element {
  const [open, setOpen] = useState(false);
  const [now, setNow] = useState(Date.now);
  const anchor = useRef<HTMLButtonElement>(null);
  const close = useCallback(() => setOpen(false), []);
  const usage = useQuery({ queryKey: ["usage", actor], queryFn: getUsage, enabled: open,
    retry: false, staleTime: 30_000, gcTime: 0, refetchOnWindowFocus: false,
    refetchInterval: open ? (query) => Math.max(60_000,
      ...(query.state.data?.providers.map((p) => p.retry_after_seconds * 2000) ?? [])) : false });
  useEffect(() => {
    if (!open) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [open]);
  const delay = Math.max(30, ...(usage.data?.providers.map((p) => p.retry_after_seconds) ?? []));
  const remaining = Math.max(0, Math.ceil((Math.max(usage.dataUpdatedAt, usage.errorUpdatedAt) + delay * 1000 - now) / 1000));
  const authError = usage.error instanceof BoardApiError && usage.error.status === 401;
  return <>
    <button ref={anchor} type="button" className={styles.trigger} aria-haspopup="dialog"
      aria-expanded={open} onClick={() => setOpen((value) => !value)}>
      <Icon name="usage" /><span>Usage</span>
    </button>
    {open ? <AnchoredPanel anchor={anchor} label="Subscription usage" onClose={close} width={304} maxHeight={560}>
      <p className={styles.intro}>Subscription limits, not API spending. Times are local ({Intl.DateTimeFormat().resolvedOptions().timeZone}).</p>
      {authError ? <IdentityPanel hint="Sign in again to view your linked usage." /> : <>
        {usage.isPending ? <p role="status">Loading usage…</p> : null}
        {usage.isError ? <p role="alert">Usage could not be refreshed. Previously shown readings are hidden.</p> : null}
        {!usage.isError ? usage.data?.providers.map((provider) => <section key={provider.provider} className={styles.provider}
          aria-label={provider.provider === "claude" ? "Claude" : "Codex"}>
          <h3>{provider.provider === "claude" ? "Claude" : "Codex"}</h3>
          <p className={styles.meta}>{provider.account_binding ?? "No account linked"} · {provider.source}</p>
          <details className={styles.meta}><summary>Source timing · observation unknown</summary>
            <p>Received: {usageTime(provider.received_at)} (not observation time)</p>
          </details>
          <ul>{provider.windows.map((w) => <Bucket key={w.key} window={w} now={now} />)}</ul>
        </section>) : null}
        <button type="button" className={styles.refresh} disabled={usage.isFetching || remaining > 0}
          onClick={() => { setNow(Date.now()); void usage.refetch(); }}>
          {usage.isFetching ? "Refreshing…" : remaining > 0 ? `Refresh in ${remaining}s` : "Refresh"}
        </button>
        <p className={styles.meta}>Refresh reads cached, authorized receipts. It does not run a prompt or refresh Claude at the provider.</p>
      </>}
    </AnchoredPanel> : null}
  </>;
}
