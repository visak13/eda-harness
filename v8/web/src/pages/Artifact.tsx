import { useEffect, useState } from "react";
import { useParams, Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { getArtifact } from "../api/endpoints";
import { BoardApiError } from "../api/client";
import {
  CopyArtifactLink,
  PREVIEW_TYPES,
  dispositionOf,
  fetchArtifactContent,
  openArtifact,
} from "../components/ArtifactLink";
import styles from "./Artifact.module.css";

// The shareable artifact page (promise #20): /ui/artifact/:id resolves GET /v1/artifacts/{id} and
// shows the uploaded thing in place — an inline preview for the four safe image types (the SAME
// allowlist openArtifact honours; everything else, an SVG above all, is never rendered inline) or a
// Download action — with the note, uploader, form and a "Copy link" that yields this page's URL.
// The bytes come through an AUTHENTICATED fetch → blob: URL (a plain <img src="/v1/..."> would 401).
export function ArtifactPage(): React.JSX.Element {
  const { id = "" } = useParams();
  const art = useQuery({ queryKey: ["artifact", id], queryFn: () => getArtifact(id), retry: false, enabled: !!id });
  const previewable = PREVIEW_TYPES.has((art.data?.content_type ?? "").toLowerCase());
  const [preview, setPreview] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!previewable || !id) return;
    let url: string | null = null;
    let cancelled = false;
    fetchArtifactContent(id)
      .then(async (res) => {
        // The board's own disposition still rules: a record claiming image/png but served as an
        // attachment is downloaded, never previewed.
        if (!dispositionOf(res).inline) return;
        const blob = await res.blob();
        if (cancelled) return;
        url = URL.createObjectURL(blob);
        setPreview(url);
      })
      .catch((e: unknown) => {
        if (!cancelled) setErr(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [id, previewable]);

  if (art.isPending) {
    return <p className={styles.calm}>Loading {id}…</p>;
  }
  if (art.isError) {
    const e = art.error;
    const hint = e instanceof BoardApiError ? (e.hint ?? e.message) : String(e);
    return (
      <div className={styles.page} data-testid="artifact-page">
        <h1 className={styles.title}>Artifact not found</h1>
        <p className={styles.calm} data-testid="artifact-error">
          {hint}
        </p>
        <Link to="/library/artifacts">← Library</Link>
      </div>
    );
  }
  const a = art.data;
  const name = a.filename || a.id;
  return (
    <div className={styles.page} data-testid="artifact-page" data-artifact={a.id}>
      <nav className={styles.crumb} aria-label="Breadcrumb">
        <Link to="/library/artifacts">← Library</Link>
      </nav>
      <h1 className={styles.title}>{name}</h1>
      <dl className={styles.meta}>
        <dt>Form</dt>
        <dd data-testid="artifact-form">{a.form}</dd>
        <dt>Uploaded by</dt>
        <dd data-testid="artifact-by">{a.created_by}</dd>
        {a.content_type ? (
          <>
            <dt>Type</dt>
            <dd>{a.content_type}</dd>
          </>
        ) : null}
      </dl>
      {a.note ? (
        <p className={styles.note} data-testid="artifact-note">
          {a.note}
        </p>
      ) : null}
      {preview ? (
        <img className={styles.preview} src={preview} alt={a.note || name} data-testid="artifact-preview" />
      ) : null}
      <div className={styles.actions}>
        {!preview ? (
          <button
            type="button"
            className={styles.button}
            data-testid="artifact-download"
            onClick={() => {
              setErr(null);
              openArtifact(a.id).catch((e: unknown) => setErr(e instanceof Error ? e.message : String(e)));
            }}
          >
            Download
          </button>
        ) : null}
        <CopyArtifactLink id={a.id} className={styles.button} />
      </div>
      {err ? (
        <p className={styles.calm} data-testid="artifact-error">
          {err}
        </p>
      ) : null}
    </div>
  );
}
