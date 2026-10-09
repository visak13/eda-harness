import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { DesignReview } from "./DesignReview";
import { pendingWork } from "./PendingNavigation";
import styles from "./DocumentSource.module.css";
export function DocumentSource({ docId, version, onLatest, readerOverride }: { docId: string; version: number; onLatest?: (v: number) => void; readerOverride?: boolean }): React.JSX.Element {
  const [source, setSource] = useState("");
  const sources = useQuery({ queryKey: ["doc-sources", docId], queryFn: () => api<{ id: string; title: string }[]>(`/v1/docs/${encodeURIComponent(docId)}/sources`) });
  const only = sources.data?.length === 1 ? sources.data[0].id : "";
  // p-77ab1bf1: a doc opened from a message link has one conversation; the person approving must not have to pick it to get Approve
  useEffect(() => { if (only) setSource((cur) => cur || only); }, [only]);
  return <section aria-label="Document conversation source">
    <label className={styles.source}>Conversation source <select className={styles.select} value={source} onChange={(e) => { if (!pendingWork()) setSource(e.target.value); }}>
      <option value="">Select source before commenting</option>
      {sources.data?.map((s) => <option key={s.id} value={s.id}>{s.title} · {s.id}</option>)}
    </select></label>
    {sources.isError ? <p role="alert">Could not load document sources.</p> : null}
    {sources.data?.length === 0 ? <p>No linked source conversation. Link this document to work before commenting.</p> : null}
    {source ? <DesignReview key={`${source}:${docId}:${version}`} source={source} docId={docId} version={version} onLatest={onLatest} readerOverride={readerOverride} /> : null}
  </section>;
}
