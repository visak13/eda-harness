import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getUsage, type ProviderUsage, type UsageWindow } from "../api/usage";
import { BoardApiError } from "../api/client";
import { AnchoredPanel } from "./AnchoredPanel";
import { IdentityPanel } from "./IdentityPanel";
import { Icon } from "./Icon";
import styles from "./UsageWidget.module.css";

// The Usage popover per revision3-clean-usage.png: "Usage" heading + close, one freshness line,
// then per provider a bold name and one compact meter per window ("5-hour window … 42% used",
// a thin bar, "Resets …"), an unavailable window as a quiet left-ruled note, and one full-width
// "Refresh usage". Nothing scrolls at 1440×900; the verbose bucket cards are gone (owner defect:
// "giant scrolling pop-up that shows no usage").

const statusLabel = { available: "Available", stale: "May be stale", unavailable: "Unavailable",
  auth_required: "Authentication required", error: "Source error" };

export function usageTime(value: string | number | null): string {
  if (value === null) return "Unknown";
  const date = new Date(typeof value === "number" ? value * 1000 : value);
  if (!Number.isFinite(date.getTime())) return "Unknown";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "long" }).format(date);
}

/** "Resets today, 18:30 IST" / "Resets Monday, 09:00 IST" — the render's short form, with the zone. */
export function resetsLine(resetsAt: number | null, now: number): string {
  if (resetsAt === null) return "Reset time unknown";
  const date = new Date(resetsAt * 1000);
  if (!Number.isFinite(date.getTime())) return "Reset time unknown";
  const today = new Date(now);
  const sameDay = date.toDateString() === today.toDateString();
  const time = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", timeZoneName: "short" }).format(date);
  const day = sameDay ? "today" : new Intl.DateTimeFormat(undefined, { weekday: "long", month: "short", day: "numeric" }).format(date);
  return `Resets ${day}, ${time}`;
}

function windowLabel(w: UsageWindow): string {
  if (w.key === "fable") return "Fable";
  if (w.window_minutes === 300) return "5-hour window";
  if (w.window_minutes === 10080) return "Weekly";
  return w.window_minutes ? `${w.window_minutes}-minute window` : "Window";
}

function Meter({ window: w, now }: { window: UsageWindow; now: number }): React.JSX.Element {
  const label = windowLabel(w);
  const expired = w.resets_at !== null && w.resets_at * 1000 <= now;
  const used = !expired && (w.status === "available" || w.status === "stale") ? w.used_percent : null;
  if (used === null) {
    return <li className={styles.note} data-testid="usage-window" data-window={w.key}>
      <span><span>{label}</span> · {expired ? "reset elapsed" : statusLabel[w.status].toLowerCase()}</span>
      <span>{expired ? "Reset elapsed; awaiting source update" : w.reason || "No supported reading from this source"}</span>
    </li>;
  }
  return <li className={styles.meter} data-testid="usage-window" data-window={w.key}>
    <div className={styles.meterTop}><span>{label}</span><strong>{used}% used</strong></div>
    <div className={styles.bar} role="meter" aria-label={`${label} used`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={used}>
      <b style={{ width: `${used}%` }} />
    </div>
    <small>{resetsLine(w.resets_at, now)}{w.status === "stale" ? " · may be stale" : ""}</small>
  </li>;
}

function Provider({ provider, now }: { provider: ProviderUsage; now: number }): React.JSX.Element {
  const name = provider.provider === "claude" ? "Claude" : "Codex";
  return <section className={styles.provider} aria-label={name}>
    <h3>{name}</h3>
    <ul>{provider.windows.map((w) => <Meter key={w.key} window={w} now={now} />)}</ul>
  </section>;
}

function freshness(providers: ProviderUsage[] | undefined, now: number): string {
  const times = (providers ?? []).map((p) => (p.received_at ? new Date(p.received_at).getTime() : NaN)).filter(Number.isFinite);
  if (!times.length) return "No reading received yet";
  const age = Math.max(0, Math.round((now - Math.max(...times)) / 60000));
  return age < 1 ? "Updated just now" : `Updated ${age} min ago`;
}

/** Isolated query and nonmodal portal: no route, composer mutation or global refresh. */
export function UsageWidget({ actor, className }: { actor: string; className?: string }): React.JSX.Element {
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
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  return <>
    <button ref={anchor} type="button" className={`${styles.trigger} ${className ?? ""}`} aria-haspopup="dialog"
      aria-expanded={open} onClick={() => setOpen((value) => !value)} data-testid="usage-open">
      <Icon name="usage" /><span>Usage</span>
    </button>
    {open ? <AnchoredPanel anchor={anchor} label="Subscription usage" heading="Usage" onClose={close} width={304} maxHeight={640}>
      <p className={styles.fresh} data-testid="usage-freshness">
        {usage.data ? freshness(usage.data.providers, now) : usage.isPending ? "Loading usage…" : "No reading"} · subscription limits, not API spending · times are local ({zone})
      </p>
      {authError ? <IdentityPanel hint="Sign in again to view your linked usage." /> : <>
        {usage.isError ? <p role="alert" className={styles.alert}>Usage could not be refreshed. Previously shown readings are hidden.</p> : null}
        {!usage.isError ? usage.data?.providers.map((provider, i) => <div key={provider.provider}>
          {i > 0 ? <div className={styles.divider} /> : null}
          <Provider provider={provider} now={now} />
        </div>) : null}
        <button type="button" className={styles.refresh} disabled={usage.isFetching || remaining > 0}
          onClick={() => { setNow(Date.now()); void usage.refetch(); }}
          title="Reads cached, authorized receipts. It does not run a prompt or refresh Claude at the provider.">
          {usage.isFetching ? "Refreshing…" : remaining > 0 ? `Refresh in ${remaining}s` : "Refresh usage"}
        </button>
      </>}
    </AnchoredPanel> : null}
  </>;
}
