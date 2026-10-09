import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { retireLesson } from "../api/endpoints";
import { api } from "../api/client";
import type { BoardApiError } from "../api/client";
import type { KnowledgeLesson } from "../api/types";
import type { WhoAmI } from "../auth/useViewer";
import ui from "../components/ui.module.css";
import styles from "./Knowledge.module.css";

// Sweep #4 (note-8f0629190d): one lesson in the Library — what it says, who it reaches (scope), where it came
// from, and, for the owner, Retire. A retired lesson shows its reason and no action.

export function lessonScope(l: KnowledgeLesson): string {
  return l.scope_kind === "project" ? `project · ${l.project || "unnamed"}` : "framework";
}

export function LessonDetail({ lesson, onClose }: { lesson: KnowledgeLesson; onClose: () => void }): React.JSX.Element {
  const qc = useQueryClient();
  const who = useQuery({ queryKey: ["whoami"], queryFn: () => api<WhoAmI>("/v1/whoami"), retry: false });
  const owner = who.data?.participant.role === "owner";
  const [reason, setReason] = useState("");
  const retire = useMutation({
    mutationFn: () => retireLesson(lesson.id, reason.trim()),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["knowledge"] }); },
  });
  const retired = lesson.status === "retired";
  const err = retire.error as BoardApiError | null;
  return (
    <aside className={styles.detail} aria-label={`Lesson ${lesson.topic}`} data-testid="lesson-detail">
      <h2 className={styles.detailTitle}>{lesson.domain} · {lesson.topic}</h2>
      <p className={styles.muted}>
        <span className={ui.tag}>lesson</span> <span className={styles.status} data-testid="lesson-status">{retired ? "Retired" : "Active"}</span> · {lesson.id} · by {lesson.created_by}
      </p>
      <p data-testid="lesson-text">{lesson.text}</p>
      <p className={styles.muted} data-testid="lesson-scope">
        Reaches: {lesson.scope_kind === "project" ? `epics of project ${lesson.project}` : "framework epics (Heronry's own work)"}
      </p>
      {lesson.domains?.length ? <p className={styles.muted}>Also ranked under: {lesson.domains.join(", ")}</p> : null}
      {retired ? <p className={styles.muted} data-testid="lesson-reason">Retired: {lesson.retired_reason || "no reason recorded"}</p> : null}
      <div className={styles.actions}>
        {owner && !retired ? (
          <>
            <input className={ui.input} aria-label="Reason to retire" placeholder="Why retire it?" value={reason}
              onChange={(e) => setReason(e.target.value)} data-testid="lesson-retire-reason" />
            <button type="button" className={`${ui.button} ${ui.buttonFail}`} disabled={retire.isPending}
              onClick={() => { if (window.confirm("Retire this lesson? Seats stop recalling it.")) retire.mutate(); }}
              data-testid="lesson-retire">Retire</button>
          </>
        ) : null}
        <button type="button" className={ui.button} onClick={onClose}>Close</button>
      </div>
      {err ? <p className={ui.banner} role="alert">{err.hint || err.message}</p> : null}
    </aside>
  );
}
