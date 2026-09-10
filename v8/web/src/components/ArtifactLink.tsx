import { useState } from "react";
import { authHeaders } from "../auth/identity";
import styles from "./ArtifactLink.module.css";

// An uploaded artifact opens through an AUTHENTICATED fetch → Blob → new tab. A plain
// <a href="/v1/artifacts/:id/content"> carries no X-Participant/X-Token header and 401s
// (adversary finding #5, 2026-09-10). The tab is opened before the await so a popup blocker
// sees a user gesture; the object URL is revoked once the tab has had a minute to load it.
export async function openArtifact(id: string): Promise<void> {
  const tab = window.open("", "_blank", "noopener");
  const res = await fetch(`/v1/artifacts/${encodeURIComponent(id)}/content`, { headers: authHeaders() });
  if (!res.ok) {
    tab?.close();
    throw new Error(`artifact ${id}: ${res.status}`);
  }
  const url = URL.createObjectURL(await res.blob());
  if (tab) tab.location.href = url;
  else window.location.assign(url);
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export function ArtifactLink({ id, label }: { id: string; label?: string }): React.JSX.Element {
  const [err, setErr] = useState<string | null>(null);
  return (
    <>
      <button
        type="button"
        className={styles.link}
        data-testid="artifact-link"
        data-artifact={id}
        onClick={() => {
          setErr(null);
          openArtifact(id).catch((e: unknown) => setErr(e instanceof Error ? e.message : String(e)));
        }}
      >
        {label ?? id}
      </button>
      {err ? <span className={styles.err}>{err}</span> : null}
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
