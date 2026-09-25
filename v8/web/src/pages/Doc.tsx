import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import type { DocHtml } from "../api/types";
import { DocView } from "../components/DocView";
import styles from "./Doc.module.css";
import { Icon } from "../components/Icon";

// The kept full-page doc reader (/ui/doc/:id → /doc/:id, design §12/§14/§17). It is the same
// DocView the §17 drawer hosts — the 650/462 reader in a 1112px panel, centred (Astra ruling #36
// item 2) — with a crumb back to the scope. DocView owns the title (the page's only <h1>).
// ?version=n pins a version (the History pills inside switch it). The one-click sign-off pane and
// the comment box are DocView's; on the full page nested links navigate normally (no drawer).
export function DocPage(): React.JSX.Element {
  const { id = "" } = useParams();
  const [params, setParams] = useSearchParams();
  // ?v=N (S22 consult #6: what the viewer writes when a version is chosen) or the older ?version=N.
  const versionParam = params.get("v") ?? params.get("version");
  const version = versionParam ? Number(versionParam) : undefined;

  // Round 2 #2: the page no longer runs its own ["doc", id, null] query — that shared "latest" key
  // refetched on every feed invalidation and moved the reader's body under it. DocView pins the
  // version and reports the document it shows.
  const [doc, setDoc] = useState<DocHtml | null>(null);
  // S19 D11: opened from a review ("Open in tab"), the review header's crumb is the way back to the
  // source conversation (by its title) — no second crumb with the raw scope id.
  const source = params.get("source");

  return (
    <div className={styles.page}>
      {source ? null : <nav className={styles.crumb} aria-label="Breadcrumb">
        {doc ? (
          <Link to={`/epic/${encodeURIComponent(doc.scope)}`}><Icon name="back" /> {doc.scope}</Link>
        ) : (
          <Link to="/library/documents"><Icon name="back" /> Library</Link>
        )}
      </nav>}
      <div className={source ? `${styles.reader} ${styles.review}` : styles.reader}>
        <DocView docId={id} version={version} onDoc={setDoc} onPick={(v) => {
          const p = new URLSearchParams(params);
          p.delete("version");
          p.set("v", String(v));
          setParams(p, { replace: true });
        }} source={source} request={params.get("request")} focusLines={params.get("line")} />
      </div>
    </div>
  );
}
