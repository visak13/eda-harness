import { useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { cutRelease, getRelease, getUpdates } from "../../api/admin";
import type { CutBody } from "../../api/admin";
import ui from "../../components/ui.module.css";
import dialogStyles from "../../components/NewEpicDialog.module.css";
import { useModalDialog } from "../../components/useModalDialog";
import styles from "./Admin.module.css";
import { AdminError, Done, adminRefused } from "./shared";

// Admin → Updates → Cut release (S10, owner R8): the owner dispatches release.yml through the board. A dry run
// (the default) validates only; a real run tags, builds and drafts; "publish" on top makes the draft public.
// Always behind a confirm dialog that says exactly what will happen; enabled only when the board says can_cut.

const VERSION = /^v?\d+\.\d+\.\d+$/;

export function CutRelease(): React.JSX.Element | null {
  const q = useQuery({ queryKey: ["admin", "release"], queryFn: getRelease, retry: false, staleTime: 60_000 });
  // S12-ui2 (m2): Version prefills the RUNNING version (Admin → Updates' `current`, the same query Services reads)
  // until the owner types; the board's reason reads as a sentence.
  const updates = useQuery({ queryKey: ["admin", "updates"], queryFn: getUpdates, retry: false, staleTime: 60_000 });
  const [typed, setVersion] = useState<string | null>(null);
  const version = typed ?? updates.data?.current ?? "";
  const [dryRun, setDryRun] = useState(true);
  const [publish, setPublish] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const busy = useRef(false);
  const cut = useMutation({
    mutationFn: (b: CutBody) => cutRelease(b),
    onSettled: () => { busy.current = false; setConfirming(false); },
  });
  useModalDialog(confirming, panelRef, confirmRef, busy, () => setConfirming(false));
  const r = q.data;
  if (!r) return q.error && !adminRefused(q.error) ? <AdminError error={q.error} testid="release-error" /> : null; // a refused admin route is said once, by the Services table
  const valid = VERSION.test(version.trim());
  const bare = version.trim().replace(/^v/, "");
  const tag = `v${bare}`;
  const body: CutBody = { version: bare, dry_run: dryRun, publish: publish && !dryRun };
  const what = dryRun
    ? "A dry run: GitHub validates the tag and writes a summary. Nothing is tagged, built or published."
    : body.publish
      ? "A real release: the tag is created when absent, every installer is built, and the release is PUBLISHED publicly."
      : "A real run: the tag is created when absent and every installer is built into a DRAFT release. Nothing is public until you publish it.";
  return (
    <section className={styles.card} data-testid="cut-release">
      <div className={styles.cardHead}><h2 className={styles.cardTitle}>Cut release</h2></div>
      {!r.can_cut ? <p className={styles.fieldNote} data-testid="cut-release-refusal">{r.reason ? r.reason.charAt(0).toUpperCase() + r.reason.slice(1) : null}</p> : null}
      <div className={styles.row}>
        <label htmlFor="cut-version">Version</label>
        <input id="cut-version" className={ui.input} data-testid="cut-version" placeholder="0.10.0" value={version}
          disabled={!r.can_cut} onChange={(e) => setVersion(e.target.value)} />
        <label className={styles.row}>
          <input type="checkbox" checked={dryRun} disabled={!r.can_cut} data-testid="cut-dry-run"
            onChange={(e) => { setDryRun(e.target.checked); if (e.target.checked) setPublish(false); }} />
          Dry run (validate only)
        </label>
        <label className={styles.row}>
          <input type="checkbox" checked={publish && !dryRun} disabled={!r.can_cut || dryRun} data-testid="cut-publish"
            onChange={(e) => setPublish(e.target.checked)} />
          Publish when built
        </label>
        <button type="button" className={`${ui.button} ${ui.buttonPrimary}`} data-testid="cut-release-open"
          disabled={!r.can_cut || !valid || cut.isPending} onClick={() => setConfirming(true)}>
          {cut.isPending ? "Sending…" : "Cut release…"}
        </button>
      </div>
      <p className={styles.fieldDoc}>Builds a release from the {r.default_ref} branch. {r.last ? `Last: ${r.last.tag} by ${r.last.by} (${r.last.dry_run === "true" ? "dry run" : "real"}).` : "No release cut from here yet."}</p>
      <AdminError error={cut.error} testid="cut-release-error" />
      <Done text={cut.data ? `Dispatched ${cut.data.value.tag}. Follow it at ${cut.data.value.runs_url}. ${cut.data.hint}` : null} testid="cut-release-done" />
      {confirming ? createPortal(
        <div className={dialogStyles.scrim} onMouseDown={(e) => e.target === e.currentTarget && !busy.current && setConfirming(false)}>
          <div className={dialogStyles.dialog} ref={panelRef} role="dialog" aria-modal="true" aria-label="Confirm cut release" data-testid="cut-confirm">
            <h2 className={dialogStyles.title}>Cut {tag}?</h2>
            <p data-testid="cut-confirm-text"><strong>{r.repo}</strong> · tag <code>{tag}</code> · branch {r.default_ref}</p>
            <p>{what}</p>
            <div className={dialogStyles.actions}>
              <button type="button" className={ui.button} data-testid="cut-cancel" onClick={() => setConfirming(false)}>Cancel</button>
              <button type="button" ref={confirmRef} className={`${ui.button} ${ui.buttonPrimary}`} data-testid="cut-confirm-go"
                onClick={() => { if (!busy.current) { busy.current = true; cut.mutate(body); } }}>
                {dryRun ? "Confirm dry run" : body.publish ? "Confirm and publish" : "Confirm"}
              </button>
            </div>
          </div>
        </div>, document.body) : null}
    </section>
  );
}
