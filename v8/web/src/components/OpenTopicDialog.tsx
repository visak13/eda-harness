import { useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { addTopicExpert, openTopic } from "../api/endpoints";
import { parseTags } from "../pages/KnowledgeDetail";
import { getModels } from "../api/seats";
import { clampEffort, SeatPickHead, SeatPickRow, type Effort } from "./SeatPicks";
import type { ExpertAdded, ModelCatalog } from "../api/types";
import type { BoardApiError } from "../api/client";
import ui from "./ui.module.css";
import styles from "./NewEpicDialog.module.css";
import { useModalDialog } from "./useModalDialog";

// t-f5bf848f0f (owner m-30d50df723 "the topics pop-up is nothing similar to the tickets or epics pop-up.
// its low-effort."): Library → Topics → Open topic, built to NewEpicDialog's standard, control for control —
// title with the n/80 counter; the owner's words (the topic's purpose, kept verbatim like an epic's); tags
// with the same help line; the sme's model + effort (the SeatPickRow the per-role picks use, catalog from
// GET /v1/models role sme, Claude capped at medium); experts to add now; the seed URL with help; a preview
// of what happens; the same footer and busy/done states.
//
// Open is two steps like "create the epic, then spawn": POST /v1/topics (words, tags, seed, model, effort),
// then POST /v1/topics/<id>/experts per handle. An expert's link carries its token and is shown ONCE, so
// with experts the dialog stays open on the links (done state) instead of navigating; a failed expert keeps
// the topic and "Retry experts" adds only the ones still missing — the topic is never opened twice.

const HANDLE = /^[a-z0-9][a-z0-9_.-]{1,39}$/;
const RESERVED = new Set(["agents", "owner"]);
const SME = "sme";

/** Expert handles from free text: comma/space separated, `@` dropped, lower-case, first-seen order. */
export function parseHandles(raw: string): string[] {
  const out: string[] = [];
  for (const w of raw.split(/[\s,]+/)) {
    const h = w.trim().replace(/^@/, "").toLowerCase();
    if (h && !out.includes(h)) out.push(h);
  }
  return out;
}

const badHandle = (h: string): boolean => !HANDLE.test(h) || RESERVED.has(h);

export function OpenTopicDialog({ open, onClose, onOpened }: {
  open: boolean; onClose: () => void; onOpened: (id: string) => void;
}): React.JSX.Element | null {
  const [title, setTitle] = useState("");
  const [words, setWords] = useState("");
  const [tags, setTags] = useState("");
  const [expertsRaw, setExpertsRaw] = useState("");
  const [seed, setSeed] = useState("");
  const [model, setModel] = useState<string | null>(null);
  const [effort, setEffort] = useState<Effort>("medium");
  const committed = useRef<string | null>(null);
  const busy = useRef(false);
  const panelRef = useRef<HTMLFormElement>(null);
  const titleRef = useRef<HTMLInputElement>(null);
  const [links, setLinks] = useState<ExpertAdded[]>([]);
  const [failed, setFailed] = useState<{ handle: string; why: string }[]>([]);
  const qc = useQueryClient();
  const modelsQ = useQuery({ queryKey: ["models"], queryFn: getModels, retry: false, enabled: open });
  const catalog = modelsQ.data as ModelCatalog | undefined;
  const smeOptions = catalog?.roles[SME] ?? [];
  const smeModel = model ?? catalog?.defaults[SME] ?? "";
  const smeEffort = clampEffort(smeModel, effort);

  useModalDialog(open, panelRef, titleRef, busy, onClose);

  const reset = () => {
    setTitle(""); setWords(""); setTags(""); setExpertsRaw(""); setSeed(""); setModel(null); setEffort("medium");
    setLinks([]); setFailed([]); committed.current = null;
  };
  const finish = (id: string) => { reset(); onClose(); onOpened(id); };

  const run = useMutation({
    mutationFn: async () => {
      if (!committed.current) {
        const made = await openTopic({
          title: title.trim(), words: words.trim() ? words : null, tags: parseTags(tags),
          seed_url: seed.trim() || null, model: catalog ? smeModel || null : null, effort: catalog ? smeEffort : null,
        });
        committed.current = made.value.topic.id;
        void qc.invalidateQueries({ queryKey: ["topics"] });
      }
      const id = committed.current;
      const have = new Set(links.map((l) => l.expert.handle));
      const added: ExpertAdded[] = [];
      const missed: { handle: string; why: string }[] = [];
      for (const handle of parseHandles(expertsRaw).filter((h) => !have.has(h))) {
        try {
          added.push((await addTopicExpert(id, { handle })).value);
        } catch (e) {
          const b = e as BoardApiError;
          missed.push({ handle, why: b.hint || b.message });
        }
      }
      if (added.length) void qc.invalidateQueries({ queryKey: ["topics"] });
      return { id, added, missed };
    },
    onSuccess: ({ id, added, missed }) => {
      const all = [...links, ...added];
      setLinks(all); setFailed(missed);
      if (!all.length && !missed.length) finish(id); // nothing to hand over: straight to the topic page
    },
    onSettled: () => { busy.current = false; },
  });
  const err = run.error as BoardApiError | undefined;

  if (!open) return null;
  const done = committed.current;
  const locked = run.isPending || Boolean(done);
  const handles = parseHandles(expertsRaw);
  const bad = handles.filter(badHandle);
  const seedOk = !seed.trim() || /^https:\/\/\S+$/.test(seed.trim());
  const ready = Boolean(title.trim()) && title.trim().length <= 80 && seedOk && !bad.length;
  const plain = parseTags(tags);
  return createPortal(
    <div className={styles.scrim} onMouseDown={(e) => e.target === e.currentTarget && !busy.current && onClose()} data-testid="topic-open-scrim">
      <form
        className={styles.dialog}
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label="Open topic"
        data-testid="topic-open-dialog"
        onSubmit={(e) => {
          e.preventDefault();
          if (busy.current) return;
          if (done && !failed.length) { finish(done); return; } // links handed over: on to the topic
          if (done || ready) { busy.current = true; run.mutate(); }
        }}
      >
        <h2 className={styles.title}>Open topic</h2>
        <label className={ui.sectionLabel} htmlFor="topic-open-title">Title</label>
        <input id="topic-open-title" data-testid="topic-open-title" ref={titleRef} className={ui.input} maxLength={80}
          value={title} disabled={locked} onChange={(e) => setTitle(e.target.value)} aria-describedby="topic-open-title-count" />
        <p id="topic-open-title-count" className={styles.muted}>{title.length}/80 — required</p>
        <label className={ui.sectionLabel} htmlFor="topic-open-words">Your words</label>
        <textarea
          id="topic-open-words"
          data-testid="topic-open-words"
          className={ui.textarea}
          rows={4}
          value={words}
          disabled={locked}
          onChange={(e) => setWords(e.target.value)}
          placeholder="What this topic keeps up to date, in your own words. They are kept verbatim, separately from your title."
          aria-describedby="topic-open-words-help"
        />
        <p id="topic-open-words-help" className={styles.muted}>Optional. The sme reads them as the topic's purpose; they never change.</p>
        <label className={ui.sectionLabel} htmlFor="topic-open-tags">Tags (optional)</label>
        <input id="topic-open-tags" data-testid="topic-open-tags" className={ui.input} value={tags} disabled={locked}
          onChange={(e) => setTags(e.target.value)} placeholder="python, testing" aria-describedby="topic-open-tags-help" />
        <p id="topic-open-tags-help" className={styles.muted} data-testid="topic-open-tags-help">
          {plain.length
            ? `Tagged ${plain.join(", ")}; the sme adds its own as it researches. You can edit them on the topic page.`
            : "Plain words, comma-separated; the sme adds its own as it researches. You can edit them on the topic page."}
        </p>
        <fieldset className={styles.roleModels} data-testid="topic-open-sme-model">
          <legend className={ui.sectionLabel}>The sme's model and effort</legend>
          {modelsQ.isError ? (
            <p className={styles.muted} role="alert" data-testid="topic-open-models-error">
              Could not load the model catalog; the sme runs on its role's default.
            </p>
          ) : null}
          {smeOptions.length ? <SeatPickHead /> : null}
          {smeOptions.length ? (
            <SeatPickRow role={SME} testIdPrefix="topic-open" options={smeOptions} model={smeModel} effort={smeEffort}
              disabled={locked} onModel={setModel} onEffort={setEffort} />
          ) : null}
          <p className={styles.muted} data-testid="topic-open-effort-cap">
            Claude seats are capped at effort medium fleet-wide; high applies to GPT seats only.
          </p>
        </fieldset>
        <label className={ui.sectionLabel} htmlFor="topic-open-experts">Experts (optional)</label>
        <input id="topic-open-experts" data-testid="topic-open-experts" className={ui.input} value={expertsRaw}
          disabled={locked} onChange={(e) => setExpertsRaw(e.target.value)} placeholder="priya, dana"
          aria-describedby="topic-open-experts-help" aria-invalid={bad.length > 0} />
        <p id="topic-open-experts-help" className={styles.muted} data-testid="topic-open-experts-help">
          Handles of people from your team, comma-separated. Each gets a one-time link to read this topic and post on its
          thread, nothing else. You can add more later on the topic page.
        </p>
        {bad.length ? (
          <p className={ui.banner} role="alert" data-testid="topic-open-experts-invalid">
            Not a handle: {bad.join(", ")} (2–40 of a-z 0-9 . _ -, starting with a letter or digit; not owner or agents).
          </p>
        ) : null}
        <label className={ui.sectionLabel} htmlFor="topic-open-seed">Seed URL (optional)</label>
        <input id="topic-open-seed" data-testid="topic-open-seed" className={ui.input} value={seed} disabled={locked}
          onChange={(e) => setSeed(e.target.value)} placeholder="https://docs.pytest.org/en/stable/"
          aria-describedby="topic-open-seed-help" aria-invalid={!seedOk} />
        <p id="topic-open-seed-help" className={styles.muted}>
          A public https page. The sme reads skills.sh, GitHub skill files and pages on this site, and nothing else.
        </p>
        {!seedOk ? <p className={ui.banner} role="alert">The seed URL must start with https://</p> : null}
        <p className={styles.preview} data-testid="topic-open-preview">
          Opens the topic with your words verbatim and your explicit title, and queues its resident sme on{" "}
          {smeModel || "its role's default"} at effort {smeEffort}. The sme proposes docs; you approve them in
          Knowledge. It stays on the topic until you close it.
          {handles.length && !bad.length
            ? ` Then adds ${handles.length === 1 ? "1 expert" : `${handles.length} experts`} (${handles.join(", ")}) and shows each one-time link here.`
            : " No expert is added now."}
        </p>
        {err ? (
          <p className={ui.banner} role="alert" data-testid="topic-open-error">{err.hint || err.message}</p>
        ) : null}
        {failed.length ? (
          <p className={ui.banner} role="alert" data-testid="topic-open-experts-failed">
            {failed.map((f) => `${f.handle}: ${f.why}`).join(" · ")}
          </p>
        ) : null}
        {done ? (
          <div role="status" data-testid="topic-open-done">
            <p className={styles.muted}>
              Topic opened.{links.length ? " Send each expert their link now; it carries their token, which is not shown again." : ""}{" "}
              <Link to={`/library/topics/${encodeURIComponent(done)}`} onClick={(e) => { if (busy.current) { e.preventDefault(); return; } e.preventDefault(); finish(done); }}
                data-testid="topic-open-go">Open the topic</Link>
            </p>
            {links.length ? (
              <ul className={styles.links} data-testid="topic-open-links">
                {links.map((l) => (
                  <li key={l.expert.id} data-testid="topic-open-link">
                    <strong>{l.expert.handle}</strong>
                    <span className={styles.secret}>{`${window.location.origin}${l.link}`}</span>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
        <div className={styles.actions}>
          <button type="button" className={ui.button} onClick={() => (done ? finish(done) : onClose())} disabled={run.isPending}
            data-testid="topic-open-cancel">
            {done ? "Close" : "Cancel"}
          </button>
          <button
            type="submit"
            className={`${ui.button} ${ui.buttonPrimary}`}
            disabled={run.isPending || (!done && !ready)}
            data-testid="topic-open-create"
          >
            {run.isPending ? "Opening…" : done ? (failed.length ? "Retry experts" : "Go to the topic") : handles.length ? "Open the topic and add experts" : "Open the topic"}
          </button>
        </div>
      </form>
    </div>, document.body,
  );
}
