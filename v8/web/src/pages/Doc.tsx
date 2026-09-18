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
  const [params] = useSearchParams();
  const versionParam = params.get("version");
  const version = versionParam ? Number(versionParam) : undefined;

  // Round 2 #2: the page no longer runs its own ["doc", id, null] query — that shared "latest" key
  // refetched on every feed invalidation and moved the reader's body under it. DocView pins the
  // version and reports the document it shows.
  const [doc, setDoc] = useState<DocHtml | null>(null);

  return (
    <div className={styles.page}>
      <nav className={styles.crumb} aria-label="Breadcrumb">
        {doc ? (
          <Link to={`/epic/${encodeURIComponent(doc.scope)}`}><Icon name="back" /> {doc.scope}</Link>
        ) : (
          <Link to="/library/documents"><Icon name="back" /> Library</Link>
        )}
      </nav>
      <div className={styles.reader}>
        <DocView docId={id} version={version} onDoc={setDoc} source={params.get("source")} request={params.get("request")} />
      </div>
    </div>
  );
}
