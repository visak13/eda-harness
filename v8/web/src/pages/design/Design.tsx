import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router";
import { getModels } from "../../api/seats";
import {
  dryRunWorkflow, duplicateWorkflow, getTemplates, getWorkflow, listWorkflows, publishWorkflow, refOf, saveWorkflow,
  validateWorkflow,
} from "../../api/workflows";
import type { DryRun, MergeResult, Problem, WorkflowDef } from "../../api/workflows";
import { PageHeader } from "../../components/PageHeader";
import { Tabs } from "../../components/Tabs";
import ui from "../../components/ui.module.css";
import { useIsAdmin } from "../admin/Admin";
import { AdminError, Done } from "../admin/shared";
import { DiffPanel, DryRunPanel, UpstreamBanner, ValidatePanel } from "./CheckPanels";
import styles from "./Design.module.css";
import { PANELS, ROLE_ID, bodyOf, rolesWithErrors, type PanelKey } from "./model";
import { PipelineView } from "./PipelineView";
import { CapsPanel, GatesPanel, HooksPanel } from "./PolicyPanels";
import { RolePanel } from "./RolePanel";
import { WorkflowList } from "./WorkflowList";

// S14 (design-e963c656f5 §4.14): the Design tab. Everyone reads every workflow version; only an admin edits,
// and only a draft (a preset or a published version is immutable: Duplicate to edit). Publish = save, then
// the board's Validate (lint + dry run), then publish — any error stops it and opens Validate.

export function DesignPage(): React.JSX.Element {
  const [params, setParams] = useSearchParams();
  const qc = useQueryClient();
  const { admin } = useIsAdmin();
  const list = useQuery({ queryKey: ["workflows"], queryFn: listWorkflows });
  const templates = useQuery({ queryKey: ["workflow-templates"], queryFn: getTemplates, staleTime: Infinity });
  const catalog = useQuery({ queryKey: ["models"], queryFn: getModels, retry: false });
  const rows = list.data ?? [];
  const selected = params.get("wf") ?? rows.find((r) => r.builtin && r.id === "standard")?.ref ?? rows[0]?.ref ?? null;
  const panel = (PANELS.some((p) => p.key === params.get("panel")) ? params.get("panel") : "pipeline") as PanelKey;
  const setParam = (patch: Record<string, string | null>) => setParams((old) => {
    const p = new URLSearchParams(old);
    for (const [k, v] of Object.entries(patch)) { if (v === null) p.delete(k); else p.set(k, v); }
    return p;
  }, { replace: true });

  const wfq = useQuery({ queryKey: ["workflow", selected], queryFn: () => getWorkflow(selected ?? ""), enabled: Boolean(selected) });
  const [draft, setDraft] = useState<WorkflowDef | null>(null);
  const [dirty, setDirty] = useState(false);
  const [problems, setProblems] = useState<Problem[] | null>(null);
  const [run, setRun] = useState<DryRun | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  useEffect(() => {
    if (wfq.data) { setDraft(bodyOf(wfq.data)); setDirty(false); setProblems(null); setRun(null); }
  }, [wfq.data]);

  const editable = Boolean(admin && draft && !draft.builtin && !draft.published);
  const change = (wf: WorkflowDef) => { setDraft(wf); setDirty(true); setDone(null); };
  const open = (ref: string, extra: Record<string, string | null> = {}) => { setParam({ wf: ref, role: null, ...extra }); setDone(null); };

  const [dupFor, setDupFor] = useState<string | null>(null);
  const duplicate = useMutation({
    mutationFn: async ({ ref, newId }: { ref: string; newId?: string }) => (await duplicateWorkflow(ref, newId)).value,
    onSuccess: async (d) => {
      setDupFor(null);
      await qc.invalidateQueries({ queryKey: ["workflows"] });
      open(refOf(d));
      setDone(`Draft ${refOf(d)} created from ${d.source}. Edit it, then Validate and Publish.`);
    },
  });
  const save = useMutation({
    mutationFn: async (d: WorkflowDef) => (await saveWorkflow(d)).value,
    onSuccess: async (d) => {
      setDirty(false);
      qc.setQueryData(["workflow", refOf(d)], d);
      await qc.invalidateQueries({ queryKey: ["workflows"] });
    },
  });
  const validate = useMutation({
    mutationFn: async (d: WorkflowDef) => (await validateWorkflow(d)).value,
    onSuccess: (r) => setProblems(r.problems),
  });
  const dry = useMutation({
    mutationFn: async (d: WorkflowDef) => (await dryRunWorkflow(d)).value,
    onSuccess: setRun,
  });
  const publish = useMutation({
    mutationFn: async (d: WorkflowDef) => {
      await saveWorkflow(d);
      setDirty(false);
      const v = (await validateWorkflow(d)).value;
      setProblems(v.problems);
      if (v.problems.some((p) => p.severity === "error")) return null;
      return (await publishWorkflow(refOf(d))).value;
    },
    onSuccess: async (d) => {
      if (!d) { setParam({ panel: "validate" }); return; }
      await qc.invalidateQueries({ queryKey: ["workflows"] });
      await qc.invalidateQueries({ queryKey: ["workflow", refOf(d)] });
      setDone(`${refOf(d)} is published and immutable. New epics may pin it.`);
    },
  });
  const busy = save.isPending || validate.isPending || publish.isPending || duplicate.isPending;
  const errorRoles = useMemo(() => rolesWithErrors(problems ?? wfq.data?.problems ?? []), [problems, wfq.data]);
  const errorCount = (problems ?? []).filter((p) => p.severity === "error").length;
  const tabs = PANELS.map((p) => ({ key: p.key, label: p.label, ...(p.key === "validate" && errorCount ? { count: errorCount } : {}) }));
  const go = (p: PanelKey, role?: string, field?: string) => {
    setParam({ panel: p, ...(role ? { role } : {}) });
    setFocus(field ? `${field}#${Date.now()}` : null);
  };
  const focusField = focus ? focus.split("#")[0] : null;

  return (
    <div className={styles.page} data-testid="design-page">
      <PageHeader title="Design" subtitle="The workflows epics run on: roles, how work moves, the gates a human answers and the caps. Epics pin a published version." />
      {!admin ? <p className={styles.readonly} data-testid="design-readonly">Read-only: only an admin edits workflows. You can read every version and its dry run.</p> : null}
      <AdminError error={list.error} testid="design-list-error" />
      <div className={styles.layout}>
        <div>
          <WorkflowList rows={rows} selected={selected} canEdit={admin} pending={busy}
            onSelect={(ref) => open(ref)} onDuplicate={(ref) => setDupFor(ref)} />
          {dupFor ? <DuplicateForm refStr={dupFor} builtin={rows.find((r) => r.ref === dupFor)?.builtin ?? false}
            pending={duplicate.isPending} onCancel={() => setDupFor(null)} onSubmit={(newId) => duplicate.mutate({ ref: dupFor, newId })} /> : null}
          <AdminError error={duplicate.error} testid="design-duplicate-error" />
        </div>
        <div className={styles.page}>
          {wfq.isLoading ? <p className={ui.empty}>Loading…</p> : null}
          <AdminError error={wfq.error} testid="design-load-error" />
          {draft ? (
            <>
              <div className={styles.spread}>
                <div className={styles.row}>
                  <h2 className={styles.cardTitle} data-testid="design-title">{draft.name} <span className={styles.mono}>{refOf(draft)}</span></h2>
                  <span className={`${styles.badge} ${draft.published ? styles.badgePub : styles.badgeDraft}`} data-testid="design-state">
                    {draft.builtin ? "preset" : draft.published ? "published" : dirty ? "draft · unsaved" : "draft"}
                  </span>
                </div>
                {editable ? (
                  <div className={styles.toolbar}>
                    <button type="button" className={ui.button} disabled={busy || !dirty} data-testid="design-save" onClick={() => save.mutate(draft)}>{save.isPending ? "Saving…" : "Save draft"}</button>
                    <button type="button" className={ui.button} disabled={busy} data-testid="design-validate-run"
                      onClick={() => { validate.mutate(draft); setParam({ panel: "validate" }); }}>{validate.isPending ? "Validating…" : "Validate"}</button>
                    <button type="button" className={ui.button} disabled={busy || dry.isPending} data-testid="design-dryrun-run"
                      onClick={() => { dry.mutate(draft); setParam({ panel: "dryrun" }); }}>Dry run</button>
                    <button type="button" className={`${ui.button} ${ui.buttonPrimary}`} disabled={busy} data-testid="design-publish"
                      onClick={() => publish.mutate(draft)}>{publish.isPending ? "Publishing…" : `Publish ${refOf(draft)}`}</button>
                  </div>
                ) : admin ? (
                  <button type="button" className={ui.button} disabled={busy} data-testid="design-duplicate" onClick={() => setDupFor(refOf(draft))}>Duplicate to edit</button>
                ) : null}
              </div>
              {draft.description ? <p className={styles.muted}>{draft.description}</p> : null}
              {admin && !editable ? <p className={styles.readonly} data-testid="design-immutable">{draft.builtin ? "A preset" : "A published version"} is immutable. Duplicate it to edit a new draft.</p> : null}
              <AdminError error={save.error ?? validate.error ?? publish.error} testid="design-error" />
              <Done text={done} testid="design-done" />
              {!draft.builtin ? <UpstreamBannerSlot refStr={refOf(draft)} canEdit={admin}
                onMerged={async (r: MergeResult) => { await qc.invalidateQueries({ queryKey: ["workflows"] }); open(refOf(r.draft)); setDone(`Draft ${refOf(r.draft)} holds the merge.`); }} /> : null}
              <Tabs tabs={tabs} active={panel} onChange={(k) => setParam({ panel: k })} />
              {panel === "pipeline" ? <PipelineView wf={draft} /> : null}
              {panel === "roles" ? (
                <RolePanel wf={draft} savedRef={refOf(draft)} editable={editable} templates={templates.data} catalog={catalog.data}
                  selected={params.get("role")} onSelect={(id) => setParam({ role: id })} onChange={change}
                  errorRoles={errorRoles} focusField={focusField} />
              ) : null}
              {panel === "hooks" ? <HooksPanel wf={draft} editable={editable} onChange={change} focusField={focusField} templates={templates.data} /> : null}
              {panel === "gates" ? <GatesPanel wf={draft} editable={editable} onChange={change} focusField={focusField} /> : null}
              {panel === "caps" ? <CapsPanel wf={draft} editable={editable} onChange={change} focusField={focusField} /> : null}
              {panel === "validate" ? <ValidatePanel problems={problems ?? (editable ? null : wfq.data?.problems ?? [])} ran={problems !== null || !editable} onGo={go} /> : null}
              {panel === "dryrun" ? <DryRunPanel run={run} pending={dry.isPending} error={dry.error} onRun={() => dry.mutate(draft)} /> : null}
              {panel === "diff" ? <DiffPanel key={refOf(draft)} wf={draft} rows={rows.filter((r) => r.ref !== refOf(draft))} /> : null}
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function UpstreamBannerSlot(p: { refStr: string; canEdit: boolean; onMerged: (r: MergeResult) => void }): React.JSX.Element | null {
  return <UpstreamBanner key={p.refStr} {...p} />;
}

function DuplicateForm({ refStr, builtin, pending, onCancel, onSubmit }: {
  refStr: string; builtin: boolean; pending: boolean; onCancel: () => void; onSubmit: (newId?: string) => void;
}): React.JSX.Element {
  const baseId = refStr.split("@")[0];
  const [mode, setMode] = useState<"version" | "id">(builtin ? "id" : "version");
  const [id, setId] = useState(builtin ? `${baseId}-custom` : `${baseId}-copy`);
  const bad = mode === "id" && !ROLE_ID.test(id);
  return (
    <form className={styles.card} data-testid="duplicate-form" onSubmit={(e) => { e.preventDefault(); if (!bad) onSubmit(mode === "id" ? id : undefined); }}>
      <strong>Duplicate {refStr}</strong>
      {!builtin ? (
        <div className={styles.checks}>
          <label className={styles.check}><input type="radio" checked={mode === "version"} onChange={() => setMode("version")} />as the next version of {baseId}</label>
          <label className={styles.check}><input type="radio" checked={mode === "id"} onChange={() => setMode("id")} />as a new workflow</label>
        </div>
      ) : <span className={styles.help}>A preset keeps its id; your copy gets its own and tracks {refStr} as its upstream.</span>}
      {mode === "id" ? (
        <label className={styles.field}>
          <span className={styles.fieldLabel}>new id</span>
          <input className={ui.input} value={id} onChange={(e) => setId(e.target.value.trim())} data-testid="duplicate-id" aria-invalid={bad} />
          <span className={styles.help}>{bad ? "Lowercase letters, digits and dashes, starting with a letter." : "Epics show it as <id>@<version>."}</span>
        </label>
      ) : null}
      <div className={styles.row}>
        <button type="submit" className={`${ui.button} ${ui.buttonPrimary}`} disabled={pending || bad} data-testid="duplicate-submit">{pending ? "Duplicating…" : "Create draft"}</button>
        <button type="button" className={ui.button} onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}
