import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { diffWorkflow, getUpstream, mergeUpstream } from "../../api/workflows";
import type { Change, DryRun, MergeResult, Problem, WorkflowDef, WorkflowRow } from "../../api/workflows";
import ui from "../../components/ui.module.css";
import { AdminError } from "../admin/shared";
import styles from "./Design.module.css";
import { PANELS, panelFor, short, type PanelKey } from "./model";

// S14 (§4.14(e).2-4): Validate (the board's lint + the dry run, each issue linked to the panel where it is
// fixed), Dry run (the timeline of a synthetic epic), Diff (against the version it came from) and the
// "upstream changed" banner with its three-way merge into a new draft.

export function ValidatePanel({ problems, ran, onGo }: {
  problems: Problem[] | null; ran: boolean; onGo: (panel: PanelKey, role?: string, field?: string) => void;
}): React.JSX.Element {
  const errors = (problems ?? []).filter((p) => p.severity === "error");
  const warnings = (problems ?? []).filter((p) => p.severity !== "error");
  return (
    <div className={styles.card} data-testid="design-validate">
      <h2 className={styles.cardTitle}>Validate</h2>
      {!ran || !problems ? <p className={styles.muted}>Press Validate to check this draft: the board's lint, then a dry run.</p>
        : errors.length === 0 ? <p className={styles.muted} data-testid="validate-ok">No errors: this version can be published.{warnings.length ? ` ${warnings.length} warning${warnings.length === 1 ? "" : "s"} below.` : ""}</p>
          : <p className={ui.banner} role="alert" data-testid="validate-errors">{errors.length === 1 ? "1 error blocks" : `${errors.length} errors block`} Publish.</p>}
      <ul className={styles.problems}>
        {[...errors, ...warnings].map((p, i) => {
          const go = panelFor(p);
          const label = PANELS.find((x) => x.key === go.panel)?.label ?? go.panel;
          return (
            <li key={i} className={`${styles.problem} ${p.severity === "error" ? "" : styles.problemWarn}`} data-testid={`problem-${p.code}`}>
              <span className={styles.problemCode}>{p.severity === "error" ? "Error" : "Warning"} · {p.code}</span>
              <span>{p.message}</span>
              {p.why ? <span className={styles.help}><strong>Why:</strong> {p.why}</span> : null}
              {p.fix ? <span className={styles.help}><strong>Fix:</strong> {p.fix}</span> : null}
              <span>
                <button type="button" className={`${ui.button} ${styles.small}`} data-testid={`problem-go-${p.code}`}
                  onClick={() => onGo(go.panel, go.role, go.field)}>
                  Go to {label}{go.role ? ` → ${go.role}` : ""}{go.field ? ` → ${go.field.replaceAll("_", " ")}` : ""}
                </button>
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

const KIND_CLASS: Record<string, string> = {
  spawn: styles.tlSpawn, gate: styles.tlGate, stall: styles.tlStall, done: styles.tlDone,
};

export function DryRunPanel({ run, pending, error, onRun }: {
  run: DryRun | null; pending: boolean; error: unknown; onRun: () => void;
}): React.JSX.Element {
  const [wakes, setWakes] = useState(false);
  const rows = (run?.timeline ?? []).filter((e) => wakes || e.kind !== "wake");
  return (
    <div className={styles.card} data-testid="design-dryrun">
      <div className={styles.spread}>
        <h2 className={styles.cardTitle}>Dry run</h2>
        <div className={styles.row}>
          <label className={styles.check}><input type="checkbox" checked={wakes} onChange={(e) => setWakes(e.target.checked)} data-testid="dryrun-wakes" />show wakes</label>
          <button type="button" className={ui.button} disabled={pending} onClick={onRun} data-testid="dryrun-run">{pending ? "Walking…" : "Run dry run"}</button>
        </div>
      </div>
      <p className={styles.muted}>A synthetic epic with one story walks through this draft on a throwaway board: who is spawned, who wakes, which gate asks a human, and where it would stall. A stall blocks Publish.</p>
      <AdminError error={error} testid="dryrun-error" />
      {run?.stall ? (
        <div className={ui.banner} role="alert" data-testid="dryrun-stall">
          <strong>Stalls at “{run.stall.step}”:</strong> needs {run.stall.needs}.
          <ul className={styles.pre}>{run.stall.tried.map((t, i) => <li key={i}><strong>{t.role}</strong>: {t.refusal}</li>)}</ul>
        </div>
      ) : run ? <p className={styles.muted} data-testid="dryrun-ok">The synthetic epic reached done.</p> : null}
      {run ? (
        <ol className={styles.timeline} data-testid="dryrun-timeline">
          {rows.map((e, i) => (
            <li key={i} className={`${styles.tl} ${KIND_CLASS[e.kind] ?? ""}`} data-kind={e.kind}>
              <span className={styles.tlKind}>{e.kind}</span><span>{e.text}</span>
            </li>
          ))}
        </ol>
      ) : null}
    </div>
  );
}

export function DiffPanel({ wf, rows }: { wf: WorkflowDef; rows: WorkflowRow[] }): React.JSX.Element {
  const [against, setAgainst] = useState<string>(wf.source ?? "");
  const q = useQuery({
    queryKey: ["workflow-diff", against, JSON.stringify(wf)],
    queryFn: async () => (await diffWorkflow(against, wf)).value,
    enabled: Boolean(against),
    retry: false,
  });
  return (
    <div className={styles.card} data-testid="design-diff">
      <div className={styles.spread}>
        <h2 className={styles.cardTitle}>Diff</h2>
        <label className={styles.check}>
          <span className={styles.fieldLabel}>against</span>
          <select className={ui.select} value={against} onChange={(e) => setAgainst(e.target.value)} data-testid="diff-against">
            <option value="">pick a version</option>
            {rows.map((r) => <option key={r.ref} value={r.ref}>{r.ref}{r.ref === wf.source ? " (source)" : ""}</option>)}
          </select>
        </label>
      </div>
      {!against ? <p className={styles.muted}>This version has no source; pick one to compare with.</p> : null}
      <AdminError error={q.error} testid="diff-error" />
      {q.data ? <ChangeTable changes={q.data.changes} testid="diff-table" empty={`No difference from ${against}.`} /> : null}
    </div>
  );
}

export function ChangeTable({ changes, testid, empty }: { changes: Change[]; testid: string; empty: string }): React.JSX.Element {
  if (!changes.length) return <p className={styles.muted} data-testid={`${testid}-empty`}>{empty}</p>;
  const cls = { added: styles.opAdded, removed: styles.opRemoved, changed: styles.opChanged };
  return (
    <div className={styles.svgWrap}>
      <table className={styles.diffTable} data-testid={testid}>
        <thead><tr><th>Field</th><th>Change</th><th>Before</th><th>After</th></tr></thead>
        <tbody>
          {changes.map((c) => (
            <tr key={c.path} data-path={c.path}>
              <td className={styles.mono}>{c.path}</td>
              <td className={cls[c.op]}>{c.op}</td>
              <td className={styles.mono}>{short(c.before)}</td>
              <td className={styles.mono}>{short(c.after)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** "Upstream changed": the version this one was duplicated from has a newer published version. */
export function UpstreamBanner({ refStr, canEdit, onMerged }: { refStr: string; canEdit: boolean; onMerged: (r: MergeResult) => void }): React.JSX.Element | null {
  const q = useQuery({ queryKey: ["workflow", refStr, "upstream"], queryFn: () => getUpstream(refStr), retry: false });
  const [open, setOpen] = useState(false);
  const [merged, setMerged] = useState<MergeResult | null>(null);
  const merge = useMutation({
    mutationFn: async () => (await mergeUpstream(refStr)).value,
    onSuccess: (r) => { setMerged(r); onMerged(r); },
  });
  const up = q.data;
  if (merged) {
    return (
      <div className={styles.upstream} data-testid="upstream-merged">
        <strong>Merged {up?.latest} into draft {merged.draft.id}@{merged.draft.version}.</strong>
        {merged.conflicts.length ? (
          <>
            <span className={styles.muted}>{merged.conflicts.length} conflict{merged.conflicts.length === 1 ? "" : "s"} kept this version's value; review each:</span>
            <table className={styles.diffTable} data-testid="upstream-conflicts">
              <thead><tr><th>Field</th><th>Base</th><th>Yours (kept)</th><th>Upstream</th></tr></thead>
              <tbody>{merged.conflicts.map((c) => <tr key={c.path}><td className={styles.mono}>{c.path}</td><td className={styles.mono}>{short(c.base)}</td><td className={styles.mono}>{short(c.ours)}</td><td className={styles.mono}>{short(c.theirs)}</td></tr>)}</tbody>
            </table>
          </>
        ) : <span className={styles.muted}>No conflicts: {merged.taken.length} upstream change{merged.taken.length === 1 ? "" : "s"} taken.</span>}
      </div>
    );
  }
  if (!up?.changed) return null;
  return (
    <div className={styles.upstream} data-testid="upstream-banner">
      <div className={styles.spread}>
        <strong>Upstream changed: {up.source} → {up.latest} ({up.diff.length} change{up.diff.length === 1 ? "" : "s"})</strong>
        <div className={styles.row}>
          <button type="button" className={`${ui.button} ${styles.small}`} onClick={() => setOpen((o) => !o)} data-testid="upstream-show">{open ? "Hide" : "Three-way diff"}</button>
          {canEdit ? (
            <button type="button" className={`${ui.button} ${ui.buttonPrimary} ${styles.small}`} disabled={merge.isPending}
              onClick={() => merge.mutate()} data-testid="upstream-merge">{merge.isPending ? "Merging…" : "Merge into a new draft"}</button>
          ) : null}
        </div>
      </div>
      {open ? (
        <>
          <span className={styles.help}>Base = {up.source} as you duplicated it; upstream = {up.latest}; yours = this version. The merge takes every upstream change you did not also make; a field both changed keeps yours and is listed.</span>
          <ChangeTable changes={up.diff} testid="upstream-diff" empty="No upstream change." />
        </>
      ) : null}
      <AdminError error={merge.error} testid="upstream-error" />
    </div>
  );
}
