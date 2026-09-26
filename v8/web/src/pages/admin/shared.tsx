import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BoardApiError } from "../../api/client";
import { getHealthz, serviceAction } from "../../api/admin";
import type { SettingRow, SettingValue } from "../../api/admin";
import ui from "../../components/ui.module.css";
import styles from "./Admin.module.css";

// S6 c-e834afcefc (pain p-77ab1bf1 "Approve did nothing"): every admin action shows the board's refusal.
// One reader of the error, one element that renders it, so no mutation can fail silently.

/** The words the board gave for a refusal: its error message, else its hint, else the transport error. */
export function errorText(e: unknown): string {
  if (e instanceof BoardApiError) return e.message || e.hint || `the board answered ${e.status}`;
  if (e instanceof Error) return e.message;
  return String(e);
}

/** The board's refusal, rendered where the action was taken. Renders nothing when there is no error. */
export function AdminError({ error, testid }: { error: unknown; testid?: string }): React.JSX.Element | null {
  if (!error) return null;
  return <p className={ui.banner} role="alert" data-testid={testid ?? "admin-error"}>{errorText(error)}</p>;
}

/** A one-line success receipt (the board's hint when it gave one). */
export function Done({ text, testid }: { text: string | null | undefined; testid?: string }): React.JSX.Element | null {
  if (!text) return null;
  return <p className={ui.empty} role="status" data-testid={testid ?? "admin-done"}>{text}</p>;
}

export function CopyButton({ text, label = "Copy", testid }: { text: string; label?: string; testid?: string }): React.JSX.Element {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);
  return (
    <button type="button" className={ui.button} data-testid={testid}
      onClick={() => {
        navigator.clipboard?.writeText(text).then(() => { setCopied(true); setFailed(false); }, () => setFailed(true));
        if (!navigator.clipboard) setFailed(true);
      }}>
      {copied ? "Copied" : failed ? "Copy failed: select the text" : label}
    </button>
  );
}

/** A value shown once (a link, a token, a key) with its copy button. */
export function Secret({ label, value, testid }: { label: string; value: string; testid: string }): React.JSX.Element {
  return (
    <div className={styles.secret}>
      <span className={styles.secretLabel}>{label}</span>
      <code className={styles.secretValue} data-testid={testid}>{value}</code>
      <CopyButton text={value} testid={`${testid}-copy`} />
    </div>
  );
}

// ------------------------------------------------------------------------ restarts (board polls /healthz)

export type RestartPhase = { svc: string; state: "asking" | "restarting" | "back" | "timeout"; startedAt?: string | null };

const POLL_MS = 1000;
const POLL_LIMIT_MS = 120_000;

/** Start/stop/restart one service. A board restart is answered 202 by the board being replaced: the UI
 *  shows "restarting…" and polls /healthz until a NEW started_at appears (design §4.8). */
export function useServiceAction(onDone?: () => void) {
  const qc = useQueryClient();
  const [phase, setPhase] = useState<RestartPhase | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  const pollBoard = (before: string | null | undefined, svc: string) => {
    const deadline = Date.now() + POLL_LIMIT_MS;
    const tick = () => {
      getHealthz().then((h) => {
        if (h.ok && h.started_at && h.started_at !== before) {
          setPhase({ svc, state: "back", startedAt: h.started_at });
          void qc.invalidateQueries({ queryKey: ["admin"] });
          onDone?.();
          return;
        }
        throw new Error("not yet");
      }).catch(() => {
        if (Date.now() > deadline) setPhase({ svc, state: "timeout" });
        else timer.current = setTimeout(tick, POLL_MS);
      });
    };
    timer.current = setTimeout(tick, POLL_MS);
  };

  const m = useMutation({
    mutationFn: async ({ svc, verb, force }: { svc: string; verb: "start" | "stop" | "restart"; force?: boolean }) => {
      setPhase({ svc, state: "asking" });
      const before = svc === "board" ? (await getHealthz().catch(() => null))?.started_at ?? null : null;
      const out = await serviceAction(svc, verb, force ? { force: true } : {});
      return { svc, verb, before: out.value?.started_at ?? before, hint: out.hint };
    },
    onSuccess: ({ svc, verb, before }) => {
      if (svc === "board" && verb === "restart") {
        setPhase({ svc, state: "restarting" });
        pollBoard(before, svc);
      } else {
        setPhase(null);
        void qc.invalidateQueries({ queryKey: ["admin"] });
        onDone?.();
      }
    },
    onError: () => setPhase(null),
  });
  return { run: m.mutate, pending: m.isPending, error: m.error, hint: m.data?.hint, phase, pollBoard, setPhase };
}

export function RestartStatus({ phase }: { phase: RestartPhase | null }): React.JSX.Element | null {
  if (!phase || phase.state === "asking") return null;
  if (phase.state === "restarting") return <p className={ui.banner} role="status" data-testid="restart-status">Restarting {phase.svc}… waiting for /healthz to report a new start.</p>;
  if (phase.state === "timeout") return <p className={ui.banner} role="alert" data-testid="restart-status">{phase.svc} did not come back within two minutes. Check Services, or run <code>heronry status</code> on the host.</p>;
  return <p className={ui.empty} role="status" data-testid="restart-status">{phase.svc} is back (started {phase.startedAt}).</p>;
}

// ------------------------------------------------------------------------ one registry field

/** The form value for a setting row: what the input shows. Secrets start blank (write-only). */
export function formValue(s: SettingRow): string | boolean {
  if (s.secret) return "";
  if (s.type === "bool") return Boolean(s.value);
  if (s.value === null || s.value === undefined) return "";
  if (Array.isArray(s.value)) return s.value.join(", ");
  return String(s.value);
}

/** Form value → what PUT /v1/admin/settings takes (the registry coerces and validates it). */
export function toPut(s: SettingRow, v: string | boolean): SettingValue {
  if (s.type === "bool") return Boolean(v);
  const t = String(v).trim();
  if (s.type === "list") return t ? t.split(",").map((x) => x.trim()).filter(Boolean) : [];
  if (s.type === "int" && /^-?\d+$/.test(t)) return Number(t);
  if (s.type === "float" && t !== "" && !Number.isNaN(Number(t))) return Number(t);
  return t;
}

const SOURCE_WORD: Record<string, string> = { env: "environment", config: "config.toml", default: "default" };

/** One registry setting: its key, doc line, where the value comes from and an input by type. A value the
 *  environment sets is read-only (env wins); a secret is write-only and shown masked. */
export function SettingField({ s, value, onChange, onReset }: {
  s: SettingRow;
  value: string | boolean;
  onChange: (v: string | boolean) => void;
  onReset?: () => void;
}): React.JSX.Element {
  const id = `setting-${s.key}`;
  const ro = s.read_only;
  let input: React.JSX.Element;
  if (s.type === "bool") {
    input = <input id={id} type="checkbox" checked={Boolean(value)} disabled={ro} onChange={(e) => onChange(e.target.checked)} data-testid={`${id}-input`} />;
  } else if (s.choices.length) {
    input = (
      <select id={id} className={ui.select} value={String(value)} disabled={ro} onChange={(e) => onChange(e.target.value)} data-testid={`${id}-input`}>
        {String(value) === "" ? <option value="">(default)</option> : null}
        {s.choices.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
    );
  } else {
    input = (
      <input id={id} className={ui.input} disabled={ro} value={String(value)} data-testid={`${id}-input`}
        type={s.secret ? "password" : s.type === "int" || s.type === "float" ? "number" : "text"}
        autoComplete={s.secret ? "new-password" : "off"}
        placeholder={s.secret ? (s.set ? "set (hidden): type to replace" : "not set") : s.default === null || s.default === undefined ? "" : `default: ${Array.isArray(s.default) ? s.default.join(", ") : String(s.default)}`}
        onChange={(e) => onChange(e.target.value)} />
    );
  }
  return (
    <div className={styles.field} data-testid="setting-field" data-key={s.key} data-readonly={ro ? "true" : undefined} data-secret={s.secret ? "true" : undefined}>
      <label htmlFor={id} className={styles.fieldHead}>
        <span className={styles.fieldKey}>{s.key}</span>
        <span className={ui.idMono}>{s.env}</span>
        <span className={ui.chip}>{SOURCE_WORD[s.source] ?? s.source}</span>
        {s.secret ? <span className={ui.chip} data-testid={`${id}-masked`}>{s.set ? "secret · set ********" : "secret · not set"}</span> : null}
        {s.restart_required !== "none" ? <span className={ui.chip}>restart {s.restart_required}</span> : null}
      </label>
      <div className={styles.fieldRow}>
        {input}
        {onReset && !ro && s.source === "config" ? <button type="button" className={ui.button} onClick={onReset} data-testid={`${id}-reset`}>Reset to default</button> : null}
      </div>
      <p className={styles.fieldDoc}>{s.doc}</p>
      {ro ? <p className={styles.fieldNote} data-testid={`${id}-readonly`}>{s.read_only_reason}</p> : null}
      {s.error ? <p className={styles.fieldNote}>{s.error}</p> : null}
    </div>
  );
}
