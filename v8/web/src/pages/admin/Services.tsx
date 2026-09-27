import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { applyUpdate, getCapacity, getServices, getUpdates, putCapacity } from "../../api/admin";
import type { CapacityPut, CapacityView, ServiceRow } from "../../api/admin";
import ui from "../../components/ui.module.css";
import styles from "./Admin.module.css";
import { AdminError, Done, RestartStatus, useServiceAction } from "./shared";

// Admin → Services (design §4.8, §4.10): health per service with Start/Stop/Restart through the supervisor;
// the app-update banner; and Capacity (§4.14(d)).

function healthWord(r: ServiceRow): string {
  return r.health ?? r.state;
}

/** Start when down, Stop/Restart when up. Nothing to start without a code-server installed (S21), and a port
 *  another program holds is never ours to stop. */
function canRun(r: ServiceRow, verb: "start" | "stop" | "restart"): boolean {
  if (r.state === "not_installed" || r.state === "foreign") return false;
  if (verb === "start") return r.state !== "up";
  if (verb === "stop") return r.state === "up";
  return true;
}

function UpdatesBanner(): React.JSX.Element | null {
  const q = useQuery({ queryKey: ["admin", "updates"], queryFn: getUpdates, retry: false, staleTime: 60_000 });
  const act = useServiceAction();
  const apply = useMutation({
    mutationFn: () => applyUpdate(false),
    onSuccess: () => {
      act.setPhase({ svc: "the app", state: "restarting" });
      act.pollBoard(null, "the app");
    },
  });
  const u = q.data;
  if (!u) return q.error ? <AdminError error={q.error} testid="updates-error" /> : null;
  const last = u.last?.result?.state;
  return (
    <>
      {u.available ? (
        <div className={ui.banner} role="status" data-testid="update-banner">
          <div className={styles.row}>
            <span>Version <strong>{u.latest}</strong> is available (this install runs {u.current}).</span>
            {u.url ? <a href={u.url} target="_blank" rel="noreferrer">Release notes</a> : null}
            <button type="button" className={`${ui.button} ${ui.buttonPrimary}`} data-testid="update-apply"
              disabled={apply.isPending || Boolean(u.apply_refusal)} onClick={() => apply.mutate()}>
              {apply.isPending ? "Applying…" : "Apply"}
            </button>
          </div>
          {u.apply_refusal ? <p className={styles.fieldNote} data-testid="update-refusal">Apply is not possible here: {u.apply_refusal}</p> : null}
          <p className={styles.fieldDoc}>Apply backs up the database, stops every service, upgrades and starts again; seats are drained first.</p>
        </div>
      ) : (
        <p className={ui.empty} data-testid="update-current">Version {u.current}{u.checked ? " is the latest release." : " (the releases check did not answer: offline, opted out or a dev checkout)."}{last ? ` Last update: ${last}.` : ""}</p>
      )}
      <AdminError error={apply.error} testid="update-apply-error" />
      <RestartStatus phase={act.phase} />
    </>
  );
}

function ServicesTable(): React.JSX.Element {
  const q = useQuery({ queryKey: ["admin", "services"], queryFn: getServices, retry: false, refetchInterval: 10_000 });
  const act = useServiceAction();
  const [force, setForce] = useState(false);
  const rows = q.data?.services ?? [];
  const sup = q.data?.supervisor;
  return (
    <section className={styles.card} data-testid="services">
      <div className={styles.cardHead}>
        <h2 className={styles.cardTitle}>Services</h2>
        <label className={styles.row}>
          <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} data-testid="services-force" />
          Take live seats offline (pool stop/restart)
        </label>
      </div>
      {sup && !sup.control ? (
        <p className={ui.banner} role="alert" data-testid="supervisor-down">
          The supervisor is {sup.running ? "running without a control port" : "not running"}, so nothing here can start or stop a service. Run <code>heronry start</code> on the host.{sup.error ? ` (${sup.error})` : ""}
        </p>
      ) : null}
      <AdminError error={q.error} testid="services-error" />
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead><tr><th>Service</th><th>Health</th><th>Pid</th><th>Port</th><th>Uptime</th><th>Revision</th><th>Actions</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.service} data-testid={`service-${r.service}`}>
                <td><strong>{r.service}</strong>{r.note ? <div className={styles.usage}>{r.note}</div> : null}</td>
                <td><span className={`${ui.chip} ${r.state === "up" && healthWord(r) === "up" ? ui.done : ui.blocked}`}><span className={ui.chipDot} />{healthWord(r)}</span></td>
                <td className={ui.idMono}>{r.pid ?? "—"}</td>
                <td className={ui.idMono}>{r.port ?? "—"}</td>
                <td>{r.uptime ?? "—"}</td>
                <td className={ui.idMono}>{r.rev ? String(r.rev).slice(0, 8) : "—"}</td>
                <td>
                  {r.managed === false ? <span className={styles.usage}>not managed here</span> : (
                    <div className={styles.actions}>
                      {(["start", "stop", "restart"] as const).map((verb) => (
                        <button key={verb} type="button" className={`${ui.button} ${styles.small}`} data-testid={`service-${r.service}-${verb}`}
                          disabled={act.pending || !canRun(r, verb)}
                          onClick={() => act.run({ svc: r.service, verb, force })}>
                          {verb[0].toUpperCase() + verb.slice(1)}
                        </button>
                      ))}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <AdminError error={act.error} testid="service-action-error" />
      <Done text={act.phase ? null : act.hint} testid="service-action-done" />
      <RestartStatus phase={act.phase} />
    </section>
  );
}

// ------------------------------------------------------------------------------------------ capacity

type Draft = Record<string, string>;

function draftOf(v: CapacityView): Draft {
  const d: Draft = { total: String(v.total.cap ?? ""), live: String(v.live.cap ?? "") };
  for (const c of v.classes) if (!c.exempt) d[`class:${c.class}`] = String(c.cap ?? "");
  for (const r of v.roles) d[`role:${r.role}`] = r.cap === null ? "" : String(r.cap);
  return d;
}

/** Admin → Services → Capacity (§4.14(d), c-002a8ba1b5): the pool's caps and live usage; writes apply now
 *  through the pool's limits endpoint and persist across a pool restart. */
export function CapacityPanel(): React.JSX.Element {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["admin", "capacity"], queryFn: getCapacity, retry: false });
  const [draft, setDraft] = useState<Draft>({});
  const [dirty, setDirty] = useState(false);
  useEffect(() => { if (q.data && !dirty) setDraft(draftOf(q.data)); }, [q.data, dirty]);
  const save = useMutation({
    mutationFn: (body: CapacityPut) => putCapacity(body),
    onSuccess: ({ value }) => { setDirty(false); qc.setQueryData(["admin", "capacity"], value); setDraft(draftOf(value)); },
  });
  const v = q.data;
  const set = (k: string, val: string) => { setDirty(true); setDraft((d) => ({ ...d, [k]: val })); };
  const num = (k: string) => Math.max(1, Math.floor(Number(draft[k])));
  const changed = (k: string, cap: number | null) => draft[k] !== undefined && draft[k] !== String(cap ?? "");
  const tooLow = Object.values(draft).some((x) => x !== "" && Number(x) < 1);

  function submit() {
    if (!v) return;
    const body: CapacityPut = {};
    if (changed("total", v.total.cap)) body.max_total_shells = num("total");
    if (changed("live", v.live.cap)) body.max_live_shells = num("live");
    for (const c of v.classes) {
      if (!c.exempt && changed(`class:${c.class}`, c.cap)) (body.classes ??= {})[c.class] = num(`class:${c.class}`);
    }
    for (const r of v.roles) {
      const k = `role:${r.role}`;
      if (changed(k, r.cap)) (body.role_caps ??= {})[r.role] = draft[k] === "" ? null : num(k);
    }
    save.mutate(body);
  }

  const cell = (k: string, label: string, inUse: number, cap: number | null, extra?: React.ReactNode, allowBlank = false) => (
    <label className={styles.capCell} key={k} data-testid={`cap-${k}`}>
      <span>{label}</span>
      <input className={ui.input} type="number" min={1} step={1} value={draft[k] ?? ""} placeholder={allowBlank ? "no cap" : ""}
        onChange={(e) => set(k, e.target.value)} data-testid={`cap-${k}-input`} />
      <span className={styles.usage} data-testid={`cap-${k}-usage`}>{inUse} / {cap ?? "no cap"} in use</span>
      {extra}
    </label>
  );

  return (
    <section className={styles.card} data-testid="capacity">
      <div className={styles.cardHead}>
        <h2 className={styles.cardTitle}>Capacity</h2>
        <button type="button" className={`${ui.button} ${ui.buttonPrimary}`} data-testid="capacity-save"
          disabled={!dirty || save.isPending || !v} onClick={submit}>{save.isPending ? "Saving…" : "Save caps"}</button>
      </div>
      <p className={styles.fieldDoc}>How many seat shells the pool runs at once. Changes apply at once, with no restart, and survive a pool restart. Every cap is at least 1: a cap of 0 would not pause anything, it would deadlock spawning. Pausing is its own control.</p>
      {tooLow ? <p className={ui.banner} role="alert" data-testid="capacity-clamp">A cap below 1 is saved as 1. To stop new seats, pause instead.</p> : null}
      <AdminError error={q.error} testid="capacity-error" />
      {v ? (
        <>
          <div className={styles.capGrid}>
            {cell("total", "Total shells (throughput)", v.total.in_use, v.total.cap)}
            {cell("live", "Live shells ceiling (incl. parked)", v.live.in_use, v.live.cap)}
            {v.classes.map((c) => c.exempt ? (
              <div className={styles.capCell} key={c.class} data-testid={`cap-class:${c.class}`}>
                <span>{c.class}</span>
                <span className={styles.usage} data-testid={`cap-class:${c.class}-usage`}>{c.in_use} in use · exempt from class caps; counts toward the total only</span>
              </div>
            ) : cell(`class:${c.class}`, `${c.class} class`, c.in_use, c.cap))}
          </div>
          <h3 className={ui.sectionLabel}>Per role (every workflow a running epic pins)</h3>
          <div className={styles.capGrid}>
            {v.roles.map((r) => cell(`role:${r.role}`, `${r.role} · ${r.capacity_class ?? "no class"}`, r.in_use, r.cap,
              <span className={styles.usage}>{r.overridden ? "set here" : r.declared_max ? `workflow cap ${r.declared_max}` : "no own cap"} · {r.workflows.join(", ")}</span>, true))}
            {v.roles.length === 0 ? <p className={ui.empty}>No running epic pins a workflow yet.</p> : null}
          </div>
        </>
      ) : null}
      <AdminError error={save.error} testid="capacity-save-error" />
      <Done text={save.isSuccess && !dirty ? save.data?.hint : null} testid="capacity-saved" />
    </section>
  );
}

export function ServicesTab(): React.JSX.Element {
  return (
    <div className={styles.panel} data-testid="admin-services">
      <UpdatesBanner />
      <ServicesTable />
      <CapacityPanel />
    </div>
  );
}
