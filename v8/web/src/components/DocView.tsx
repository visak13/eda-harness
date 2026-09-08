import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getDocHtml, sendMessage } from "../api/endpoints";
import type { DocHtml } from "../api/types";
import { identity } from "../auth/identity";
import { Markdown } from "./Markdown";
import { SignoffPane } from "./SignoffPane";
import { DocControls } from "./DocControls";
import ui from "./ui.module.css";
import styles from "./DocView.module.css";

// The document reader body (design §4.1/§14/§17) shared by the full page (/doc/:id) and the
// §17 drawer. It shows: version pills, doc meta, the sanitised HTML, the viewer's pending
// sign-off criterion inline as a one-click ruling card (when the board reports one for this
// doc), and a comment box that posts "[doc <id> v<n>] text" to the doc's scope ticket.
//
// `onOpenDoc` (drawer only) intercepts nested doc links so they open in the same drawer instead
// of navigating. `onOpenTicket` similarly for ticket links. The version the reader opened is
// frozen and named on every verdict (§14).
export function DocView({
  docId,
  version,
  onOpenDoc,
  onOpenTicket,
}: {
  docId: string;
  version?: number | null;
  onOpenDoc?: (id: string) => void;
  onOpenTicket?: (id: string) => void;
}): React.JSX.Element {
  const q = useQuery({
    queryKey: ["doc", docId, version ?? null],
    queryFn: () => getDocHtml(docId, version),
  });

  if (q.isPending) return <p className={ui.empty}>Loading document…</p>;
  if (q.isError)
    return (
      <p className={ui.banner} role="alert">
        Could not load {docId}: {(q.error as Error).message}
      </p>
    );
  return <DocBody doc={q.data} onOpenDoc={onOpenDoc} onOpenTicket={onOpenTicket} />;
}

function DocBody({
  doc,
  onOpenDoc,
  onOpenTicket,
}: {
  doc: DocHtml;
  onOpenDoc?: (id: string) => void;
  onOpenTicket?: (id: string) => void;
}): React.JSX.Element {
  const as = identity();
  const qc = useQueryClient();
  const latest = doc.versions.length ? Math.max(...doc.versions) : doc.version;
  const [comment, setComment] = useState("");
  const [posted, setPosted] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);

  // The legacy reader shows the comment box only when the scope is a ticket (not domain:/global);
  // a comment posts "[doc id vN] text" to that ticket's thread.
  const scopeIsTicket = !doc.scope.includes(":") && doc.scope !== "global";

  const commentMut = useMutation({
    mutationFn: () =>
      sendMessage({
        ticket_id: doc.scope,
        kind: "note",
        text: `[doc ${doc.id} v${doc.version}] ${comment}`,
      }),
    onSuccess: () => {
      setComment("");
      setPosted(true);
      void qc.invalidateQueries();
    },
  });

  // Intercept nested doc/ticket links (design §17: they open in the same drawer, no page load).
  function onBodyClick(e: React.MouseEvent) {
    if (!onOpenDoc && !onOpenTicket) return;
    const a = (e.target as HTMLElement).closest("a");
    if (!a) return;
    const href = a.getAttribute("href") ?? "";
    const doc_ = href.match(/\/(?:ui|app)?\/?doc\/([\w.-]+)/) ?? href.match(/[?&]doc=([\w.-]+)/);
    const tkt = href.match(/\/(?:ui|app)?\/?ticket\/([\w.-]+)/);
    if (doc_ && onOpenDoc) {
      e.preventDefault();
      onOpenDoc(doc_[1]);
    } else if (tkt && onOpenTicket) {
      e.preventDefault();
      onOpenTicket(tkt[1]);
    }
  }

  return (
    <div className={styles.doc}>
      <p className={styles.meta}>
        {doc.doc_type} · owner {doc.owner_role} · scope <span className={ui.idMono}>{doc.scope}</span> ·
        version {doc.version}
      </p>

      {doc.versions.length > 1 ? (
        <div className={styles.versions} aria-label="Versions">
          {doc.versions.map((v) => (
            <span key={v} className={`${styles.vpill} ${v === doc.version ? styles.vactive : ""}`}>
              v{v}
              {v === latest ? " · latest" : ""}
            </span>
          ))}
        </div>
      ) : null}

      <SignoffPane doc={doc} />

      <div ref={bodyRef} onClick={onBodyClick}>
        <Markdown html={doc.html} />
      </div>

      {scopeIsTicket ? (
        <div className={styles.commentBox}>
          <div className={ui.sectionLabel}>Comment on this document</div>
          <textarea
            className={ui.textarea}
            aria-label="Comment"
            value={comment}
            placeholder={`Comment as @${as} — posts to ${doc.scope}`}
            onChange={(e) => {
              setComment(e.target.value);
              setPosted(false);
            }}
          />
          {posted ? <p className={styles.posted}>Comment posted to the thread.</p> : null}
          <div className={styles.commentActions}>
            <button
              type="button"
              className={`${ui.button} ${ui.buttonPrimary}`}
              disabled={commentMut.isPending || comment.trim() === ""}
              onClick={() => commentMut.mutate()}
            >
              Comment
            </button>
          </div>
        </div>
      ) : null}

      <DocControls docId={doc.id} scope={doc.scope} version={doc.version} scopeIsThread={scopeIsTicket} />
    </div>
  );
}
