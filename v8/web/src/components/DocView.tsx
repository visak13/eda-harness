import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
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
// §17 drawer. Astra ruling #36 item (2) "Doc drawer/reader" (2026-09-10): two panes, 650 reading
// + 462 side, separated by a 1px rule. Reading pane: meta line, Georgia title, the sanitised HTML,
// the comment box. Side pane (sticky): the viewer's pending sign-off (only when the board reports
// one), an Outline of the body headings, an Ownership list and a History of versions.
//
// `onOpenDoc` (drawer only) intercepts nested doc links so they open in the same drawer instead
// of navigating. `onOpenTicket` similarly for ticket links. The version the reader opened is
// frozen and named on every verdict (§14).

/** Drops a trailing " (epic-…)" / " (s-…)" / " (t-…)" scope-id suffix from a display title. */
export function stripScopeId(title: string): string {
  return title.replace(/\s*\((?:epic|s|t)-[\w.-]+\)\s*$/, "").trim();
}

export type OutlineEntry = { level: 1 | 2 | 3; text: string };

/** h1/h2/h3 headings of the doc's html, in document order (empty when DOMParser is unavailable). */
export function outlineOf(html: string): OutlineEntry[] {
  if (typeof DOMParser === "undefined") return [];
  const parsed = new DOMParser().parseFromString(`<body>${html}</body>`, "text/html");
  return Array.from(parsed.body.querySelectorAll("h1, h2, h3")).map((el) => ({
    level: Number(el.tagName.slice(1)) as 1 | 2 | 3,
    text: (el.textContent ?? "").trim(),
  }));
}

export function DocView({
  docId,
  version,
  onOpenDoc,
  onOpenTicket,
  onVersion,
  onDoc,
  versionsHosted,
}: {
  docId: string;
  version?: number | null;
  onOpenDoc?: (id: string) => void;
  onOpenTicket?: (id: string) => void;
  /** Reports the version the reader is showing (the drawer's "Open as page" carries it). */
  onVersion?: (v: number) => void;
  /** Reports the pinned document (title/scope for a host page that must not run its own "latest" query). */
  onDoc?: (doc: DocHtml) => void;
  /** The host renders its own "Versions" menu (the drawer toolbar); the History block then keeps its own label. */
  versionsHosted?: boolean;
}): React.JSX.Element {
  // The version the reader OPENED is pinned (adversary finding #2, 2026-09-10; round 2 #2): without
  // an explicit version the first load resolves "latest" ONCE, then the reader switches to the
  // explicit, immutable ["doc", id, N] query — so a feed invalidation (or a sibling full-page
  // query on the same "latest" key) can never swap the body or the ruling target under the reader
  // when a new version is published. A version pill re-requests another explicit version.
  const [requested, setRequested] = useState<number | null>(version ?? null);
  const [frozen, setFrozen] = useState<number | null>(null);
  useEffect(() => {
    setRequested(version ?? null);
    setFrozen(null);
  }, [docId, version]);
  const pinned = requested ?? frozen;
  const q = useQuery({
    queryKey: ["doc", docId, pinned],
    queryFn: () => getDocHtml(docId, pinned),
    // An explicit version is immutable: never refetched, never invalidated under the reader.
    ...(pinned != null ? { staleTime: Infinity, refetchOnWindowFocus: false, refetchOnReconnect: false } : {}),
  });
  const shown = q.data?.version ?? null;
  const qc = useQueryClient();
  const latestData = q.data;
  useEffect(() => {
    if (pinned == null && shown != null && latestData) {
      // Seed the immutable key with the body already on screen: the switch is instant, no
      // "Loading…" flash, and no second request for what the reader is already looking at.
      qc.setQueryData(["doc", docId, shown], latestData);
      setFrozen(shown);
    }
  }, [pinned, shown, latestData, qc, docId]);
  useEffect(() => {
    if (shown != null) onVersion?.(shown);
  }, [shown, onVersion]);
  const data = q.data;
  useEffect(() => {
    if (data) onDoc?.(data);
  }, [data, onDoc]);

  if (q.isPending) return <p className={ui.empty}>Loading document…</p>;
  if (q.isError)
    return (
      <p className={ui.banner} role="alert">
        Could not load {docId}: {(q.error as Error).message}
      </p>
    );
  return (
    <DocBody
      doc={q.data}
      onOpenDoc={onOpenDoc}
      onOpenTicket={onOpenTicket}
      onPickVersion={setRequested}
      versionsHosted={versionsHosted}
    />
  );
}

function DocBody({
  doc,
  onOpenDoc,
  onOpenTicket,
  onPickVersion,
  versionsHosted,
}: {
  doc: DocHtml;
  onOpenDoc?: (id: string) => void;
  onOpenTicket?: (id: string) => void;
  onPickVersion?: (v: number) => void;
  versionsHosted?: boolean;
}): React.JSX.Element {
  const as = identity();
  const qc = useQueryClient();
  const latest = doc.versions.length ? Math.max(...doc.versions) : doc.version;
  const [comment, setComment] = useState("");
  const [posted, setPosted] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);
  const outline = useMemo(() => outlineOf(doc.html), [doc.html]);

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

  // Outline entry i ↔ the i-th rendered heading: <Markdown> demotes every body heading one level
  // (h1→h2 … h3→h4) in document order, so the order — not the tag — is the join key.
  function scrollToHeading(i: number) {
    const el = bodyRef.current?.querySelectorAll<HTMLElement>("h2, h3, h4")[i];
    el?.scrollIntoView?.({ block: "start", behavior: "smooth" });
  }

  // LATCH (mirrors SignoffPane's own latch): a successful ruling refetches the doc and the ruled
  // criterion leaves signoff_criteria — the pane must stay mounted so the card can read "Passed"
  // without a navigation (c-a0b2f8ddda; g3a-doc.spec "approves … in one click" flaked on this gate
  // after the #36 side-pane rewrite). Once a doc has shown a sign-off, its pane stays for that doc.
  const signoffNow = (doc.signoff_criteria?.length ?? 0) > 0 || Boolean(doc.signoff_criterion);
  const signoffSeen = useRef<string | null>(null);
  if (signoffNow) signoffSeen.current = doc.id;
  const hasSignoff = signoffNow || signoffSeen.current === doc.id;
  const isLatest = doc.version === latest;
  const scopeHref = doc.scope.startsWith("epic-")
    ? `/epic/${encodeURIComponent(doc.scope)}`
    : `/ticket/${encodeURIComponent(doc.scope)}`;
  return (
    <div className={`${styles.doc} ${hasSignoff ? styles.withPane : ""}`} data-testid="doc-view">
      <div className={styles.reading}>
        <p className={styles.meta} data-testid="doc-meta">
          <span>{doc.doc_type.replace(/_/g, " ")}</span>
          <span aria-hidden="true">·</span>
          <span className={ui.idMono}>{doc.id}</span>
          <span aria-hidden="true">·</span>
          <span className={styles.versionNow} data-testid="version-now">
            v{doc.version} · {isLatest ? "latest" : `pinned (latest v${latest})`}
          </span>
        </p>
        <h1 className={styles.title} data-testid="doc-title">
          {stripScopeId(doc.title)}
        </h1>

        <div ref={bodyRef} onClick={onBodyClick} className={styles.body}>
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

      <aside className={styles.side} data-testid="doc-side">
        <div className={styles.sideSticky}>
          {hasSignoff ? (
            <section className={styles.pane} aria-label="Your sign-off">
              <SignoffPane doc={doc} />
            </section>
          ) : null}

          {outline.length > 0 ? (
            <nav className={styles.block} aria-label="Outline" data-testid="doc-outline">
              <div className={ui.sectionLabel}>Outline</div>
              <ul className={styles.outline}>
                {outline.map((h, i) => (
                  <li key={i} className={styles[`outlineL${h.level}`]}>
                    <button type="button" className={styles.outlineLink} onClick={() => scrollToHeading(i)}>
                      {h.text}
                    </button>
                  </li>
                ))}
              </ul>
            </nav>
          ) : null}

          <section className={styles.block} aria-label="Ownership" data-testid="doc-ownership">
            <div className={ui.sectionLabel}>Ownership</div>
            <dl className={styles.ownership}>
              <dt>Type</dt>
              <dd>{doc.doc_type.replace(/_/g, " ")}</dd>
              <dt>Owner</dt>
              <dd>{doc.owner_role}</dd>
              <dt>Scope</dt>
              <dd>
                {scopeIsTicket ? (
                  <Link
                    to={scopeHref}
                    className={ui.idMono}
                    onClick={(e) => {
                      if (onOpenTicket && !doc.scope.startsWith("epic-")) {
                        e.preventDefault();
                        onOpenTicket(doc.scope);
                      }
                    }}
                  >
                    {doc.scope}
                  </Link>
                ) : (
                  <span className={ui.idMono}>{doc.scope}</span>
                )}
              </dd>
            </dl>
          </section>

          {doc.versions.length > 1 ? (
            <details
              className={styles.block}
              data-testid="doc-history"
              aria-label={versionsHosted ? "History" : "Versions"}
              open
            >
              <summary className={styles.historySummary}>History</summary>
              <div className={styles.versions}>
                {doc.versions.map((v) => (
                  <button
                    key={v}
                    type="button"
                    className={`${styles.vpill} ${v === doc.version ? styles.vactive : ""}`}
                    aria-pressed={v === doc.version}
                    data-testid="version-pill"
                    onClick={() => onPickVersion?.(v)}
                  >
                    v{v}
                    {v === latest ? " · latest" : ""}
                  </button>
                ))}
              </div>
            </details>
          ) : null}
        </div>
      </aside>
    </div>
  );
}
