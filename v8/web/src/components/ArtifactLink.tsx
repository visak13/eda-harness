import { useState } from "react";
import { authHeaders } from "../auth/identity";
import styles from "./ArtifactLink.module.css";

// An uploaded artifact opens through an AUTHENTICATED fetch → Blob. A plain
// <a href="/v1/artifacts/:id/content"> carries no X-Participant/X-Token header and 401s
// (adversary finding #5, 2026-09-10). Round 2 #1: the board's Content-Disposition is HONOURED —
// only the four inline image types preview in a new tab; everything else (an SVG above all, which
// can script at top level from a same-origin blob: URL) is saved through <a download> and never
// navigated to. There is no current-tab fallback: a blocked popup degrades to the download.
export const PREVIEW_TYPES = new Set(["image/png", "image/jpeg", "image/gif", "image/webp"]);

/** The shareable SPA link for an artifact (promise #20): `${origin}/ui/artifact/<id>` — the /ui
 *  base rides import.meta.env.BASE_URL so the link follows the mount prefix like the router does. */
export function artifactShareUrl(id: string): string {
  const base = import.meta.env.BASE_URL.replace(/\/$/, "");
  return `${window.location.origin}${base}/artifact/${encodeURIComponent(id)}`;
}

/** Authenticated fetch of an artifact's bytes (the plain <a href> would 401 — finding #5). */
export async function fetchArtifactContent(id: string): Promise<Response> {
  const res = await fetch(`/v1/artifacts/${encodeURIComponent(id)}/content`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`artifact ${id}: ${res.status}`);
  return res;
}

export function dispositionOf(res: { headers: { get(name: string): string | null } }): { inline: boolean; filename: string | null } {
  const cd = res.headers.get("content-disposition") ?? "";
  const ctype = (res.headers.get("content-type") ?? "").split(";")[0].trim().toLowerCase();
  const m = /filename="?([^";]+)"?/i.exec(cd);
  return { inline: /^inline\b/i.test(cd) && PREVIEW_TYPES.has(ctype), filename: m ? m[1] : null };
}

function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.rel = "noopener";
  a.setAttribute("data-testid", "artifact-download");
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export async function openArtifact(id: string): Promise<void> {
  const res = await fetchArtifactContent(id);
  const { inline, filename } = dispositionOf(res);
  const blob = await res.blob();
  if (inline) {
    const url = URL.createObjectURL(blob);
    const tab = window.open(url, "_blank", "noopener");
    if (tab !== null || document.visibilityState === "hidden") {
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
      return;
    }
    URL.revokeObjectURL(url); // popup blocked → save it instead; never navigate this tab
  }
  saveBlob(blob, filename ?? id);
}

/** "Copy link" (promise #20): puts the shareable /ui/artifact/<id> URL on the clipboard and says so. */
export function CopyArtifactLink({ id, className }: { id: string; className?: string }): React.JSX.Element {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const url = artifactShareUrl(id);
  return (
    <button
      type="button"
      className={className ?? styles.copy}
      data-testid="artifact-copy-link"
      data-artifact={id}
      title={url}
      aria-label={`Copy link to ${id}`}
      onClick={() => {
        const write = navigator.clipboard?.writeText(url) ?? Promise.reject(new Error("no clipboard"));
        write.then(() => setState("copied")).catch(() => setState("failed"));
      }}
    >
      {state === "copied" ? "Link copied" : state === "failed" ? `Copy failed — ${url}` : "Copy link"}
    </button>
  );
}

export function ArtifactLink({ id, label }: { id: string; label?: string }): React.JSX.Element {
  return (
    <>
      <a className={styles.link} data-testid="artifact-link" data-artifact={id} href={artifactShareUrl(id)}>{label ?? id}</a>
      <CopyArtifactLink id={id} />
    </>
  );
}

const TOKEN = /(art-[0-9a-f]{6,}|https?:\/\/[^\s<>"']+)/g;

/** Message text with artifact tokens (`art-…`) and bare URLs rendered as links (finding #5). */
export function MessageText({ text, className }: { text: string; className?: string }): React.JSX.Element {
  const parts = text.split(TOKEN);
  return (
    <div className={className}>
      {parts.map((p, i) => {
        if (/^art-[0-9a-f]{6,}$/.test(p)) return <ArtifactLink key={i} id={p} />;
        if (/^https?:\/\//.test(p))
          return (
            <a key={i} href={p} target="_blank" rel="noreferrer">
              {p}
            </a>
          );
        return <span key={i}>{p}</span>;
      })}
    </div>
  );
}
