import { Link, useParams, useSearchParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { getDocHtml } from "../api/endpoints";
import { DocView } from "../components/DocView";
import styles from "./Doc.module.css";

// The kept full-page doc reader (/ui/doc/:id → /doc/:id, design §12/§14/§17). It is the same
// DocView the §17 drawer hosts, at full width, with a Georgia title and a crumb back to the scope.
// ?version=n pins a version (the version pills inside switch it). The one-click sign-off pane and
// the comment box are DocView's; on the full page nested links navigate normally (no drawer).
export function DocPage(): React.JSX.Element {
  const { id = "" } = useParams();
  const [params] = useSearchParams();
  const versionParam = params.get("version");
  const version = versionParam ? Number(versionParam) : undefined;

  const doc = useQuery({ queryKey: ["doc", id, version ?? null], queryFn: () => getDocHtml(id, version) });

  return (
    <div className={styles.page}>
      <nav className={styles.crumb} aria-label="Breadcrumb">
        {doc.data ? (
          <Link to={`/epic/${encodeURIComponent(doc.data.scope)}`}>← {doc.data.scope}</Link>
        ) : (
          <Link to="/library/documents">← Library</Link>
        )}
      </nav>
      <h1 className={styles.title}>{doc.data?.title ?? "Document"}</h1>
      <DocView docId={id} version={version} />
    </div>
  );
}
