import { useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createKnowledgeDoc, importSkill } from "../api/endpoints";
import type { BoardApiError } from "../api/client";
import ui from "../components/ui.module.css";
import dialogStyles from "../components/NewEpicDialog.module.css";
import { useModalDialog } from "../components/useModalDialog";
import { parseTags } from "./KnowledgeDetail";
import { KIND_LABEL, KNOWLEDGE_KINDS } from "./knowledgeShared";

// The two Library add paths (S-LIBRARY). Both are page dialogs under the shared modal contract
// (Esc closes and restores focus, focus trapped, background inert). The board's error sentence
// shows verbatim; success selects the new doc in the list.

function errText(e: unknown): string | null {
  if (!e) return null;
  const b = e as BoardApiError;
  return b.hint || b.message;
}

export function NewKnowledgeDialog({ open, onClose, onCreated }: {
  open: boolean; onClose: () => void; onCreated: (id: string) => void;
}): React.JSX.Element | null {
  const [kind, setKind] = useState<string>("strategy_hl");
  const [title, setTitle] = useState("");
  const [tags, setTags] = useState("");
  const [body, setBody] = useState("");
  const panelRef = useRef<HTMLFormElement>(null);
  const firstRef = useRef<HTMLSelectElement>(null);
  const busy = useRef(false);
  const qc = useQueryClient();
  useModalDialog(open, panelRef, firstRef, busy, onClose);
  const create = useMutation({
    mutationFn: () => createKnowledgeDoc({ doc_type: kind, title: title.trim(), body_md: body, tags: parseTags(tags) }),
    onSuccess: (res) => {
      void qc.invalidateQueries({ queryKey: ["knowledge"] });
      setTitle(""); setTags(""); setBody("");
      onCreated(res.value.id);
      onClose();
    },
    onSettled: () => { busy.current = false; },
  });
  if (!open) return null;
  const ready = Boolean(title.trim()) && Boolean(body.trim());
  return createPortal(
    <div className={dialogStyles.scrim} onMouseDown={(e) => e.target === e.currentTarget && !busy.current && onClose()}>
      <form className={dialogStyles.dialog} ref={panelRef} role="dialog" aria-modal="true" aria-label="New knowledge doc"
        data-testid="knowledge-new-dialog"
        onSubmit={(e) => { e.preventDefault(); if (ready && !busy.current) { busy.current = true; create.mutate(); } }}>
        <h2 className={dialogStyles.title}>New knowledge doc</h2>
        <label className={ui.sectionLabel} htmlFor="kn-kind">Kind</label>
        <select id="kn-kind" ref={firstRef} className={ui.select} value={kind} onChange={(e) => setKind(e.target.value)}>
          {KNOWLEDGE_KINDS.map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
        </select>
        <label className={ui.sectionLabel} htmlFor="kn-title">Title</label>
        <input id="kn-title" className={ui.input} value={title} onChange={(e) => setTitle(e.target.value)} data-testid="knowledge-new-title" />
        <label className={ui.sectionLabel} htmlFor="kn-tags">Tags (comma or space separated)</label>
        <input id="kn-tags" className={ui.input} value={tags} onChange={(e) => setTags(e.target.value)} placeholder="python, web" />
        <label className={ui.sectionLabel} htmlFor="kn-body">Body (markdown)</label>
        <textarea id="kn-body" className={ui.textarea} rows={10} value={body} onChange={(e) => setBody(e.target.value)}
          data-testid="knowledge-new-body"
          placeholder={"- a bar a seat applies [required]\n- context a seat reads on demand"} />
        <p className={dialogStyles.muted}>Lines tagged [required]/[expected]/[preferred] or checkboxes are inlined into briefs; the rest is read on demand.</p>
        {create.isError ? <p className={ui.banner} role="alert">{errText(create.error)}</p> : null}
        <div className={dialogStyles.actions}>
          <button type="button" className={ui.button} onClick={onClose} disabled={create.isPending}>Cancel</button>
          <button type="submit" className={`${ui.button} ${ui.buttonPrimary}`} disabled={!ready || create.isPending}
            data-testid="knowledge-new-create">{create.isPending ? "Saving…" : "Create"}</button>
        </div>
      </form>
    </div>, document.body,
  );
}

export function ImportSkillDialog({ open, onClose, onImported }: {
  open: boolean; onClose: () => void; onImported: (id: string) => void;
}): React.JSX.Element | null {
  const [url, setUrl] = useState("");
  const [tags, setTags] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const panelRef = useRef<HTMLFormElement>(null);
  const firstRef = useRef<HTMLInputElement>(null);
  const busy = useRef(false);
  const qc = useQueryClient();
  useModalDialog(open, panelRef, firstRef, busy, onClose);
  const run = useMutation({
    mutationFn: () => importSkill({ url: url.trim(), tags: parseTags(tags) }),
    onSuccess: (res) => {
      void qc.invalidateQueries({ queryKey: ["knowledge"] });
      setDone(res.hint);
      onImported(res.value.doc.id);
    },
    onSettled: () => { busy.current = false; },
  });
  if (!open) return null;
  const ready = /^https:\/\/\S+$/.test(url.trim());
  const close = () => { setDone(null); setUrl(""); setTags(""); run.reset(); onClose(); };
  return createPortal(
    <div className={dialogStyles.scrim} onMouseDown={(e) => e.target === e.currentTarget && !busy.current && close()}>
      <form className={dialogStyles.dialog} ref={panelRef} role="dialog" aria-modal="true" aria-label="Import from skills.sh"
        data-testid="knowledge-import-dialog"
        onSubmit={(e) => { e.preventDefault(); if (ready && !busy.current) { busy.current = true; setDone(null); run.mutate(); } }}>
        <h2 className={dialogStyles.title}>Import from skills.sh</h2>
        <label className={ui.sectionLabel} htmlFor="ki-url">Skill page or SKILL.md URL</label>
        <input id="ki-url" ref={firstRef} className={ui.input} value={url} onChange={(e) => setUrl(e.target.value)}
          placeholder="https://skills.sh/anthropics/skills/frontend-design" data-testid="knowledge-import-url" />
        <label className={ui.sectionLabel} htmlFor="ki-tags">Extra tags (optional)</label>
        <input id="ki-tags" className={ui.input} value={tags} onChange={(e) => setTags(e.target.value)} placeholder="web, design" />
        <p className={dialogStyles.muted}>
          The board fetches the skill once (skills.sh page, a GitHub blob or a raw SKILL.md; 256 KB, 10 s) and files it as a
          high-level strategy with the skill's tags. Importing the same URL again writes the next version. Nothing runs at seat boot.
        </p>
        {run.isError ? <p className={ui.banner} role="alert" data-testid="knowledge-import-error">{errText(run.error)}</p> : null}
        {done ? <p className={dialogStyles.preview} role="status" data-testid="knowledge-import-done">{done}</p> : null}
        <div className={dialogStyles.actions}>
          <button type="button" className={ui.button} onClick={close} disabled={run.isPending}>{done ? "Done" : "Cancel"}</button>
          <button type="submit" className={`${ui.button} ${ui.buttonPrimary}`} disabled={!ready || run.isPending}
            data-testid="knowledge-import-run">{run.isPending ? "Fetching…" : "Import"}</button>
        </div>
      </form>
    </div>, document.body,
  );
}
